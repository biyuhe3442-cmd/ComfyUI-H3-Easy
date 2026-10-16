import os
import re
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
    # it shows the reply it asks for twice, each a whole list in one ```markdown box: the
    # skeleton and the worked example. Both are lists this parser reads.
    lists = re.findall(r"^```markdown\n(.*?)\n```$", template, re.S | re.M)
    assert len(lists) == 2
    for text in lists:
        shots = shotlist.parse(text)
        assert len(shots) == 1 and shotlist.problems(shots) == [] and shots[0].aspect == (16, 9)
        # the files a card names are the ones the list's 素材 table tells the user to save
        assert [ref.file for ref in shots[0].pictures] == re.findall(r"^`([^`]+)` ", text, re.M)
    example = shotlist.parse(lists[1])[0]
    assert example.seconds == 14 and example.mode == shotlist.REFERENCE and not example.continues
    assert shotlist.unlisted_tags(example) == []
    # the plan fields before the prompt and the notes after it stay out of the prompt
    assert example.prompt.startswith("subject_definitions:") and example.prompt.endswith("N/A")
    assert len(example.prompt) < 7000 and "已核对" not in example.prompt
    # sent the way the template asks: picture prompts in boxes of their own, the list, one sentence
    reply = ("**沈砚.png**　比例 3:2\n```text\none actor in full costume\n```\n\n```markdown\n" + lists[1]
             + "\n```\n\n复制上面整个清单框。")
    assert shotlist.parse(reply) == [example]


ONE_BOX = """# 《账本》出片清单
**画幅：** 9:16
**我替你定的：** 无

素材：
`沈砚.png` 角色：沈砚
`草屋.png` 场景：漏雨的草屋

SHOT 01
Duration: 6s
Mode: Ref2VA
References:
<Picture 1> 沈砚 `沈砚.png`
<Picture 2> 草屋 `草屋.png`
接上一镜: 硬切
导演意图：他翻开账本。
H3 Prompt:
subject_definitions:
<Subject 1> is the young man in <Picture 1>.

non_diegetic_music:
N/A
注意事项：无

SHOT 02
Duration: 6s
Mode: Ref2VA
References:
<Picture 1> 沈砚 `沈砚.png`
接上一镜: 续写
导演意图：他抬头。
H3 Prompt:
subject_definitions:
<Subject 1> is the young man in <Picture 1>.

detailed_description:
[Shot 1] The shot opens on the same medium shot.
[Shot 2] At 00:03.600, the camera cuts to a close-up.

non_diegetic_music:
N/A
注意事项：无"""


def test_a_list_in_one_code_block_is_read_however_it_was_copied():
    def check(text):
        shots = shotlist.parse(text)
        assert [(s.number, s.seconds, s.mode, s.continues) for s in shots] == [
            (1, 6.0, shotlist.REFERENCE, False), (2, 6.0, shotlist.REFERENCE, True)], text[:40]
        assert shotlist.problems(shots) == [] and shots[0].aspect == (9, 16)
        assert [ref.file for ref in shots[0].pictures] == ["沈砚.png", "草屋.png"]
        assert shots[0].prompt == ("subject_definitions:\n<Subject 1> is the young man in <Picture 1>.\n\n"
                                   "non_diegetic_music:\nN/A")
        # the cut marks of the official prompt format are not card headers
        assert shots[1].prompt.endswith("N/A") and "[Shot 2] At 00:03.600" in shots[1].prompt

    check(ONE_BOX)                                  # the code block's own copy button: no fence at all
    check("```text\n" + ONE_BOX + "\n```")            # the whole reply copied
    check("好的：\n\n```\n" + ONE_BOX + "\n```\n")
    # prompts fenced inside an outer fence of the same length: wrong nesting, still read
    nested = ONE_BOX.replace("H3 Prompt:\n", "H3 Prompt:\n```text\n").replace("\n注意事项：", "\n```\n注意事项：")
    check("```markdown\n" + nested + "\n```")
    check("```text\n" + nested + "\n```")


def test_director_notes_between_fields_stay_out_of_the_card():
    text = ONE_BOX.split("SHOT 02")[0].replace(
        "接上一镜: 硬切\n",
        "接上一镜: 硬切\n分段：\n- 0.0秒起 · 继续翻账本\n已核对：语速：常\n声线绑定：\n- 沈砚 (S1)：`青年男性`\n"
        "开场状态：沈砚坐画左。\n结束状态：账本已翻开。\n人物认知：他看见账目。\n观众信息：账本有异。\n切镜：固定机位。\n")
    shot = shotlist.parse(text)[0]
    assert shot == shotlist.parse(ONE_BOX)[0]  # the prompt is sent as written
    assert not shot.continues  # 「继续」 in the notes is not 接上一镜：续写


