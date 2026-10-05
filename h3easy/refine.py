"""Small-face refine: redraw each small face at a higher resolution and paste it back.

For every face track the video is cropped to a square around the face, the crop is
upscaled to ``refine_size`` and only the last steps of the schedule are redrawn
(partial denoise from ``strength``), so motion, expression and mouth shapes stay
while detail is added. The real soundtrack rides along as kept context (mask 0),
which keeps the redraw in step with the speech. Runs longer than one H3 window are
split with the same exact 39-frame continuation as generation. The refined crop is
scaled back, colour-matched to the original and blended in with feathered edges.

Cost: the crop is a 384-512 px square video and only a few steps run; a face that is
on screen the whole time costs roughly 15% (384) to 30% (512) of the original generation.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import torch

import comfy.model_management as mm
import comfy.samplers
import comfy.utils

from . import assemble, continuation, faces, timing
from .conditioning import ConditioningBuilder
from .media import Media
from .pipeline import MODE_REFERENCE, Reporter, _sample

DEFAULT_PROMPT = (
    "integrated_multimodal_description: [Shot 1] Live-action, cinematic, a close-up of a person's face that "
    "continues the same scene, lighting, colors and framing as the source footage. The face is sharp and finely "
    "detailed, with clear natural eyes, eyelashes, nose, lips and skin texture. The head position, gaze, expression "
    "and mouth movements stay exactly as they are throughout, and the framing holds steady.\n\n"
    "overall_soundscape: The original soundtrack continues unchanged.\n\n"
    "non_diegetic_music: N/A"
)


def default_reference_prompt(ref_count: int) -> str:
    subjects = "\n".join(f"<Subject {i + 1}> is the person whose facial identity comes from the close-up portrait "
                         f"in <Picture {i + 1}>." for i in range(ref_count))
    who = "<Subject 1>" if ref_count == 1 else "the defined subject it already resembles"
    retention = "\n".join(f"<Subject {i + 1}> (appears in [Shot 1]): partially_preserved - the facial identity is "
                          f"followed while the pose, expression and mouth movements of the source stay unchanged."
                          for i in range(ref_count))
    return (
        f"subject_definitions:\n{subjects}\n\n"
        f"summary:\n[reference generation] The target video is a close-up of the face of {who}, refining its "
        f"detail without changing the motion of the source footage.\n\n"
        f"retention_analysis:\n{retention}\n\n"
        "detailed_description:\nThe target video is in a live-action, cinematic style that matches the source footage.\n"
        "[Shot 1] A close-up of the face, continuing the same scene, lighting, colors and framing as the source. "
        "The face is sharp and finely detailed, with clear natural eyes, eyelashes, nose, lips and skin texture. "
        "The head position, gaze, expression and mouth movements stay exactly as they are throughout, and the "
        "framing holds steady.\n\n"
        "overall_soundscape:\nThe original soundtrack continues unchanged.\n\n"
        "non_diegetic_music:\nN/A"
    )


@dataclass
class RefineSettings:
    mode: str
    prompt: str = ""
    faces: str = ""               # "1,3" -> only these track ids; empty -> all
    max_face: int = 128           # faces whose typical height is above this are left alone
    refine_size: int = 384
    steps: int = 6                # sampling steps actually run
    strength: float = 0.4         # share of noise in the crop where the redraw starts (0.4 keeps 60% of it)
    seed: int = 0
    sampler_name: str = "res_multistep"
    scheduler: str = "simple"
    context: float = 2.2          # crop side = face size x context
    feather: float = 0.15
    detect_score: float = 0.7
    ref_image_size: str = "max"   # the refine canvas is small: "match" would shrink references to it
    low_vram: bool = True


def _grid_at_least(frames: int) -> int:
    """Smallest exact audio/video length (39 + 51k) that holds ``frames``, within H3's range."""
    k = max(0, math.ceil((max(frames, timing.MIN_SEGMENT_FRAMES) - timing.EXACT_AV_BASE) / timing.EXACT_AV_STEP))
    return min(timing.EXACT_AV_BASE + timing.EXACT_AV_STEP * k, timing.MAX_SEGMENT_FRAMES)


