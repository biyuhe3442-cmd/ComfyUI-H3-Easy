"""End-to-end H3 Easy generation: plan -> condition -> sample segments -> decode."""

from __future__ import annotations

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

from . import assemble, continuation, timing
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
    tst: bool = False
    tst_strength: float = 0.2
    low_vram: bool = True
    ref_image_size: str = "match"


@dataclass
class Result:
    images: torch.Tensor
    audio: dict
    report: str
    log: list[str] = field(default_factory=list)


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


def _upscale_video(x0_video, method, video_vae, width, height, learned_upscaler, report):
    lat_h, lat_w = height // 16, width // 16
    target_t = x0_video.shape[2]
    if learned_upscaler is not None:
        report.add("第 1 段放大：学习式 upscaler")
        up = learned_upscaler.upscale_clean_video(x0_video, target_h=lat_h, target_w=lat_w)
        return up.to("cpu", torch.float32)
    if method == UPSCALE_LATENT:
        report.add("第 1 段放大：latent 三线性插值")
        return F.interpolate(x0_video.float(), size=(target_t, lat_h, lat_w), mode="trilinear", align_corners=False)
    report.add("第 1 段放大：像素放大（低分辨率解码 → 放大 → 重新编码）")
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


def _progressive_first_segment(model, builder, positive, segment, settings, sampler, sigmas,
                               learned_upscaler, report):
    """Low-resolution prefix, lift the clean estimate, finish at full resolution."""
    low_w, low_h = _scaled_size(settings.width, settings.height, settings.progressive_scale)
    if (low_w, low_h) == (settings.width, settings.height):
        return None
    model_sampling = model.get_model_object("model_sampling")
    shift = float(getattr(model_sampling, "shift", 12.0))
    k = timing.handoff_index(sigmas.tolist(), shift, settings.progressive_switch)
    report.add(f"第 1 段渐进加速：前 {k} 步 {low_w}×{low_h}，后 {len(sigmas) - 1 - k} 步 "
               f"{settings.width}×{settings.height}（切换 sigma={float(sigmas[k]):.3f}）")

    low_positive = builder.rescale_keyframes(positive, low_w, low_h)
    low_latent = empty_av_latent(low_w, low_h, segment.frames)
    x0_store: dict = {}
    low_out = _sample(model, low_positive, low_latent, sigmas[:k + 1], sampler, settings.seed, x0_store=x0_store)
    x0 = x0_store.get("x0")
    if x0 is None or not getattr(x0, "is_nested", False):
        raise RuntimeError("progressive sampling did not report a clean estimate")
    x0_video = x0.unbind()[0].to("cpu", torch.float32)
    _, low_audio = continuation.split_av(low_out)
    del low_out, x0, x0_store
    if settings.low_vram:
        mm.soft_empty_cache()

    up = _upscale_video(x0_video, settings.upscale_method, builder.video_vae, settings.width, settings.height,
                        learned_upscaler, report)
    del x0_video
    generator = torch.Generator().manual_seed((settings.seed + 0x5EED) & 0xFFFFFFFFFFFFFFFF)
    noise = torch.randn(up.shape, generator=generator, dtype=torch.float32)
    sigma = sigmas[k:k + 1].float()
    restarted = model_sampling.noise_scaling(sigma, noise, up)
    start_video = model_sampling.inverse_noise_scaling(sigma, restarted)
    start = continuation.join_av(start_video, low_audio.to(torch.float32))
    zeros = continuation.join_av(torch.zeros_like(start_video), torch.zeros_like(low_audio, dtype=torch.float32))
    return _sample(model, positive, start, sigmas[k:], sampler, settings.seed, noise=zeros)


def run(settings: Settings, model, clip, video_vae, audio_vae, media: Media | None,
        learned_upscaler=None) -> Result:
    report = Reporter()
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

    # 1. conditioning for every segment (text encoder runs here, then can be unloaded)
    builder = ConditioningBuilder(clip, video_vae, audio_vae, settings.width, settings.height, media,
                                  settings.ref_image_size)
    conds = []
    for seg, prompt in zip(segments, prompts):
        mm.throw_exception_if_processing_interrupted()
        if image_mode:
            guide = None
            if lock_source is not None:
                guide = assemble.slice_audio(lock_source, *seg.window_seconds)
            positive, latent = builder.image_mode(prompt, seg, seg.index == len(segments) - 1, guide)
        else:
            positive, latent = builder.reference_mode(prompt, seg)
        conds.append((positive, latent["samples"]))
    report.add("条件编码完成")
    if settings.low_vram:
        mm.unload_all_models()
        mm.soft_empty_cache()

    # 2. sampling
    sigmas = _sigmas(model, settings.scheduler, settings.steps)
    sampler = comfy.samplers.sampler_object(settings.sampler_name)
    tst_state = None
    if settings.tst and settings.tst_strength > 0:
        model, tst_state = apply_tst(model, settings.tst_strength, sigmas.tolist())
        report.add(f"TST 防闪烁：强度 {settings.tst_strength:.2f}")

    carry_audio = lock_source is None
    video_latents, audio_latents = [], []
    previous = None
    for seg, (positive, target) in zip(segments, conds):
        mm.throw_exception_if_processing_interrupted()
        seed = (settings.seed + seg.index) & 0xFFFFFFFFFFFFFFFF
        started = time.perf_counter()
        if seg.index == 0:
            out = None
            if settings.progressive:
                out = _progressive_first_segment(model, builder, positive, seg, settings, sampler, sigmas,
                                                 learned_upscaler, report)
            if out is None:
                out = _sample(model, positive, target, sigmas, sampler, seed)
        else:
            video_ctx, audio_ctx = continuation.tail_context(previous)
            audio_ctx = audio_ctx if carry_audio else None
            latent, mask = continuation.apply_prefix(target, video_ctx, audio_ctx)
            out = _sample(model, positive, latent, sigmas, sampler, seed, mask=mask)
            out = continuation.restore_prefix(out, video_ctx, audio_ctx)
        video, audio = continuation.split_av(out)
        video_latents.append(video.to("cpu", torch.float32))
        audio_latents.append(audio.to("cpu", torch.float32))
        previous = continuation.join_av(video_latents[-1], audio_latents[-1])
        report.add(f"第 {seg.index + 1} 段采样完成，用时 {time.perf_counter() - started:.1f}s")
        if settings.low_vram:
            mm.soft_empty_cache()
    if tst_state is not None and tst_state.scales:
        report.add(f"TST 平均放大系数 {sum(tst_state.scales) / len(tst_state.scales):.4f}，"
                   f"最大 {max(tst_state.scales):.4f}")

    # 3. decode and join
    if settings.low_vram:
        mm.unload_all_models()
        mm.soft_empty_cache()
    images = assemble.decode_video(
        video_vae, video_latents, segments,
        on_segment=lambda i: (report.add(f"第 {i + 1} 段解码完成"), settings.low_vram and mm.soft_empty_cache()))
    if lock_source is not None:
        audio_out = assemble.fit_audio(lock_source, total_seconds)
        report.add("输出音频：原音频（已对齐到视频时长）")
    else:
        from comfy_extras.nodes_audio import vae_decode_audio
        joined = assemble.join_audio_latents(audio_latents)
        audio_out = assemble.fit_audio(vae_decode_audio(audio_vae, {"samples": joined}), total_seconds)
        report.add("输出音频：H3 生成")
    report.add(f"完成：{images.shape[0]} 帧（{images.shape[0] / timing.FPS:.2f}s）")
    return Result(images=images, audio=audio_out, report=report.text())
