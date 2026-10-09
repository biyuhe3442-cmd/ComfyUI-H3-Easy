"""Loading images, audio and video for the H3 Easy media bundle."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import av
import numpy as np
import torch

import folder_paths

from . import shotlist
from .timing import FPS

NONE = "无"
# MiniMax H3 reference limits (ComfyUI Core "MiniMax H3 Reference to Video")
REF_SLOTS = 9
AUDIO_SLOTS = 3
VIDEO_SLOTS = 3
VIDEO_MAX_SECONDS = 15.0
VIDEO_MAX_PIXELS = 640 * 640  # reference video tokens ride through every step; keep them light
# a shot card's reference groups and the kinds of file each one accepts
SHOT_REFS = (("pictures", ["image"]), ("videos", ["video"]), ("audios", ["audio", "video"]))


@dataclass
class Media:
    first_frame: torch.Tensor | None = None
    last_frame: torch.Tensor | None = None
    ref_images: list[torch.Tensor] = field(default_factory=list)
    audios: list[dict] = field(default_factory=list)              # standalone audio files
    videos: list[torch.Tensor] = field(default_factory=list)      # 24 fps frames [F, H, W, 3]
    video_audios: list[dict | None] = field(default_factory=list)  # soundtrack of each video (or None)
    files: list[str] = field(default_factory=list)                # shot cards: input files used, for the report
    stamp: str = ""                                               # shot cards: those files' names and change times

    @property
    def lock_source(self) -> dict | None:
        """Audio that locks the soundtrack in image mode: audio slot 1 (a video file there gives its soundtrack)."""
        return self.audios[0] if self.audios else None

    def describe(self) -> str:
        parts = []
        if self.first_frame is not None:
            parts.append("首帧")
        if self.last_frame is not None:
            parts.append("尾帧")
        if self.ref_images:
            parts.append(f"参考图×{len(self.ref_images)}")
        for i, audio in enumerate(self.audios):
            parts.append(f"音频{i + 1} {audio['waveform'].shape[-1] / audio['sample_rate']:.1f}s")
        for i, video in enumerate(self.videos):
            sound = "，带音轨" if i < len(self.video_audios) and self.video_audios[i] is not None else ""
            parts.append(f"视频{i + 1} {video.shape[0] / FPS:.1f}s{sound}")
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


def input_files() -> list[str]:
    """Every file in the input folder, subfolders included, as names the loaders above accept."""
    root = folder_paths.get_input_directory()
    out = []
    for folder, _, names in os.walk(root):
        inside = os.path.relpath(folder, root).replace(os.sep, "/")
        out += [name if inside == "." else f"{inside}/{name}" for name in names]
    return out


def find_input(wanted: str, kinds: list[str], files: list[str]) -> str | None:
    """The input file a shot card means: the same file name, else the same name without extension.

    Several matches: the one nearest the top of the input folder, then the newest.
    """
    wanted = wanted.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    candidates = folder_paths.filter_files_content_types(files, kinds)
    matches = [name for name in candidates if name.rsplit("/", 1)[-1].casefold() == wanted]
    if not matches:
        stem = os.path.splitext(wanted)[0]
        matches = [name for name in candidates if os.path.splitext(name.rsplit("/", 1)[-1])[0].casefold() == stem]
    if len(matches) > 1:
        root = folder_paths.get_input_directory()
        matches.sort(key=lambda name: (name.count("/"), -os.path.getmtime(os.path.join(root, name))))
    return matches[0] if matches else None


def find_shot_files(shots: list[shotlist.Shot]) -> list[dict[str, list[str | None]]]:
    """For each shot card, the input file behind every reference (None when nothing matches)."""
    files = input_files() if shots else []
    return [{group: [find_input(ref.file, kinds, files) for ref in getattr(shot, group)]
             for group, kinds in SHOT_REFS} for shot in shots]


def load_shot_media(shots: list[shotlist.Shot]) -> list[Media]:
    """What each shot card hands to H3, in the card's own order."""
    found = find_shot_files(shots)
    missing = [f"镜头 {shot.number} 的 {ref.tag}：{ref.file}"
               for shot, names in zip(shots, found) for group, _ in SHOT_REFS
               for ref, name in zip(getattr(shot, group), names[group]) if name is None]
    if missing:
        raise ValueError("出片清单里有素材没找到。请把这些文件放进 ComfyUI 的 input 文件夹（可以带子文件夹），"
                         "或拖进素材面板：\n" + "\n".join(missing))
    loaded: dict = {}

    def load(reader, name):
        if (reader, name) not in loaded:
            loaded[reader, name] = reader(name)
        return loaded[reader, name]

    out = []
    for shot, names in zip(shots, found):
        media = Media(files=names["pictures"] + names["videos"] + names["audios"])
        media.stamp = file_signature(media.files)
        pictures = [load(load_image, name) for name in names["pictures"]]
        if shot.mode == shotlist.IMAGE:  # fl2va: <Picture 1> is the first frame, <Picture 2> the last
            media.first_frame = pictures[0] if pictures else None
            media.last_frame = pictures[1] if len(pictures) > 1 else None
        else:
            media.ref_images = pictures
            media.videos = [load(load_video_frames, name) for name in names["videos"]]
            media.video_audios = [load(load_video_audio, name) for name in names["videos"]]
            media.audios = [load(load_audio, name) for name in names["audios"]]
        out.append(media)
    return out


def probe(path: str) -> dict:
    with av.open(path) as container:
        duration = container.duration / 1_000_000 if container.duration else None
        video = container.streams.video[0] if container.streams.video else None
        info = {
            "duration": duration,
            "has_audio": bool(container.streams.audio),
            "has_video": video is not None,
        }
        if video is not None:
            info["width"] = video.codec_context.width
            info["height"] = video.codec_context.height
            if duration is None and video.duration and video.time_base:
                info["duration"] = float(video.duration * video.time_base)
    return info
