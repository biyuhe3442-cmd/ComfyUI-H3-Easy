"""End-to-end H3 Easy generation: plan -> condition -> sample segments -> decode.

Two ways in: ``run`` for the node's own prompt box (one mode, equal segments, each
continuing the one before) and ``run_shot_list`` for a director shot list, where
every shot brings its own mode, length and media and either continues the shot
before it or starts with a cut. A shot list keeps its finished shots (shotcache.py),
so a later run only samples the shots whose inputs changed.
"""

from __future__ import annotations

import dataclasses
import math
import time
from dataclasses import dataclass, field

import torch
import torch.nn.functional as F

import comfy.model_management as mm
import comfy.sample
import comfy.samplers
import comfy.utils
import latent_preview
from comfy_extras.nodes_custom_sampler import Guider_Basic

from . import assemble, continuation, refs, shotcache, shotlist, timing
from .conditioning import ConditioningBuilder, empty_av_latent
from .media import Media
from .prompts import split_prompts
from .tst import apply_tst

MODE_IMAGE = "图文模式（文生 / 首尾帧）"
MODE_REFERENCE = "参考模式（多图 / 视频参考）"

UPSCALE_PIXEL = "像素放大（推荐）"
UPSCALE_LATENT = "latent 插值（最快）"
UPSCALE_METHODS = [UPSCALE_PIXEL, UPSCALE_LATENT]


@dataclass
class Settings:
    mode: str
    prompt: str
    segments: int
    segment_seconds: float
    width: int
    height: int
    steps: int
    sampler_name: str
    scheduler: str
    seed: int
    lock_audio: bool = True
    progressive: bool = True
    progressive_scale: float = 0.7
    progressive_switch: float = 0.35
    upscale_method: str = UPSCALE_PIXEL
    progressive_continuation: bool = False
    tst: bool = False
    tst_strength: float = 0.2
    low_vram: bool = True
    ref_image_size: str = "match"
    shot_versions: dict = field(default_factory=dict)  # shot list: shot number -> which take of it (1 = first)


@dataclass
class Shot:
    """One H3 generation on the timeline."""
    name: str        # how the report calls it
    prompt: str
    reference: bool  # ref2va model, otherwise fl2va
    media: Media     # exactly what this generation uses


@dataclass
class Result:
    images: torch.Tensor
    audio: dict
    report: str
    log: list[str] = field(default_factory=list)
    clips: list[tuple[int, int]] = field(default_factory=list)  # frame range of each separately usable part


class Reporter:
    def __init__(self):
        self.lines: list[str] = []
        self.t0 = time.perf_counter()

    def add(self, text: str):
        stamp = time.perf_counter() - self.t0
        line = f"[{stamp:7.1f}s] {text}"
        self.lines.append(line)
        print(f"[H3 Easy] {text}", flush=True)

    def text(self) -> str:
        return "\n".join(self.lines)


def aspect_mismatch(image: torch.Tensor, width: int, height: int, tolerance: float = 0.05) -> bool:
    """True when an IMAGE [B, H, W, C] differs from the output aspect ratio by more than ~5%."""
    h, w = image.shape[1], image.shape[2]
    return abs(math.log((w / h) / (width / height))) > tolerance


def crop_to_aspect(image: torch.Tensor, width: int, height: int) -> torch.Tensor:
    """Center-crop an IMAGE [B, H, W, C] to the width:height aspect ratio (no resizing)."""
    h, w = image.shape[1], image.shape[2]
    target = width / height
    if w / h > target:  # wider than the output: trim left and right
        new_w = max(1, round(h * target))
        x = (w - new_w) // 2
        return image[:, :, x:x + new_w]
    new_h = max(1, round(w / target))
    y = (h - new_h) // 2
    return image[:, y:y + new_h]


def _sigmas(model, scheduler: str, steps: int) -> torch.Tensor:
    return comfy.samplers.calculate_sigmas(model.get_model_object("model_sampling"), scheduler, steps).cpu()


