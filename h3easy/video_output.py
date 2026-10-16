"""File-backed shot videos; concatenation uses ComfyUI's streaming video implementation."""

from __future__ import annotations

import os
from fractions import Fraction

import av
import torch

import comfy.model_management as mm
import comfy.utils
import folder_paths
from comfy_api.latest import InputImpl, Types

from . import shotcache, timing


def last_frame(path):
    """Seek to the tail and retain only the final decoded frame of our MP4."""
    with av.open(path) as container:
        stream = container.streams.video[0]
        container.seek(max(0, stream.duration - int(1 / stream.time_base)), stream=stream, backward=True)
        frame = None
        for frame in container.decode(stream):
            pass
        if frame is None:
            raise ValueError(f"上一镜视频没有可读取的画面：{path}")
        return torch.from_numpy(frame.to_ndarray(format="rgb24")).unsqueeze(0).float().div_(255)


def _save(video, path):
    video.save_to(path + ".part", format=Types.VideoContainer.MP4, codec=Types.VideoCodec.H264)
    os.replace(path + ".part", path)


class ShotRun:
    """One uninterrupted soundtrack, with each shot's pictures stored separately."""

    def __init__(self, keys, segments):
        render_key = shotcache.key("video-v1", [(key, seg.prefix_frames) for key, seg in zip(keys, segments)])
        self.folder = os.path.join(folder_paths.get_output_directory(), "H3Easy", "shots", render_key)
        self.files = [os.path.join(self.folder, f"shot_{index + 1:04}.mp4") for index in range(len(segments))]
        self.lengths = [seg.new_frames for seg in segments]
        self.metadata = os.path.join(self.folder, "audio.safetensors")
        self.preview = None

    def load(self):
        if not os.path.isfile(self.metadata) or not all(os.path.isfile(path) for path in self.files):
            return None
        stored = comfy.utils.load_torch_file(self.metadata, safe_load=True)
        self.preview = stored["preview"].float().div_(255)
        return {"waveform": stored["waveform"], "sample_rate": int(stored["sample_rate"].item())}

    def write(self, index, images):
        if index == 0:
            self.preview = images[:1].mul(255).clamp_(0, 255).to(device="cpu", dtype=torch.uint8).contiguous()
        path = self.files[index]
        if os.path.isfile(path) or os.path.isfile(path + ".silent.mp4"):
            return
        os.makedirs(self.folder, exist_ok=True)
        video = InputImpl.VideoFromComponents(Types.VideoComponents(images=images, frame_rate=Fraction(timing.FPS)))
        _save(video, path + ".silent.mp4")

    def finish(self, audio):
        cursor, rate = 0, audio["sample_rate"]
        for path, frames in zip(self.files, self.lengths):
            mm.throw_exception_if_processing_interrupted()
            if not os.path.isfile(path):
                soundtrack = {"waveform": audio["waveform"][..., round(cursor * rate / timing.FPS):
                                                           round((cursor + frames) * rate / timing.FPS)],
                              "sample_rate": rate}
                video = InputImpl.VideoFromList([InputImpl.VideoFromFile(path + ".silent.mp4")],
                                                complete_audio=soundtrack)
                _save(video, path)
            cursor += frames
        # A completed marker is written last: interrupted exports are never reused as complete runs.
        comfy.utils.save_torch_file({"waveform": audio["waveform"].contiguous(),
                                     "sample_rate": torch.tensor(rate), "preview": self.preview},
                                    self.metadata + ".part")
        os.replace(self.metadata + ".part", self.metadata)
        self.preview = self.preview.float().div_(255)
        for path in self.files:
            if os.path.isfile(path + ".silent.mp4"):
                os.remove(path + ".silent.mp4")


def join(files, audio):
    """Return a complete on-disk video without expanding its frames into a tensor."""
    path = os.path.join(folder_paths.get_output_directory(), "H3Easy", shotcache.key("joined-v1", files) + ".mp4")
    if not os.path.isfile(path):
        mm.throw_exception_if_processing_interrupted()
        _save(InputImpl.VideoFromList([InputImpl.VideoFromFile(file) for file in files], complete_audio=audio), path)
    return path
