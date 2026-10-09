"""Read NB-H3-Director shot cards, so a whole 出片清单 can be pasted as the prompt.

One card is one H3 generation::

    SHOT 02

    Duration:
    8s

    Mode:
    Ref2VA（参考模式：接角色图、场景图）

    References:
    <Picture 1> 沈烬 —— 第 1 张接 `沈烬.png`
    <Picture 2> 断月台 —— 第 2 张接 `断月台.png`

    接上一镜：
    续写

    H3 Prompt:
    ```text
    ...
    ```

Tags are numbered inside each card, in the order its files are handed to H3, so
the prompt is used exactly as written. A reference names its file in backticks;
without one, the words after the tag are taken as the file name without its
extension. Everything else in the text (the other steps of the 出片清单, 导演意图,
注意事项) is skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# "SHOT 01" on its own line; markdown decoration and a note after the number are fine
_HEADER = re.compile(r"^[\s#>*_-]*SHOT\s*(\d+)\s*(?:[*_:：（(].*)?$", re.IGNORECASE)
_PROMPT_LABEL = re.compile(r"^[\s#>*_-]*H3\s*Prompt[\s*_]*[:：]", re.IGNORECASE | re.MULTILINE)
_LABEL = re.compile(
    r"^[\s#>*_-]*(Duration|Mode|Aspect|References|H3\s*Prompt|接上一镜|导演意图|注意事项)[\s*_]*[:：][\s*_]*(.*)$",
    re.IGNORECASE)
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
# a chat AI may wrap its whole reply in one outer fence: four or more backticks, or ```markdown
_WRAPPER = re.compile(r"^\s*(`{4,}.*|`{3}\s*(markdown|md)\s*)$", re.IGNORECASE)
_TAG = re.compile(r"<\s*(Picture|Video|Audio)\s*(\d+)\s*>", re.IGNORECASE)
# a file name in backticks, else a bare word that ends like a media file
_FILE = re.compile(r"`([^`]+\.\w{2,5})`|([^\s`，,、（(]+\.(?:png|jpe?g|webp|bmp|gif|wav|mp3|flac|ogg|m4a|aac|mp4|mov|webm|mkv))",
                   re.IGNORECASE)
_SECONDS = re.compile(r"(\d+(?:\.\d+)?)")
_RATIO = re.compile(r"(\d+)\s*[:：]\s*(\d+)")
_SHEET_ASPECT = re.compile(r"画幅[^\d\n]*(\d+)\s*[:：]\s*(\d+)")
_LABEL_END = re.compile(r"——|—|--|（|\(|，|,|：|:")

IMAGE = "image"
REFERENCE = "reference"


@dataclass(frozen=True)
class Ref:
    tag: str   # as numbered in this card, e.g. "<Picture 2>"
    file: str  # file name, or the bare words after the tag when the card gives none


@dataclass(frozen=True)
class Shot:
    number: int
    seconds: float | None
    mode: str | None               # IMAGE (fl2va), REFERENCE (ref2va) or not recognised
    pictures: tuple[Ref, ...]
    videos: tuple[Ref, ...]
    audios: tuple[Ref, ...]
    prompt: str
    continues: bool                # starts on the previous shot's last frames instead of a cut
    aspect: tuple[int, int] | None


def _mode(text: str) -> str | None:
    upper = text.upper()
    if re.search(r"REF2VA|IA2V", upper) or "参考" in text:
        return REFERENCE
    if re.search(r"I2VA|T2VA|FL2VA", upper) or "首帧" in text or "图文" in text:
        return IMAGE
    return None


def _refs(lines: list[str]) -> dict[str, tuple[Ref, ...]]:
    found = {"picture": {}, "video": {}, "audio": {}}
    for line in lines:
        tags = list(_TAG.finditer(line))
        for tag, following in zip(tags, tags[1:] + [None]):
            rest = line[tag.end():following.start() if following else len(line)]
            file = _FILE.search(rest)
            if file:
                name = (file.group(1) or file.group(2)).strip()
            else:
                rest = rest.lstrip(" \t:：-—")
                end = _LABEL_END.search(rest)
                name = (rest[:end.start()] if end else rest).strip()
            kind, n = tag.group(1).lower(), int(tag.group(2))
            found[kind].setdefault(n, Ref(f"<{kind.capitalize()} {n}>", name))
    return {kind: tuple(refs[n] for n in sorted(refs)) for kind, refs in found.items()}


def _card(number: int, lines: list[str], sheet_aspect) -> Shot:
    plain: dict[str, list[str]] = {}
    fenced: dict[str, list[str]] = {}
    field = fence = block = None
    for line in lines:
        mark = _FENCE.match(line)
        if fence:
            if mark and mark.group(1).startswith(fence):
                fence = None
            else:
                block.append(line)
            continue
        if mark:
            fence, block = mark.group(1), []
            if field and field not in fenced:
                fenced[field] = block
            continue
        label = _LABEL.match(line)
        if label:
            field = re.sub(r"\s+", "", label.group(1)).lower()
            plain[field] = [label.group(2)]
        elif field:
            plain[field].append(line)

    def text(name):
        return "\n".join(plain.get(name, [])).strip()

    seconds = _SECONDS.search(text("duration"))
    ratio = _RATIO.search(text("aspect"))
    refs = _refs(plain.get("references", []))
    return Shot(
        number=number,
        seconds=float(seconds.group(1)) if seconds else None,
        mode=_mode(text("mode")),
        pictures=refs["picture"], videos=refs["video"], audios=refs["audio"],
        prompt="\n".join(fenced["h3prompt"]).strip() if "h3prompt" in fenced else text("h3prompt"),
        continues="续" in text("接上一镜"),
        aspect=(int(ratio.group(1)), int(ratio.group(2))) if ratio else sheet_aspect,
    )


def parse(text: str) -> list[Shot]:
    """The shot cards in ``text``; empty when it is an ordinary prompt."""
    lines = [line for line in (text or "").splitlines() if not _WRAPPER.match(line)]
    cards: list[tuple[int, list[str]]] = []
    head: list[str] = []
    fence = None
    for line in lines:
        mark = _FENCE.match(line)
        if fence:
            if mark and mark.group(1).startswith(fence):
                fence = None
        elif mark:
            fence = mark.group(1)
        else:
            header = _HEADER.match(line)
            if header:
                cards.append((int(header.group(1)), []))
                continue
        (cards[-1][1] if cards else head).append(line)
    sheet = _SHEET_ASPECT.search("\n".join(head))
    sheet_aspect = (int(sheet.group(1)), int(sheet.group(2))) if sheet else None
    shots = [_card(number, body, sheet_aspect) for number, body in cards]
    return shots if any(shot.prompt for shot in shots) else []


def looks_like_sheet(text: str) -> bool:
    """True for text that carries the cards' ``H3 Prompt:`` label, whether or not ``parse`` found cards."""
    return bool(_PROMPT_LABEL.search(text or ""))


