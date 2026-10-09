"""Finished shot latents on disk, so a shot list only samples the shots that changed.

Every shot of a shot list gets a key made from everything its result depends on:
its card, its files, its seed, the sampling settings, what the workflow feeds the
node as models, and the key of the shot it continues. A run looks each key up
first; re-rolling one shot (a new seed for it) therefore leaves the others as they
are, and a run that was stopped half way picks up where it stopped.

The files live in ``<ComfyUI user folder>/h3easy_shots``. The oldest ones are
removed once the folder grows past ``LIMIT_BYTES``.
"""

from __future__ import annotations

import hashlib
import json
import os

import comfy.utils
import folder_paths

LIMIT_BYTES = 4 * 1024 ** 3


def _folder() -> str:
    return os.path.join(folder_paths.get_user_directory(), "h3easy_shots")


def _path(key: str) -> str:
    return os.path.join(_folder(), key + ".safetensors")


def key(*parts) -> str:
    text = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def load(key: str):
    """(video latent, audio latent) stored under ``key``, or None."""
    path = _path(key)
    if not os.path.isfile(path):
        return None
    os.utime(path)  # most recently used: last to be pruned
    stored = comfy.utils.load_torch_file(path, safe_load=True)
    return stored["video"], stored["audio"]


def save(key: str, video, audio):
    os.makedirs(_folder(), exist_ok=True)
    path = _path(key)
    # written under another name first, so a stopped run never leaves half a file under the key
    comfy.utils.save_torch_file({"video": video.contiguous(), "audio": audio.contiguous()}, path + ".part")
    os.replace(path + ".part", path)
    files = sorted((os.path.join(_folder(), name) for name in os.listdir(_folder()) if name.endswith(".safetensors")),
                   key=os.path.getmtime, reverse=True)
    total = 0
    for file in files:
        total += os.path.getsize(file)
        if total > LIMIT_BYTES and file != path:
            os.remove(file)