def plan_chunks(start: int, end: int) -> list[timing.Segment]:
    """H3 windows covering frames [start, end]; later windows start with the 39 frames
    the previous one ended on, exactly like continuation segments."""
    chunks = [timing.Segment(0, start, _grid_at_least(end - start + 1), 0)]
    while chunks[-1].end_frame <= end:
        prev = chunks[-1]
        begin = prev.end_frame - timing.CONTEXT_FRAMES
        chunks.append(timing.Segment(len(chunks), begin, _grid_at_least(end + 1 - begin), timing.CONTEXT_FRAMES))
    return chunks


def refine_sigmas(shift: float, start: float, steps: int) -> torch.Tensor:
    """Noise levels from ``start`` (share of noise mixed into the crop) down to 0, spaced
    evenly in the model's unshifted time so most steps land on fine detail.

    ``start`` is the real mix: at 0.4 the sampler begins from 40% noise + 60% of the
    crop. (H3's schedule is shifted by 12, so "0.35 of the way" through a normal
    schedule would already be 86% noise, which redraws the crop from scratch.)"""
    start = min(max(float(start), 0.01), 0.99)
    t0 = timing.unshift_sigma(start, shift)
    ts = torch.linspace(t0, 0.0, max(1, int(steps)) + 1, dtype=torch.float64)
    return (shift * ts / (1 + (shift - 1) * ts)).float()


def face_mask(size: int, cx: float, cy: float, face: float, feather: float) -> torch.Tensor:
    """[S, S, 1] blend weight: an ellipse over the face, hair and chin (centre nudged up),
    fading out over ``feather * 2.5`` face sizes and always zero at the crop border, so
    the background around the head keeps the original pixels."""
    coords = torch.arange(size, dtype=torch.float32) + 0.5
    yy, xx = torch.meshgrid(coords, coords, indexing="ij")
    face = max(face, 1.0)
    d = torch.sqrt(((xx - cx) / (0.75 * face)) ** 2 + ((yy - (cy - 0.1 * face)) / (0.95 * face)) ** 2)
    width = max(feather * 2.5, 0.1)
    w = ((1.0 + width - d) / width).clamp(0.0, 1.0)
    w = w * w * (3 - 2 * w)
    return (w.unsqueeze(-1) * feather_mask(size, 0.06))


def feather_mask(size: int, feather: float) -> torch.Tensor:
    ramp_len = max(1.0, size * feather)
    ramp = torch.clamp((torch.arange(size, dtype=torch.float32) + 0.5) / ramp_len, max=1.0)
    edge = torch.minimum(ramp, ramp.flip(0))
    edge = edge * edge * (3 - 2 * edge)
    return (edge[:, None] * edge[None, :]).unsqueeze(-1)  # [S, S, 1]


def match_color(refined: torch.Tensor, original: torch.Tensor) -> torch.Tensor:
    """Per-channel mean/std of ``refined`` moved onto ``original`` (both [N, S, S, 3])."""
    dims = (0, 1, 2)
    m_r, m_o = refined.mean(dims), original.mean(dims)
    s_r, s_o = refined.std(dims).clamp_min(1e-4), original.std(dims).clamp_min(1e-4)
    gain = (s_o / s_r).clamp(0.5, 2.0)
    return ((refined - m_r) * gain + m_o).clamp(0.0, 1.0)


def _resize(frames: torch.Tensor, size: int, method: str) -> torch.Tensor:
    return comfy.utils.common_upscale(frames.movedim(-1, 1), size, size, method, "disabled").movedim(1, -1)


def _crops(frames: torch.Tensor, plan: faces.CropPlan, indices: list[int], size_r: int) -> torch.Tensor:
    """Each frame's crop (its own size) resized to ``size_r`` x ``size_r``."""
    last = frames.shape[0] - 1
    out = []
    for f in indices:
        g = min(f, last)
        size = plan.sizes[g]
        x0, y0 = plan.corners[g]
        crop = frames[g:g + 1, y0:y0 + size, x0:x0 + size, :3]
        out.append(_resize(crop, size_r, "bicubic" if size < size_r else "area"))
    return torch.cat(out).clamp(0.0, 1.0)