def _sample(model, positive, latent, sigmas, sampler, seed, noise=None, mask=None, x0_store=None):
    guider = Guider_Basic(model)
    guider.set_conds(positive)
    if noise is None:
        noise = comfy.sample.prepare_noise(latent, seed)
    callback = latent_preview.prepare_callback(model, sigmas.shape[-1] - 1, x0_store)
    out = guider.sample(noise, latent, sampler, sigmas, denoise_mask=mask, callback=callback,
                        disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED, seed=seed)
    return out.to(mm.intermediate_device())


def _scaled_size(width: int, height: int, scale: float) -> tuple[int, int]:
    w = max(256, int(round(width * scale / 32)) * 32)
    h = max(256, int(round(height * scale / 32)) * 32)
    return min(w, width), min(h, height)


def _upscale_video(x0_video, method, video_vae, width, height, learned_upscaler, report, label):
    lat_h, lat_w = height // 16, width // 16
    target_t = x0_video.shape[2]
    if learned_upscaler is not None:
        report.add(f"{label}放大：学习式 upscaler")
        up = learned_upscaler.upscale_clean_video(x0_video, target_h=lat_h, target_w=lat_w)
        return up.to("cpu", torch.float32)
    if method == UPSCALE_LATENT:
        report.add(f"{label}放大：latent 三线性插值")
        return F.interpolate(x0_video.float(), size=(target_t, lat_h, lat_w), mode="trilinear", align_corners=False)
    report.add(f"{label}放大：像素放大（低分辨率解码 → 放大 → 重新编码）")
    frames = video_vae.decode(x0_video)
    if frames.ndim == 5:
        frames = frames.reshape(-1, frames.shape[-3], frames.shape[-2], frames.shape[-1])
    frames = comfy.utils.common_upscale(frames.movedim(-1, 1), width, height, "bicubic", "disabled")
    frames = frames.movedim(1, -1).clamp(0.0, 1.0)
    up = video_vae.encode(frames)
    del frames
    if up.shape[2] != target_t:
        raise RuntimeError(f"pixel upscale produced {up.shape[2]} latent slots, expected {target_t}")
    return up.to("cpu", torch.float32)


def _progressive_first_segment(model, builder, positive, segment, shot, settings, sampler, sigmas, seed,
                               learned_upscaler, report):
    """Low-resolution prefix, lift the clean estimate, finish at full resolution."""
    low_w, low_h = _scaled_size(settings.width, settings.height, settings.progressive_scale)
    if (low_w, low_h) == (settings.width, settings.height):
        return None
    model_sampling = model.get_model_object("model_sampling")
    shift = float(getattr(model_sampling, "shift", 12.0))
    k = timing.handoff_index(sigmas.tolist(), shift, settings.progressive_switch)
    report.add(f"{shot.name}渐进加速：前 {k} 步 {low_w}×{low_h}，后 {len(sigmas) - 1 - k} 步 "
               f"{settings.width}×{settings.height}（切换 sigma={float(sigmas[k]):.3f}）")

    low_positive = builder.rescale_keyframes(positive, low_w, low_h, shot.media)
    low_latent = empty_av_latent(low_w, low_h, segment.frames)
    x0_store: dict = {}
    low_out = _sample(model, low_positive, low_latent, sigmas[:k + 1], sampler, seed, x0_store=x0_store)
    x0 = x0_store.get("x0")
    if x0 is None or not getattr(x0, "is_nested", False):
        raise RuntimeError("progressive sampling did not report a clean estimate")
    x0_video = x0.unbind()[0].to("cpu", torch.float32)
    _, low_audio = continuation.split_av(low_out)
    del low_out, x0, x0_store
    if settings.low_vram:
        mm.soft_empty_cache()

    up = _upscale_video(x0_video, settings.upscale_method, builder.video_vae, settings.width, settings.height,
                        learned_upscaler, report, shot.name)
    del x0_video
    generator = torch.Generator().manual_seed((seed + 0x5EED) & 0xFFFFFFFFFFFFFFFF)
    noise = torch.randn(up.shape, generator=generator, dtype=torch.float32)
    sigma = sigmas[k:k + 1].float()
    restarted = model_sampling.noise_scaling(sigma, noise, up)
    start_video = model_sampling.inverse_noise_scaling(sigma, restarted)
    start = continuation.join_av(start_video, low_audio.to(torch.float32))
    zeros = continuation.join_av(torch.zeros_like(start_video), torch.zeros_like(low_audio, dtype=torch.float32))
    return _sample(model, positive, start, sigmas[k:], sampler, seed, noise=zeros)


