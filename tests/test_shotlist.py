import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from h3easy import shotlist, timing  # noqa: E402

SHEET = """# EP01《断月》出片清单

**一共：** 3 个镜头，约 23 秒　**画幅：** 9:16

## 第一步　出参考图（这次要出 2 张）

### 图 1　沈烬（角色）

- 存成：`沈烬.png`　比例：3:2

```text
character reference sheet, one swordsman
SHOT 99
```

## 第二步　出视频（3 个镜头）

| 镜头 | 时长 | 按顺序接这些图 | 内容 |
|---|---|---|---|
| 1 | 10 秒 | 沈烬.png、断月台.png | 他登台走近 |

### 镜头 1

SHOT 01

Duration:
10s（length 填 243）

Mode:
Ref2VA（参考模式：接角色图、场景图）

References:
<Picture 1> 沈烬 —— 第 1 张接 `沈烬.png`
<Picture 2> 断月台 —— 第 2 张接 `断月台.png`

导演意图：
他登台走近，Mode 和 Duration 这两个词出现在这里也不算数。

H3 Prompt:
```text
subject_definitions:
<Subject 1> is the swordsman in <Picture 1>.

summary:
[reference generation] He walks onto the terrace in <Picture 2>.
```

注意事项：
没有。

---

### 镜头 2

SHOT 02

Duration: 8s

Mode: Ref2VA（参考模式：接角色图、场景图）

References:
<Picture 1> 沈烬 —— 第 1 张接 `沈烬.png`
<Picture 2> 绯璃（角色参考板）
<Audio 1> 她的声音：`绯璃_音色.wav`

接上一镜：续写

H3 Prompt:
```text
[Shot 1] The shot opens on the same framing. <Subject 2> turns, holding <Picture 3>.
```

### 镜头 3

**SHOT 03**

- **Duration:** 5 秒
- **Mode:** I2VA（首帧模式：从这张图开始）
- **Aspect:** 16:9（宽 1344，高 768）

References:
<Picture 1> 首帧图（窗边的女子）—— `窗边.png`

接上一镜：硬切

H3 Prompt:
```text
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.
```

## 第三步　剪辑

- **顺序：** 镜头 1 → 镜头 2 → 镜头 3
"""


def test_reads_the_cards_of_a_delivery_file():
    shots = shotlist.parse(SHEET)
    assert [s.number for s in shots] == [1, 2, 3]
    assert [s.seconds for s in shots] == [10.0, 8.0, 5.0]
    assert [s.mode for s in shots] == [shotlist.REFERENCE, shotlist.REFERENCE, shotlist.IMAGE]
    assert [s.continues for s in shots] == [False, True, False]
    assert [s.aspect for s in shots] == [(9, 16), (9, 16), (16, 9)]
    assert shotlist.problems(shots) == []

    first, second, third = shots
    assert first.pictures == (shotlist.Ref("<Picture 1>", "沈烬.png"), shotlist.Ref("<Picture 2>", "断月台.png"))
    assert first.prompt.startswith("subject_definitions:") and first.prompt.endswith("in <Picture 2>.")
    # no backticked file name: the words after the tag stand in for it
    assert second.pictures[1] == shotlist.Ref("<Picture 2>", "绯璃")
    assert second.audios == (shotlist.Ref("<Audio 1>", "绯璃_音色.wav"),)
    assert shotlist.unlisted_tags(second) == ["<Picture 3>"]
    assert third.pictures == (shotlist.Ref("<Picture 1>", "窗边.png"),)
    assert shotlist.unlisted_tags(third) == []


def test_ordinary_prompts_are_not_shot_lists():
    assert shotlist.parse("") == []
    plain = "A cat.\n[0-6s]\n[Shot 1] walks.\nShot 2 follows the cat.\n[6-12s]\n[Shot 1] sits."
    assert shotlist.parse(plain) == [] and not shotlist.looks_like_sheet(plain)
    # a card header with no prompt under it is not enough
    assert shotlist.parse("SHOT 01\nDuration: 5s") == []


def test_card_headers_may_be_decorated():
    for header in ("SHOT 01", "### SHOT 01", "**SHOT 01**", "shot 1:", "SHOT 01（镜头 1：登台）", "- SHOT 01 (opening)"):
        shots = shotlist.parse(f"{header}\nDuration: 5s\nMode: Ref2VA\nH3 Prompt:\nhello")
        assert [shot.number for shot in shots] == [1], header
    # the cards were not found, but this is clearly meant to be a shot list
    lost = "镜头一\nDuration: 5s\nMode: Ref2VA\n**H3 Prompt:**\n```text\nhello\n```"
    assert shotlist.parse(lost) == [] and shotlist.looks_like_sheet(lost)


