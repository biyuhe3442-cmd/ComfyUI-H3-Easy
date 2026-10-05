"""Split one prompt box into per-segment prompts.

Supported layouts (checked in this order):

* Timeline: header lines like ``[0-6s]`` / ``[6-10]`` / ``[6~10秒]``. Text above the
  first header is shared by every segment. With one section per segment the
  sections are used in order; otherwise each segment takes the section that
  overlaps the new content it adds the most.
* List: sections separated by a line of three or more dashes (``---``). Segment N
  takes section N; extra segments reuse the last section.
* Anything else: the same prompt for every segment.
"""

from __future__ import annotations

import re

_TIMELINE = re.compile(
    r"^\s*\[\s*(\d+(?:\.\d+)?)\s*(?:s|秒)?\s*[-~～–—到至]\s*(\d+(?:\.\d+)?)\s*(?:s|秒)?\s*\]\s*$",
    re.IGNORECASE,
)
_LIST_SEPARATOR = re.compile(r"^\s*-{3,}\s*$")


def _join(lines: list[str]) -> str:
    return "\n".join(lines).strip()


def _timeline_sections(lines: list[str]):
    shared: list[str] = []
    sections: list[tuple[float, float, list[str]]] = []
    for line in lines:
        match = _TIMELINE.match(line)
        if match:
            start, end = float(match.group(1)), float(match.group(2))
            sections.append((min(start, end), max(start, end), []))
        elif sections:
            sections[-1][2].append(line)
        else:
            shared.append(line)
    return _join(shared), [(a, b, _join(body)) for a, b, body in sections]


def _pick_section(sections, window):
    lo, hi = window

    def score(section):
        a, b, _ = section
        overlap = max(0.0, min(hi, b) - max(lo, a))
        # no overlap anywhere: fall back to the section starting closest to the window
        return (overlap, -abs(a - lo))

    return max(sections, key=score)[2]


def split_prompts(text: str, windows: list[tuple[float, float]]) -> tuple[list[str], str]:
    """Return one prompt per window and the detected layout name."""
    text = (text or "").strip()
    count = len(windows)
    lines = text.splitlines()

    if any(_TIMELINE.match(line) for line in lines):
        shared, sections = _timeline_sections(lines)
        if len(sections) == count:
            # one section per segment: keep the written order even when the snapped
            # segment lengths do not match the times in the headers
            bodies = [body for _, _, body in sections]
        else:
            bodies = [_pick_section(sections, window) for window in windows]
        prompts = [_join([shared, body]) if shared else body for body in bodies]
        return prompts, "timeline"

    if any(_LIST_SEPARATOR.match(line) for line in lines):
        items, current = [], []
        for line in lines:
            if _LIST_SEPARATOR.match(line):
                items.append(_join(current))
                current = []
            else:
                current.append(line)
        items.append(_join(current))
        items = [item for item in items if item]
        if not items:
            return [""] * count, "list"
        return [items[min(i, len(items) - 1)] for i in range(count)], "list"

    return [text] * count, "fixed"