def snap_size(value) -> int:
    """H3 works on a 32-pixel grid; widths/heights may arrive unaligned from links or typed values."""
    return max(256, min(4096, int(round(float(value) / 32)) * 32))


def _downscale_context(video_ctx, method, video_vae, width, height):
    """The 39-frame continuation context at the low-resolution stage's size."""
    lat_h, lat_w = height // 16, width // 16
    if method == UPSCALE_LATENT:
        return F.interpolate(video_ctx.float(), size=(video_ctx.shape[2], lat_h, lat_w), mode="area")
    frames = video_vae.decode(video_ctx)
    if frames.ndim == 5:
        frames = frames.reshape(-1, frames.shape[-3], frames.shape[-2], frames.shape[-1])
    frames = comfy.utils.common_upscale(frames.movedim(-1, 1), width, height, "area", "disabled")
    low = video_vae.encode(frames.movedim(1, -1).clamp(0.0, 1.0))
    if low.shape[2] != video_ctx.shape[2]:
        raise RuntimeError(f"context downscale produced {low.shape[2]} latent slots, expected {video_ctx.shape[2]}")
    return low.to("cpu", torch.float32)


def _progressive_continuation(model, builder, positive, video_ctx, audio_ctx, segment, shot, settings,
                              sampler, sigmas, seed, learned_upscaler, report):
    """Experimental: progressive sampling for a continuation segment.

    The high-noise steps run at low resolution with a downscaled copy of the 39-frame
    context kept fixed. At the switch the clean estimate is upscaled, the exact
    full-resolution context is put back, and the rest is sampled at full resolution from
    a fresh noise draw at the switch sigma, again with the context kept fixed.
    """
    low_w, low_h = _scaled_size(settings.width, settings.height, settings.progressive_scale)
    if (low_w, low_h) == (settings.width, settings.height):
        return None
    model_sampling = model.get_model_object("model_sampling")
    shift = float(getattr(model_sampling, "shift", 12.0))
    k = timing.handoff_index(sigmas.tolist(), shift, settings.progressive_switch)
    report.add(f"{shot.name}渐进加速（实验）：前 {k} 步 {low_w}×{low_h}，后 {len(sigmas) - 1 - k} 步 "
               f"{settings.width}×{settings.height}")

    low_positive = builder.rescale_keyframes(positive, low_w, low_h, shot.media)
    low_ctx = _downscale_context(video_ctx, settings.upscale_method, builder.video_vae, low_w, low_h)
    low_latent, low_mask = continuation.apply_prefix(empty_av_latent(low_w, low_h, segment.frames), low_ctx, audio_ctx)
    x0_store: dict = {}
    _sample(model, low_positive, low_latent, sigmas[:k + 1], sampler, seed, mask=low_mask, x0_store=x0_store)
    x0 = x0_store.get("x0")
    if x0 is None or not getattr(x0, "is_nested", False):
        raise RuntimeError("progressive sampling did not report a clean estimate")
    x0_video, x0_audio = (t.to("cpu", torch.float32) for t in x0.unbind()[:2])
    # the sampler carries audio scaled onto the video schedule; back to latent units
    x0_audio = x0_audio / float(getattr(model_sampling, "audio_scale", 1.0))
    del x0, x0_store, low_latent, low_mask
    if settings.low_vram:
        mm.soft_empty_cache()

    up = _upscale_video(x0_video, settings.upscale_method, builder.video_vae, settings.width, settings.height,
                        learned_upscaler, report, shot.name)
    del x0_video
    clean, mask = continuation.apply_prefix(continuation.join_av(up, x0_audio), video_ctx, audio_ctx)
    generator = torch.Generator().manual_seed((seed + 0x5EED) & 0xFFFFFFFFFFFFFFFF)
    noise = continuation.join_av(torch.randn(up.shape, generator=generator, dtype=torch.float32),
                                 torch.randn(x0_audio.shape, generator=generator, dtype=torch.float32))
    # starting at sigma_k the sampler forms sigma_k * noise + (1 - sigma_k) * clean, and the
    # mask keeps re-noising the exact context with the same noise at every later step
    return _sample(model, positive, clean, sigmas[k:], sampler, seed, noise=noise, mask=mask)