def test_previous_frame_reference_is_explicit_and_validated():
    text = ONE_BOX.replace("接上一镜: 续写", "接上一镜: 硬切\n承接画面：上一镜尾帧参考")
    shots = shotlist.parse(text)
    assert not shots[0].frame_reference and shots[1].frame_reference
    assert shotlist.problems(shots) == []
    assert any("第一镜" in issue for issue in shotlist.problems(shots[1:]))
    bad = text.replace("接上一镜: 硬切\n承接画面：上一镜尾帧参考", "接上一镜: 续写\n承接画面：上一镜尾帧参考")
    assert any("续写" in issue for issue in shotlist.problems(shotlist.parse(bad)))
    bad = text.replace("Mode: Ref2VA", "Mode: I2VA")
    assert any("参考模式" in issue for issue in shotlist.problems(shotlist.parse(bad)))


def test_frame_reference_reserves_a_picture_slot_without_renumbering_user_assets():
    text = ONE_BOX.replace("接上一镜: 续写", "接上一镜: 硬切\n承接画面：上一镜尾帧参考")
    text = text.replace("<Picture 1> 沈砚 `沈砚.png`\n接上一镜", "\n".join(
        f"<Picture {n}> 角色{n} `角色{n}.png`" for n in range(1, 10)) + "\n接上一镜")
    assert any("留出" in issue for issue in shotlist.problems(shotlist.parse(text)))


def test_a_list_copied_out_of_a_rich_text_view_is_cleaned():
    """A real copy (2026-10-16): Markdown punctuation escaped, every line break made four."""
    clean = ("**画幅：** 16:9\n\n素材：\n`老子_老年.png` 角色：老子\n\n"
             "SHOT 01\nDuration: 6s\nMode: Ref2VA\nReferences:\n<Picture 1> 老子（老年） `老子_老年.png`\n"
             "<Picture 2> 尹喜 `尹喜.png`\n接上一镜: 硬切\n导演意图：开场。\n分段：\n- 0.0秒起 · 中景\n"
             "H3 Prompt:\nsubject_definitions:\n<Subject 1> is the old man in <Picture 1>.\n\n"
             "summary:\n[reference generation] He stops.\n\n"
             "detailed_description:\n[Shot 1] A medium two-shot.\n[Shot 2] At 00:03.500, the camera cuts to him.\n\n"
             "non_diegetic_music:\nN/A\n注意事项：无\n\n"
             "SHOT 02\nDuration: 5s\nMode: Ref2VA\nReferences:\n<Picture 1> 老子（老年） `老子_老年.png`\n"
             "接上一镜: 硬切\nH3 Prompt:\nsubject_definitions:\n<Subject 1> is the old man in <Picture 1>.\n\n"
             "non_diegetic_music:\nN/A\n注意事项：无")
    copied = clean
    for mark in "\\_[*#-":
        copied = copied.replace(mark, "\\" + mark)
    copied = copied.replace("\n", "\n\n\n\n")
    assert "subject\\_definitions" in copied and "\\[Shot 2]" in copied and "`老子\\_老年.png`" in copied

    expected = shotlist.parse(clean)
    got = shotlist.parse(copied)
    assert len(got) == 2 and got == expected
    assert got[0].prompt.startswith("subject_definitions:\n<Subject 1> is the old man in <Picture 1>.\n\nsummary:\n")
    assert "[Shot 2] At 00:03.500" in got[0].prompt and "\\" not in got[0].prompt
    assert [ref.file for ref in got[0].pictures] == ["老子_老年.png", "尹喜.png"]
    assert got[0].aspect == (16, 9)
    # an ordinary list keeps its blank lines and a literal backslash before a letter
    assert shotlist.parse(clean.replace("尹喜.png`", "尹喜.png` C:\\x"))[0].prompt == expected[0].prompt


def test_reference_pictures_are_kept_out_of_the_video():
    prompt = "detailed_description:\n[Shot 1] A man waits.\n\noverall_soundscape:\nRain."
    added = shotlist.keep_references_out(prompt)
    assert added == ("detailed_description:\n[Shot 1] A man waits. Throughout the video, " + shotlist.NO_SHEET
                     + ".\n\noverall_soundscape:\nRain.")
    assert shotlist.keep_references_out(added) == added
    first_frame = "summary:\n[reference generation + keyframe completion] The shot begins from <Picture 2>."
    assert shotlist.keep_references_out(first_frame) == first_frame
