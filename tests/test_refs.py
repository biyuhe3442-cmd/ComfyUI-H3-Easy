import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from h3easy import refs  # noqa: E402

# 5 images; video 1 has a soundtrack (<Audio 1>), video 2 has none, video 3 has one (<Audio 2>);
# standalone audio files are <Audio 3> and <Audio 4>
CATALOG = refs.Catalog(pictures=5, video_sound=(True, False, True), audios=2)


def test_segment_gets_only_named_pictures_renumbered():
    active = refs.active_types("<Picture 1> <Picture 5>", CATALOG)
    assert active == {"pictures"}
    sel = refs.select("<Picture 2> hands <Subject 3> to <Picture 5>, then <Picture 2> smiles", CATALOG, active)
    assert sel.pictures == (1, 4)
    assert sel.prompt == "<Picture 1> hands <Subject 3> to <Picture 2>, then <Picture 1> smiles"
    # media types the prompt never names still go to every segment
    assert sel.videos == (0, 1, 2) and sel.audios == (0, 1)


def test_segment_naming_no_picture_gets_none():
    active = refs.active_types("[0-6s] <Picture 1>\n[6-12s] an empty street", CATALOG)
    sel = refs.select("an empty street", CATALOG, active)
    assert sel.pictures == () and sel.prompt == "an empty street"
    assert refs.describe(sel).startswith("视频1")


def test_no_tags_keeps_everything():
    assert refs.active_types("a man walks", CATALOG) == set()
    sel = refs.select("a man walks", CATALOG, set())
    assert sel.pictures == (0, 1, 2, 3, 4) and sel.videos == (0, 1, 2) and sel.audios == (0, 1)


def test_video_and_soundtrack_travel_together_and_audio_is_renumbered():
    full = "<Video 3> <Audio 2> <Audio 4>"
    active = refs.active_types(full, CATALOG)
    assert active == {"videos", "audios"}
    # <Audio 2> is video 3's soundtrack: naming it brings video 3 along
    sel = refs.select("voice like <Audio 2>, music like <Audio 4>", CATALOG, active)
    assert sel.videos == (2,) and sel.audios == (1,)
    # this segment presents: video 3's soundtrack (<Audio 1>), then standalone audio 2 (<Audio 2>)
    assert sel.prompt == "voice like <Audio 1>, music like <Audio 2>"
    sel = refs.select("<Video 3> moves like this", CATALOG, active)
    assert sel.videos == (2,) and sel.audios == () and sel.prompt == "<Video 1> moves like this"


def test_soundtrack_numbers_follow_the_selected_videos():
    active = {"videos", "audios"}
    # videos 1 and 3 both selected: soundtracks keep <Audio 1>, <Audio 2>; standalone 1 -> <Audio 3>
    sel = refs.select("<Video 1> <Video 3> <Audio 2> <Audio 3>", CATALOG, active)
    assert sel.videos == (0, 2) and sel.audios == (0,)
    assert sel.prompt == "<Video 1> <Video 2> <Audio 2> <Audio 3>"
    # only video 2 (silent) selected: standalone audio 2 becomes <Audio 1>
    sel = refs.select("<Video 2> <Audio 4>", CATALOG, active)
    assert sel.prompt == "<Video 1> <Audio 1>"


def test_unknown_tags_are_reported_and_left_alone():
    sel = refs.select("<Picture 9> and <Video 4> and <Audio 7> and <Picture 2>", CATALOG, {"pictures"})
    assert sel.missing == ("<Picture 9>", "<Video 4>", "<Audio 7>")
    assert sel.prompt == "<Picture 9> and <Video 4> and <Audio 7> and <Picture 1>"


def test_tag_spelling_is_forgiving():
    sel = refs.select("<picture 3> and < Picture4 >", CATALOG, {"pictures"})
    assert sel.pictures == (2, 3) and sel.prompt == "<Picture 1> and <Picture 2>"