def _select_references(prompts: list[str], full_prompt: str, media: Media, report: Reporter):
    """Give each segment only the references its prompt names (see refs.py)."""
    catalog = refs.Catalog(
        pictures=len(media.ref_images),
        video_sound=tuple(i < len(media.video_audios) and media.video_audios[i] is not None
                          for i in range(len(media.videos))),
        audios=len(media.audios))
    missing = refs.select(full_prompt, catalog, set()).missing
    if missing:
        report.add(f"提示：提示词里的 {'、'.join(missing)} 在素材加载器里没有对应素材")
    active = refs.active_types(full_prompt, catalog)
    if not active:
        return prompts, [None] * len(prompts)
    selections = [refs.select(prompt, catalog, active) for prompt in prompts]
    report.add("参考素材按段分配：每段只用它提示词里提到的（编号已按这一段重新排）")
    for i, selection in enumerate(selections):
        report.add(f"  第 {i + 1} 段：{refs.describe(selection)}")
    unused = []
    for kind, count, label in (("pictures", catalog.pictures, "图"), ("videos", len(catalog.video_sound), "视频"),
                               ("audios", catalog.audios, "音频")):
        if kind in active:
            used = {i for selection in selections for i in getattr(selection, kind)}
            unused += [f"{label}{i + 1}" for i in range(count) if i not in used]
    if unused:
        report.add(f"提示：{'、'.join(unused)} 没有在任何一段的提示词里提到，没有使用")
    return [s.prompt for s in selections], [(s.pictures, s.videos, s.audios) for s in selections]


def _snapped(settings: Settings, report: Reporter) -> Settings:
    width, height = snap_size(settings.width), snap_size(settings.height)
    if (width, height) == (settings.width, settings.height):
        return settings
    report.add(f"宽高已对齐到 32 的倍数：{settings.width}×{settings.height} → {width}×{height}")
    return dataclasses.replace(settings, width=width, height=height)


def _crop_keyframes(media: Media, settings: Settings, report: Reporter, name: str = "") -> Media:
    """The output keeps the size you set. Core would stretch a first or last frame of another
    shape, so crop it to the output's aspect ratio first (keeps the middle, no distortion)."""
    cropped = {}
    for label, attr in (("首帧", "first_frame"), ("尾帧", "last_frame")):
        frame = getattr(media, attr)
        if frame is not None and aspect_mismatch(frame, settings.width, settings.height):
            cropped[attr] = crop_to_aspect(frame, settings.width, settings.height)
            h, w = frame.shape[1], frame.shape[2]
            ch, cw = cropped[attr].shape[1], cropped[attr].shape[2]
            report.add(f"{name}{label} {w}×{h} 和输出 {settings.width}×{settings.height} 比例不同：已居中裁切成 {cw}×{ch}"
                       f"（只保留中间部分，不拉伸）")
    return dataclasses.replace(media, **cropped) if cropped else media


def _picked(media: Media, picks: tuple | None) -> Media:
    """The loader's references one segment uses; ``picks`` = (pictures, videos, audios) indices, None = all."""
    if picks is None:
        return Media(ref_images=media.ref_images, videos=media.videos, video_audios=media.video_audios,
                     audios=media.audios)
    pictures, videos, audios = picks
    return Media(ref_images=[media.ref_images[i] for i in pictures],
                 videos=[media.videos[i] for i in videos],
                 video_audios=[media.video_audios[i] if i < len(media.video_audios) else None for i in videos],
                 audios=[media.audios[i] for i in audios])