def test_problems_name_the_shot_and_the_field():
    shots = shotlist.parse("SHOT 04\nMode: 自由发挥\nReferences:\n<Picture 2> 沈烬\n<Audio 1>\n"
                           "H3 Prompt:\n```text\nhello\n```")
    found = shotlist.problems(shots)
    assert len(found) == 4
    assert all(line.startswith("镜头 4：") for line in found)
    assert "时长" in found[0] and "模式" in found[1]
    assert "<Picture N> 要从 1 开始连续编号" in found[2]
    assert "<Audio 1> 后面没有写文件名" in found[3]


def test_several_references_on_one_line_and_modes():
    shots = shotlist.parse("SHOT 1\nDuration: 9s\nMode: IA2V（图 + 音频驱动）\n"
                           "References: <Picture 1> 小悠的人像（作首帧）、<Audio 1> 口播录音（8.4 秒）\n"
                           "H3 Prompt:\nno fence here\nsecond line\n注意事项：\n无")
    shot = shots[0]
    assert shot.mode == shotlist.REFERENCE  # IA2V is written in the reference structure
    assert shot.pictures == (shotlist.Ref("<Picture 1>", "小悠的人像"),)
    assert shot.audios == (shotlist.Ref("<Audio 1>", "口播录音"),)
    assert shot.prompt == "no fence here\nsecond line"
    assert shotlist.parse("SHOT 1\nMode: T2VA\nH3 Prompt:\nx")[0].mode == shotlist.IMAGE


def test_shot_lengths_are_never_shorter_than_asked():
    # a shot on its own uses every 17k+5 length, like the native-node table in the director skill
    table = {5: 124, 6: 158, 7: 175, 8: 192, 9: 226, 10: 243, 11: 277, 12: 294, 13: 328, 14: 345, 15: 362}
    for seconds, frames in table.items():
        assert timing.plan_shots([(seconds, False)])[0].frames == frames
    assert timing.plan_shots([(30, False)])[0].frames == 362

    # shots joined by continuation stay on the exact audio/video grid
    segs = timing.plan_shots([(6, False), (8, True), (5, False), (10, False), (4, True)])
    assert [s.frames for s in segs] == [141, 243, 124, 243, 141]
    assert [s.prefix_frames for s in segs] == [0, 39, 0, 0, 39]
    assert [s.new_frames for s in segs] == [141, 204, 124, 243, 102]
    assert [s.start_frame for s in segs] == [0, 102, 345, 469, 673]
    assert timing.total_frames(segs) == 141 + 204 + 124 + 243 + 102
    for seg in segs:
        assert timing.is_valid_frame_count(seg.frames)
        if seg.prefix_frames:
            assert seg.frames % 3 == 0 and segs[seg.index - 1].frames % 3 == 0
    # the longest continuation adds 12.75 s
    assert timing.plan_shots([(8, False), (15, True)])[1].frames == 345


def test_replies_from_a_chat_ai_are_read():
    card = ("SHOT 01\nDuration: 6s\nMode: Ref2VA\nReferences:\n<Picture 1> 沈砚 沈砚.webp\n"
            "<Picture 2> 草屋，文件是 草屋.PNG\n接上一镜: 硬切\nH3 Prompt:\n```text\nhello <Picture 1>\n```\n注意事项：\n无")
    plain = shotlist.parse(card)[0]
    # a file name without backticks still counts
    assert [ref.file for ref in plain.pictures] == ["沈砚.webp", "草屋.PNG"]
    # the whole reply wrapped in one outer fence, the way chat AIs like to answer
    for opener, closer in (("````markdown", "````"), ("```markdown", "```"), ("`````", "`````")):
        wrapped = shotlist.parse(f"好的，清单如下：\n{opener}\n**画幅：** 16:9\n\n{card}\n{closer}\n希望对你有帮助")
        assert len(wrapped) == 1 and wrapped[0].prompt == "hello <Picture 1>", opener
        assert wrapped[0].aspect == (16, 9) and shotlist.problems(wrapped) == []
    # copied without its code fence: the prompt runs up to the next field
    bare = shotlist.parse(card.replace("```text\n", "").replace("```\n", ""))[0]
    assert bare.prompt == "hello <Picture 1>"


def test_the_ai_template_shows_cards_this_parser_reads():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "shot_list_template.md")
    with open(path, encoding="utf-8") as file:
        template = file.read()
    # the single-file director rules, with the section that describes this plugin's cards
    assert "ComfyUI-H3-Easy" in template and "接上一镜" in template
    shots = shotlist.parse(template)
    # the card skeleton and the worked example it shows are cards this parser reads
    assert len(shots) >= 2 and shotlist.problems(shots) == []
    example = max(shots, key=lambda shot: len(shot.prompt))
    assert example.seconds and example.mode == shotlist.REFERENCE and len(example.pictures) == 2
    assert shotlist.unlisted_tags(example) == []
    assert example.prompt.startswith("subject_definitions:") and example.prompt.endswith("N/A")
    assert len(example.prompt) < 7000
