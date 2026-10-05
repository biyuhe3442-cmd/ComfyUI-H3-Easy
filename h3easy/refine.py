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
from .pipeline import MODE_REFERENCE, Reporter, _sample, _sigmas

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
    steps: int = 12
    strength: float = 0.35        # unshifted noise level the redraw starts from
    seed: int = 0
    sampler_name: str = "res_multistep"
    scheduler: str = "simple"
    context: float = 2.2          # crop side = face size x context
    feather: float = 0.15
    detect_score: float = 0.6
    ref_image_size: str = "match"
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


def _crops(frames: torch.Tensor, plan: faces.CropPlan, indices: list[int]) -> torch.Tensor:
    last = frames.shape[0] - 1
    out = []
    for f in indices:
        x0, y0 = plan.corners[min(f, last)]
        out.append(frames[min(f, last), y0:y0 + plan.size, x0:x0 + plan.size, :3])
    return torch.stack(out)


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
    sigmas = _sigmas(model, settings.scheduler, settings.steps)
    model_sampling = model.get_model_object("model_sampling")
    k = timing.handoff_index(sigmas.tolist(), float(getattr(model_sampling, "shift", 12.0)), settings.strength)
    sampler = comfy.samplers.sampler_object(settings.sampler_name)
    report.add(f"精修：{size_r}×{size_r}，{settings.steps} 步的日程里从第 {k} 步开始，实际跑 {len(sigmas) - 1 - k} 步"
               f"（起点 sigma={float(sigmas[k]):.3f}）；{'参考模式' if reference else '图文模式'}"
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
            crops = _resize(_crops(out, plan, indices), size_r, "bicubic").clamp(0.0, 1.0)
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
            result = _sample(model, positive, clean, sigmas[k:], sampler, seed, noise=noise,
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
        refined = refined[:len(frames)]
        original = _crops(out, plan, frames)
        refined = match_color(_resize(refined, plan.size, "area").clamp(0.0, 1.0), original)
        weight = feather_mask(plan.size, settings.feather)
        for i, f in enumerate(frames):
            x0, y0 = plan.corners[f]
            region = out[f, y0:y0 + plan.size, x0:x0 + plan.size, :3]
            out[f, y0:y0 + plan.size, x0:x0 + plan.size, :3] = refined[i] * weight + region * (1 - weight)
        del refined, original, latents
        report.add(f"脸 {track.id}：精修完成，第 {track.start}–{track.end} 帧，裁剪 {plan.size}px → {size_r}px，"
                   f"{len(chunks)} 个窗口，用时 {time.perf_counter() - t0:.1f}s")
    if settings.low_vram:
        mm.soft_empty_cache()
    return out, report.text()