def run(settings: Settings, model, clip, video_vae, audio_vae, media: Media | None,
        learned_upscaler=None) -> Result:
    """The node's own prompt box: one mode, equal segments, each continuing the one before."""
    report = Reporter()
    settings = _snapped(settings, report)
    media = media or Media()
    image_mode = settings.mode == MODE_IMAGE
    segments = timing.plan_segments(settings.segments, settings.segment_seconds)
    windows = [s.new_window_seconds for s in segments]
    prompts, layout = split_prompts(settings.prompt, windows)
    total_seconds = assemble.total_seconds(segments)

    lock_source = media.lock_source if image_mode and settings.lock_audio else None

    report.add(f"模式：{'图文' if image_mode else '参考'}；素材：{media.describe()}")
    report.add(f"分段：{len(segments)} 段，总时长 {total_seconds:.2f}s，分辨率 {settings.width}×{settings.height}，"
               f"提示词格式：{ {'timeline': '时间轴', 'list': '分隔列表', 'fixed': '统一'}[layout] }")
    for seg in segments:
        a, b = seg.window_seconds
        report.add(f"  第 {seg.index + 1} 段：{a:.2f}–{b:.2f}s（{seg.frames} 帧，新增 {seg.new_frames} 帧）")
    if lock_source is not None:
        report.add("锁定音频（音频1）：生成时用它引导口型/节奏，最终输出原音频")
        if len(media.audios) > 1:
            report.add("提示：图文模式只用音频1 锁定，其余音频不使用")
    has_ref_audio = bool(media.audios) or any(a is not None for a in media.video_audios)
    if not image_mode and has_ref_audio:
        report.add("参考模式：音频只作为参考，最终输出 H3 生成的声音")
    if not image_mode and not (media.ref_images or media.videos or media.audios):
        report.add("提示：参考模式没有任何参考素材，效果等同文生视频")
    if image_mode and (media.ref_images or media.videos):
        report.add("提示：图文模式不使用参考图/参考视频（要用请切到参考模式）")
    if not image_mode and (media.first_frame is not None or media.last_frame is not None):
        report.add("提示：参考模式不使用首帧/尾帧（要用请切到图文模式）")
    picks = [None] * len(segments)
    if image_mode:
        media = _crop_keyframes(media, settings, report)
    else:
        prompts, picks = _select_references(prompts, settings.prompt, media, report)
    shots = []
    for seg, prompt, pick in zip(segments, prompts, picks):
        if image_mode:
            # the first frame opens the video and the last frame closes it
            own = Media(first_frame=media.first_frame if seg.index == 0 else None,
                        last_frame=media.last_frame if seg.index == len(segments) - 1 else None)
        else:
            own = _picked(media, pick)
        shots.append(Shot(f"第 {seg.index + 1} 段", prompt, not image_mode, own))
    seeds = [(settings.seed + seg.index) & 0xFFFFFFFFFFFFFFFF for seg in segments]
    return _generate(settings, report, {not image_mode: model}, clip, video_vae, audio_vae, shots, segments,
                     lock_source, learned_upscaler, seeds, clips=[(0, segments[-1].end_frame)])