def problems(shots: list[Shot]) -> list[str]:
    """What stops a shot list from running, one line per finding."""
    out = []
    for shot in shots:
        name = f"镜头 {shot.number}"
        if not shot.seconds:
            out.append(f"{name}：没有读到时长（Duration: 后面写秒数，例如 10s）")
        if shot.mode is None:
            out.append(f"{name}：没有读到模式（Mode: 后面写 Ref2VA、I2VA 或 IA2V）")
        if not shot.prompt:
            out.append(f"{name}：没有读到提示词（H3 Prompt: 下面用 ```text 代码框放整段提示词）")
        for kind, refs in (("Picture", shot.pictures), ("Video", shot.videos), ("Audio", shot.audios)):
            if [ref.tag for ref in refs] != [f"<{kind} {n}>" for n in range(1, len(refs) + 1)]:
                out.append(f"{name}：References 里的 <{kind} N> 要从 1 开始连续编号")
            out += [f"{name}：{ref.tag} 后面没有写文件名" for ref in refs if not ref.file]
    return out


def unlisted_tags(shot: Shot) -> list[str]:
    """Tags the prompt uses that the card's References do not provide."""
    listed = {ref.tag for ref in shot.pictures + shot.videos + shot.audios}
    used = []
    for tag in _TAG.finditer(shot.prompt):
        name = f"<{tag.group(1).capitalize()} {int(tag.group(2))}>"
        if name not in listed and name not in used:
            used.append(name)
    return used
