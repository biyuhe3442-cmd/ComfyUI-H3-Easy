"""Per-segment reference selection for reference mode.

Each segment is its own H3 generation, so it only needs the references its own
prompt names. The prompt uses the loader's global numbering (<Picture 3> is the
loader's third image); a segment gets just the media it names, and its tags are
renumbered to the order H3 sees them in that segment.

H3 numbers references per type in presentation order: images, then videos with
each video's soundtrack taking an <Audio j> label, then standalone audio. So
<Audio 1..s> are the soundtracks of the videos that have one, and standalone
audio follows.

A media type the prompt never names keeps the old behavior: every segment gets
all of it. A video and its soundtrack travel together (H3 pairs them).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TAG = re.compile(r"<\s*(Picture|Video|Audio)\s*(\d+)\s*>", re.IGNORECASE)


@dataclass(frozen=True)
class Catalog:
    """What the loader holds, in global numbering."""
    pictures: int
    video_sound: tuple[bool, ...]  # per video: has a soundtrack
    audios: int                    # standalone audio files

    @property
    def soundtracks(self) -> list[int]:
        return [i for i, sound in enumerate(self.video_sound) if sound]

    def audio_source(self, label: int):
        """Global <Audio label> -> ("video", index) or ("audio", index) or None (0-based)."""
        tracks = self.soundtracks
        if 1 <= label <= len(tracks):
            return "video", tracks[label - 1]
        if len(tracks) < label <= len(tracks) + self.audios:
            return "audio", label - len(tracks) - 1
        return None


@dataclass(frozen=True)
class Selection:
    pictures: tuple[int, ...]  # 0-based indices into the loader's lists
    videos: tuple[int, ...]
    audios: tuple[int, ...]
    prompt: str                # tags renumbered for this segment
    missing: tuple[str, ...]   # tags with no matching media, as written


@dataclass(frozen=True)
class _Named:
    pictures: set
    videos: set
    audios: set
    missing: list


def _named(text: str, catalog: Catalog) -> _Named:
    pictures, videos, audios, missing = set(), set(), set(), []
    for match in _TAG.finditer(text or ""):
        kind, n = match.group(1).lower(), int(match.group(2))
        if kind == "picture" and 1 <= n <= catalog.pictures:
            pictures.add(n - 1)
        elif kind == "video" and 1 <= n <= len(catalog.video_sound):
            videos.add(n - 1)
        elif kind == "audio" and catalog.audio_source(n):
            source, index = catalog.audio_source(n)
            (videos if source == "video" else audios).add(index)
        elif match.group(0) not in missing:
            missing.append(match.group(0))
    return _Named(pictures, videos, audios, missing)


def active_types(full_prompt: str, catalog: Catalog) -> set[str]:
    """Media types the prompt names anywhere: only these are filtered per segment."""
    named = _named(full_prompt, catalog)
    return {kind for kind, found in (("pictures", named.pictures), ("videos", named.videos),
                                     ("audios", named.audios)) if found}


def select(prompt: str, catalog: Catalog, active: set[str]) -> Selection:
    named = _named(prompt, catalog)
    pictures = sorted(named.pictures) if "pictures" in active else list(range(catalog.pictures))
    videos = sorted(named.videos) if "videos" in active else list(range(len(catalog.video_sound)))
    audios = sorted(named.audios) if "audios" in active else list(range(catalog.audios))

    picture_map = {old: new + 1 for new, old in enumerate(pictures)}
    video_map = {old: new + 1 for new, old in enumerate(videos)}
    audio_map = {}  # global label -> label in this segment
    label = 0
    for video in videos:
        if catalog.video_sound[video]:
            label += 1
            audio_map[catalog.soundtracks.index(video) + 1] = label
    for audio in audios:
        label += 1
        audio_map[len(catalog.soundtracks) + audio + 1] = label

    def renumber(match):
        kind, n = match.group(1).lower(), int(match.group(2))
        new = {"picture": picture_map.get(n - 1), "video": video_map.get(n - 1),
               "audio": audio_map.get(n)}[kind]
        return f"<{kind.capitalize()} {new}>" if new else match.group(0)

    return Selection(tuple(pictures), tuple(videos), tuple(audios), _TAG.sub(renumber, prompt or ""),
                     tuple(named.missing))


def describe(selection: Selection) -> str:
    parts = [f"图{i + 1}" for i in selection.pictures]
    parts += [f"视频{i + 1}" for i in selection.videos]
    parts += [f"音频{i + 1}" for i in selection.audios]
    return "、".join(parts) or "无（相当于纯文字生成）"