def run_shot_list(settings: Settings, models: dict, clip, video_vae, audio_vae, cards: list[shotlist.Shot],
                  medias: list[Media], learned_upscaler=None) -> Result:
    """A director shot list: one generation per card, with that card's mode, length and media.

    ``models`` maps reference mode (True) and image mode (False) to their models.
    """
    report = Reporter()
    settings = _snapped(settings, report)
    continues, notes = [], []
    for index, (card, media) in enumerate(zip(cards, medias)):
        joined = card.continues and index > 0
        if joined and card.mode != cards[index - 1].mode:
            joined = False
            notes.append(f"提示：镜头 {card.number} 和上一个镜头的模式不同，不能续写，按硬切处理")
        elif joined and media.first_frame is not None:
            joined = False
            notes.append(f"提示：镜头 {card.number} 有自己的首帧，不能续写，按硬切处理")
        continues.append(joined)
    segments = timing.plan_shots([(card.seconds, joined) for card, joined in zip(cards, continues)])

    report.add(f"出片清单：{len(cards)} 个镜头，总时长 {assemble.total_seconds(segments):.2f}s，"
               f"分辨率 {settings.width}×{settings.height}")
    report.add("模式、段数、每段秒数、锁定音频、种子以清单为准，节点上的这几项不生效")
    # everything outside the card that a shot's result depends on
    common = [settings.width, settings.height, settings.steps, settings.sampler_name, settings.scheduler,
              settings.progressive, settings.progressive_scale, settings.progressive_switch,
              settings.upscale_method, settings.progressive_continuation, settings.tst and settings.tst_strength,
              settings.ref_image_size, type(learned_upscaler).__name__, shotcache.source(getattr(clip, "patcher", None))]
    sources = {reference: [shotcache.source(model), float(getattr(model.get_model_object("model_sampling"), "shift", 0))]
               for reference, model in models.items() if model is not None}
    shots, seeds, keys = [], [], []
    for card, media, seg in zip(cards, medias, segments):
        name = f"镜头 {card.number}"
        reference = card.mode == shotlist.REFERENCE
        # a shot keeps its seed from run to run; "re-roll" in the panel moves it to its next take
        seeds.append((card.number * 1_000_003 + settings.shot_versions.get(card.number, 1)) & 0xFFFFFFFFFFFFFFFF)
        keys.append(shotcache.key(card.prompt, card.mode, seg.frames, media.stamp, seeds[-1], common, sources[reference],
                                  keys[-1] if seg.prefix_frames else ""))
        a, b = seg.new_window_seconds
        join = "续写" if seg.prefix_frames else "硬切" if seg.index else "开头"
        report.add(f"  {name}：{a:.2f}–{b:.2f}s，{'参考模式' if reference else '首帧模式'}，{join}，"
                   f"清单 {card.seconds:g} 秒 → 实际 {b - a:.2f} 秒，素材：{'、'.join(media.files) or '无'}")
        if round(card.seconds * timing.FPS) > seg.new_frames + 3:
            notes.append(f"提示：{name} 要 {card.seconds:g} 秒，{'续写的镜头' if seg.prefix_frames else '一个镜头'}"
                         f"最长 {seg.new_frames / timing.FPS:.2f} 秒")
        if not reference and (len(card.pictures) > 2 or card.videos or card.audios):
            notes.append(f"提示：{name} 是首帧模式，只用第 1 张图做首帧、第 2 张图做尾帧，其余素材不使用")
        unlisted = shotlist.unlisted_tags(card)
        if unlisted:
            notes.append(f"提示：{name} 的提示词里有 {'、'.join(unlisted)}，References 里没有列出对应素材")
        if not reference:
            media = _crop_keyframes(media, settings, report, name + " ")
        shots.append(Shot(name + " ", card.prompt, reference, media))  # the report puts what happened right after it
    aspect = cards[0].aspect
    if aspect and abs(math.log((settings.width / settings.height) / (aspect[0] / aspect[1]))) > 0.05:
        notes.append(f"提示：清单写的画幅是 {aspect[0]}:{aspect[1]}，节点设的输出是 {settings.width}×{settings.height}，"
                     f"按节点设的出")
    for note in notes:
        report.add(note)
    return _generate(settings, report, models, clip, video_vae, audio_vae, shots, segments, None, learned_upscaler,
                     seeds, clips=[(seg.start_frame + seg.prefix_frames, seg.end_frame) for seg in segments], keys=keys)


