"""Loading images, audio and video for the H3 Easy media bundle."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import av
import numpy as np
import torch

import folder_paths

from .timing import FPS

NONE = "无"
REF_SLOTS = 9
VIDEO_MAX_SECONDS = 15.0
VIDEO_MAX_PIXELS = 640 * 640  # reference video tokens ride through every step; keep them light


@dataclass
class Media:
    first_frame: torch.Tensor | None = None
    last_frame: torch.Tensor | None = None
    ref_images: list[torch.Tensor] = field(default_factory=list)
    audio: dict | None = None          # standalone audio file
    video: torch.Tensor | None = None  # 24 fps frames [F, H, W, 3]
    video_audio: dict | None = None    # soundtrack of the video file

    def describe(self) -> str:
        parts = []
        if self.first_frame is not None:
            parts.append("首帧")
        if self.last_frame is not None:
            parts.append("尾帧")
        if self.ref_images:
            parts.append(f"参考图×{len(self.ref_images)}")
        if self.audio is not None:
            parts.append(f"音频 {self.audio['waveform'].shape[-1] / self.audio['sample_rate']:.1f}s")
        if self.video is not None:
            parts.append(f"视频 {self.video.shape[0] / FPS:.1f}s")
        if self.video_audio is not None:
            parts.append("视频音轨")
        return "、".join(parts) or "无素材"


def list_inputs(kinds: list[str]) -> list[str]:
    directory = folder_paths.get_input_directory()
    os.makedirs(directory, exist_ok=True)
    files = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]
    return sorted(folder_paths.filter_files_content_types(files, kinds))


def selected(value) -> bool:
    return bool(value) and value != NONE


def load_image(name: str) -> torch.Tensor:
    import nodes
    image = nodes.LoadImage().load_image(name)[0]
    return image[:1].float().cpu()


def load_audio(name: str) -> dict:
    from comfy_extras.nodes_audio import load
    waveform, rate = load(folder_paths.get_annotated_filepath(name))
    return {"waveform": waveform.unsqueeze(0), "sample_rate": int(rate)}


def _fit_size(width: int, height: int, max_pixels: int) -> tuple[int, int]:
    scale = min(1.0, (max_pixels / float(width * height)) ** 0.5)
    w = max(32, int(round(width * scale / 2)) * 2)
    h = max(32, int(round(height * scale / 2)) * 2)
    return w, h


def load_video_frames(name: str, max_seconds: float = VIDEO_MAX_SECONDS,
                      max_pixels: int = VIDEO_MAX_PIXELS) -> torch.Tensor:
    """Decode up to ``max_seconds`` of a video, resampled to 24 fps and downscaled."""
    path = folder_paths.get_annotated_filepath(name)
    stamps: list[float] = []
    frames: list[np.ndarray] = []
    with av.open(path) as container:
        if not container.streams.video:
            raise ValueError(f"{name} 里没有视频画面")
        stream = container.streams.video[0]
        rate = float(stream.average_rate) if stream.average_rate else float(FPS)
        size = None
        for index, frame in enumerate(container.decode(stream)):
            t = float(frame.time) if frame.time is not None else index / rate
            if t >= max_seconds:
                break
            if size is None:
                size = _fit_size(frame.width, frame.height, max_pixels)
            frames.append(frame.to_ndarray(format="rgb24", width=size[0], height=size[1]))
            stamps.append(t)
    if not frames:
        raise ValueError(f"{name} 解码不出视频帧")
    first = stamps[0]
    duration = min(max_seconds, stamps[-1] - first + 1.0 / rate)
    out = []
    cursor = 0
    for i in range(max(1, int(duration * FPS))):
        t = first + i / FPS
        while cursor + 1 < len(stamps) and stamps[cursor + 1] <= t + 1e-6:
            cursor += 1
        out.append(frames[cursor])
    return torch.from_numpy(np.stack(out)).float() / 255.0


def load_video_audio(name: str) -> dict | None:
    try:
        return load_audio(name)
    except Exception:
        return None


def file_signature(names: list[str]) -> str:
    parts = []
    for name in names:
        if selected(name):
            path = folder_paths.get_annotated_filepath(name)
            parts.append(f"{name}:{os.path.getmtime(path) if os.path.exists(path) else 'missing'}")
        else:
            parts.append(NONE)
    return "|".join(parts)