def _audio_latent(audio_vae, audio: dict | None, start_frame: int, frames: int) -> torch.Tensor | None:
    ticks = timing.audio_ticks(frames)
    if audio is None:
        return None
    piece = assemble.slice_audio(audio, start_frame / timing.FPS, (start_frame + frames) / timing.FPS)
    if piece is None:
        return None
    piece = assemble.fit_audio(piece, frames / timing.FPS)
    waveform, rate = piece["waveform"], piece["sample_rate"]
    vae_rate = getattr(audio_vae, "audio_sample_rate", 32000)
    if rate != vae_rate:
        import comfy.audio
        waveform = comfy.audio.resample(waveform, rate, vae_rate)
    z = audio_vae.encode(waveform[:1].movedim(1, -1)).to("cpu", torch.float32)
    if z.shape[-1] > ticks:
        z = z[..., :ticks]
    elif z.shape[-1] < ticks:
        z = torch.cat([z, z[..., -1:].expand(*z.shape[:-1], ticks - z.shape[-1])], dim=-1)
    return z


def refine_video(settings: RefineSettings, model, clip, video_vae, audio_vae, images: torch.Tensor,
                 audio: dict | None = None, media: Media | None = None, mask: torch.Tensor | None = None):
    report = Reporter()
    count, height, width = images.shape[0], images.shape[1], images.shape[2]
    size_r = settings.refine_size
    wanted = faces.parse_face_ids(settings.faces)

    started = time.perf_counter()
    if mask is not None:
        detections = faces.boxes_from_mask(mask, count)
        mask_h, mask_w = mask.shape[-2], mask.shape[-1]
        if (mask_h, mask_w) != (height, width):  # a mask made at another size: map boxes onto the video
            sx, sy = width / mask_w, height / mask_h
            detections = [[faces.Box(b.x * sx, b.y * sy, b.w * sx, b.h * sy, b.score) for b in boxes]
                          for boxes in detections]
    else:
        detections = faces.detect_yunet(images, settings.detect_score)
    tracks = faces.build_tracks(detections)
    source = "遮罩输入" if mask is not None else "YuNet"
    report.add(f"人脸检测（{source}）：{count} 帧，找到 {len(tracks)} 张脸，用时 {time.perf_counter() - started:.1f}s")
    for track in tracks:
        report.add("  " + faces.describe_track(track, width))

    jobs = []
    for track in tracks:
        if wanted is not None and track.id not in wanted:
            report.add(f"脸 {track.id}：不在「只修这些脸」里，跳过")
        elif track.median_size() > settings.max_face:
            report.add(f"脸 {track.id}：约 {track.median_size():.0f}px，已经够大（>{settings.max_face}px），跳过")
        else:
            jobs.append(track)
    if not jobs:
        report.add("没有需要精修的脸，原样输出")
        return images, report.text()

    reference = settings.mode == MODE_REFERENCE
    refs = list(media.ref_images) if (reference and media is not None) else []
    prompt = settings.prompt.strip() or (default_reference_prompt(len(refs)) if refs else DEFAULT_PROMPT)
    builder = ConditioningBuilder(clip, video_vae, audio_vae, size_r, size_r, Media(ref_images=refs),
                                  settings.ref_image_size)
    model_sampling = model.get_model_object("model_sampling")
    sigmas = refine_sigmas(float(getattr(model_sampling, "shift", 12.0)), settings.strength, settings.steps)
    sampler = comfy.samplers.sampler_object(settings.sampler_name)
    report.add(f"精修：{size_r}×{size_r}，从 {settings.strength:.0%} 噪声开始（保留 {1 - settings.strength:.0%} 原画面），"
               f"跑 {settings.steps} 步；{'参考模式' if reference else '图文模式'}"
               + (f"，参考图×{len(refs)}" if refs else ""))

    out = images.clone()
    for track in jobs:
        mm.throw_exception_if_processing_interrupted()
        t0 = time.perf_counter()
        plan = faces.plan_crop(track, width, height, count, size_r, settings.context)
        chunks = plan_chunks(track.start, track.end)
        latents, tail = [], None
        for chunk in chunks:
            mm.throw_exception_if_processing_interrupted()
            indices = list(range(chunk.start_frame, chunk.end_frame))
            crops = _crops(out, plan, indices, size_r)
            video_z = video_vae.encode(crops).to("cpu", torch.float32)
            if video_z.shape[2] != timing.video_latent_t(chunk.frames):
                raise RuntimeError(f"crop encoded to {video_z.shape[2]} latent slots, expected "
                                   f"{timing.video_latent_t(chunk.frames)}")
            audio_z = _audio_latent(audio_vae, audio, chunk.start_frame, chunk.frames)
            keep_audio = audio_z is not None
            if audio_z is None:
                audio_z = torch.zeros(1, 32, 2, timing.audio_ticks(chunk.frames))
            video_mask = torch.ones((1, 1) + tuple(video_z.shape[2:]))
            audio_mask = torch.zeros((1, 1) + tuple(audio_z.shape[2:])) if keep_audio \
                else torch.ones((1, 1) + tuple(audio_z.shape[2:]))
            if tail is not None:  # continue exactly from the previous refined window
                video_z[:, :, :timing.CONTEXT_SLOTS] = tail
                video_mask[:, :, :timing.CONTEXT_SLOTS] = 0
            clean = continuation.join_av(video_z, audio_z)
            seed = (settings.seed + 1000 * track.id + chunk.index) & 0xFFFFFFFFFFFFFFFF
            generator = torch.Generator().manual_seed(seed)
            noise = continuation.join_av(torch.randn(video_z.shape, generator=generator),
                                         torch.randn(audio_z.shape, generator=generator))
            positive = (builder.reference_mode(prompt, chunk) if reference
                        else builder.image_mode(prompt, chunk, False, None))[0]
            result = _sample(model, positive, clean, sigmas, sampler, seed, noise=noise,
                             mask=continuation.join_av(video_mask, audio_mask))
            video_out = continuation.split_av(result)[0].to("cpu", torch.float32)
            if tail is not None:
                video_out[:, :, :timing.CONTEXT_SLOTS] = tail
            tail = video_out[:, :, -timing.CONTEXT_SLOTS:].clone()
            latents.append(video_out)
            del result, clean, noise
            if settings.low_vram:
                mm.soft_empty_cache()

        refined = assemble.decode_video(video_vae, latents, chunks)  # [frames, R, R, 3], from track.start
        frames = list(range(track.start, track.end + 1))
        refined = match_color(refined[:len(frames)].clamp(0.0, 1.0), _crops(out, plan, frames, size_r))
        weights = faces.paste_weights(track)
        pasted = 0
        for i, f in enumerate(frames):
            w = weights.get(f, 0.0)
            if w <= 0:
                continue  # face lost or moving fast: keep the original frame
            size = plan.sizes[f]
            x0, y0 = plan.corners[f]
            cx, cy, face = plan.centers[f]
            patch = _resize(refined[i:i + 1], size, "area" if size < size_r else "bicubic")[0].clamp(0.0, 1.0)
            m = face_mask(size, cx, cy, face, settings.feather) * w
            region = out[f, y0:y0 + size, x0:x0 + size, :3]
            out[f, y0:y0 + size, x0:x0 + size, :3] = patch * m + region * (1 - m)
            pasted += 1
        sizes = [plan.sizes[f] for f in frames]
        del refined, latents
        report.add(f"脸 {track.id}：精修完成，第 {track.start}–{track.end} 帧，贴回 {pasted} 帧"
                   f"（其余帧没检测到脸或动得太快，保留原画面），裁剪 {min(sizes)}–{max(sizes)}px → {size_r}px，"
                   f"{len(chunks)} 个窗口，用时 {time.perf_counter() - t0:.1f}s")
    if settings.low_vram:
        mm.soft_empty_cache()
    return out, report.text()