def _generate(settings: Settings, report: Reporter, models: dict, clip, video_vae, audio_vae, shots: list[Shot],
              segments: list[timing.Segment], lock_source: dict | None, learned_upscaler, seeds: list[int],
              clips, keys: list[str] | None = None) -> Result:
    """``lock_source`` (image mode, one continuous run) guides every shot and replaces the soundtrack.

    With ``keys``, a shot whose latents are already stored under its key is not sampled again.
    """
    total_seconds = assemble.total_seconds(segments)
    stored = [shotcache.load(key) for key in keys] if keys else [None] * len(shots)

    # 1. conditioning for every shot that will be sampled (text encoder runs here, then can be unloaded)
    builder = ConditioningBuilder(clip, video_vae, audio_vae, settings.width, settings.height,
                                  settings.ref_image_size)
    conds = []
    for seg, shot, done in zip(segments, shots, stored):
        mm.throw_exception_if_processing_interrupted()
        if done is not None:
            conds.append(None)
            continue
        if shot.reference:
            positive, latent = builder.reference_mode(shot.prompt, seg.frames, shot.media)
        else:
            guide = None
            if lock_source is not None:
                guide = assemble.slice_audio(lock_source, *seg.window_seconds)
            positive, latent = builder.image_mode(shot.prompt, seg.frames, shot.media, guide)
        conds.append((positive, latent["samples"]))
    report.add("条件编码完成")
    if settings.low_vram:
        mm.unload_all_models()
        mm.soft_empty_cache()

    # 2. sampling
    sampler = comfy.samplers.sampler_object(settings.sampler_name)
    use_tst = settings.tst and settings.tst_strength > 0
    if use_tst:
        report.add(f"TST 防闪烁：强度 {settings.tst_strength:.2f}")
    prepared, tst_states = {}, []
    for reference in sorted({shot.reference for shot, done in zip(shots, stored) if done is None}):
        model = models[reference]
        sigmas = _sigmas(model, settings.scheduler, settings.steps)
        if use_tst:
            model, state = apply_tst(model, settings.tst_strength, sigmas.tolist())
            tst_states.append(state)
        prepared[reference] = (model, sigmas)

    carry_audio = lock_source is None
    video_latents, audio_latents = [], []
    previous = None
    for seg, shot, cond, done, seed in zip(segments, shots, conds, stored, seeds):
        mm.throw_exception_if_processing_interrupted()
        if done is not None:
            video_latents.append(done[0])
            audio_latents.append(done[1])
            previous = continuation.join_av(*done)
            report.add(f"{shot.name}沿用上次的结果，没有重新生成")
            continue
        positive, target = cond
        model, sigmas = prepared[shot.reference]
        started = time.perf_counter()
        out = None
        if not seg.prefix_frames:
            if settings.progressive:
                out = _progressive_first_segment(model, builder, positive, seg, shot, settings, sampler, sigmas,
                                                 seed, learned_upscaler, report)
            if out is None:
                out = _sample(model, positive, target, sigmas, sampler, seed)
        else:
            video_ctx, audio_ctx = continuation.tail_context(previous)
            audio_ctx = audio_ctx if carry_audio else None
            if settings.progressive_continuation:
                out = _progressive_continuation(model, builder, positive, video_ctx, audio_ctx, seg, shot,
                                                settings, sampler, sigmas, seed, learned_upscaler, report)
            if out is None:
                latent, mask = continuation.apply_prefix(target, video_ctx, audio_ctx)
                out = _sample(model, positive, latent, sigmas, sampler, seed, mask=mask)
            out = continuation.restore_prefix(out, video_ctx, audio_ctx)
        video, audio = continuation.split_av(out)
        video_latents.append(video.to("cpu", torch.float32))
        audio_latents.append(audio.to("cpu", torch.float32))
        previous = continuation.join_av(video_latents[-1], audio_latents[-1])
        if keys:
            shotcache.save(keys[seg.index], video_latents[-1], audio_latents[-1])
        report.add(f"{shot.name}采样完成，用时 {time.perf_counter() - started:.1f}s")
        if settings.low_vram:
            mm.soft_empty_cache()
    scales = [scale for state in tst_states for scale in state.scales]
    if scales:
        report.add(f"TST 平均放大系数 {sum(scales) / len(scales):.4f}，最大 {max(scales):.4f}")

    # 3. decode and join
    if settings.low_vram:
        mm.unload_all_models()
        mm.soft_empty_cache()
    images = assemble.decode_video(
        video_vae, video_latents, segments,
        on_segment=lambda i: (report.add(f"{shots[i].name}解码完成"), settings.low_vram and mm.soft_empty_cache()))
    if lock_source is not None:
        audio_out = assemble.fit_audio(lock_source, total_seconds)
        report.add("输出音频：原音频（已对齐到视频时长）")
    else:
        from comfy_extras.nodes_audio import vae_decode_audio
        parts = []
        for run_of in assemble.chains(segments):
            joined = assemble.join_audio_latents([audio_latents[i] for i in run_of])
            seconds = (segments[run_of[-1]].end_frame - segments[run_of[0]].start_frame) / timing.FPS
            parts.append(assemble.fit_audio(vae_decode_audio(audio_vae, {"samples": joined}), seconds))
        audio_out = assemble.fit_audio({"waveform": torch.cat([part["waveform"] for part in parts], dim=-1),
                                        "sample_rate": parts[0]["sample_rate"]}, total_seconds)
        report.add("输出音频：H3 生成")
    report.add(f"完成：{images.shape[0]} 帧（{images.shape[0] / timing.FPS:.2f}s）")
    return Result(images=images, audio=audio_out, report=report.text(), clips=clips)
