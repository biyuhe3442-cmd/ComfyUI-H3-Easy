import os
import sys

import pytest
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from h3easy import faces  # noqa: E402


def _moving(frames, x0, y0, dx, size, skip=()):
    return [[] if f in skip else [faces.Box(x0 + dx * f, y0, size, size, 0.9)] for f in range(frames)]


def test_tracks_link_fill_gaps_and_order_ids():
    a = _moving(40, 300, 100, 2.0, 30, skip={10, 11, 12})   # right face, short detection gap
    b = _moving(40, 50, 120, 1.0, 28)                         # left face
    detections = [x + y for x, y in zip(a, b)]
    detections[5].append(faces.Box(600, 400, 20, 20, 0.7))    # one-frame false positive
    tracks = faces.build_tracks(detections)
    assert len(tracks) == 2
    left, right = tracks  # same first frame -> ordered left to right
    assert left.boxes[0].cx < right.boxes[0].cx
    assert [t.id for t in tracks] == [1, 2]
    assert right.start == 0 and right.end == 39 and len(right.boxes) == 40  # gap filled
    assert abs(right.boxes[11].cx - (315 + 2.0 * 11)) < 3.0


def test_far_jump_starts_a_new_track():
    det = _moving(20, 100, 100, 0.0, 30) + _moving(20, 700, 100, 0.0, 30)
    tracks = faces.build_tracks(det)
    assert [(t.start, t.end) for t in tracks] == [(0, 19), (20, 39)]


def test_plan_crop_follows_face_size_and_bounds():
    det = [[faces.Box(2, 300, 24 + f, 24 + f, 0.9)] for f in range(30)]  # small face at the left edge, growing
    track = faces.build_tracks(det)[0]
    plan = faces.plan_crop(track, 960, 544, 50, refine_size=384, context=2.2)
    assert plan.sizes[0] == 96  # 24 * 2.2 = 53 < 384 / 4
    assert plan.sizes[29] > plan.sizes[0]  # grows with the face (smoothed)
    for f in range(50):
        x0, y0 = plan.corners[f]
        assert 0 <= x0 <= 960 - plan.sizes[f] and 0 <= y0 <= 544 - plan.sizes[f]
    assert plan.corners[49] == plan.corners[29]  # after the track: hold the last crop
    big = faces.build_tracks([[faces.Box(100, 50, 400, 400, 0.9)] for _ in range(30)])[0]
    assert faces.plan_crop(big, 960, 544, 30, 512).sizes[0] == 544  # never larger than the frame


def test_duplicate_track_from_a_fast_move_is_dropped():
    main = [[faces.Box(300 + 3 * f, 100, 40, 40, 0.9)] for f in range(60)]
    # a second detector hit on the same face for 15 frames that did not link to the main track
    for f in range(20, 35):
        main[f].append(faces.Box(305 + 3 * f, 102, 40, 40, 0.8))
    tracks = faces.build_tracks(main)
    # every frame of the face is covered once: no frame is refined twice
    covered = [f for t in tracks for f in t.boxes]
    assert sorted(covered) == list(range(60))


def test_paste_weights_skip_lost_and_fast_frames():
    det = [[faces.Box(100, 100, 40, 40, 0.9)] for _ in range(30)]
    for f in range(10, 22):
        det[f] = []                                              # face lost for 12 frames
    det += [[faces.Box(100 + 30 * i, 100, 40, 40, 0.9)] for i in range(1, 15)]  # then whipping sideways
    track = faces.build_tracks(det, max_gap=12)[0]
    w = faces.paste_weights(track)
    assert w[0] == 1.0 and w[5] > 0.9
    assert w[16] == 0.0                                          # deep inside the gap: keep the original
    assert w[40] == 0.0                                          # 0.75 face sizes per frame: too fast
def test_parse_face_ids():
    assert faces.parse_face_ids("") is None
    assert faces.parse_face_ids("1, 3，2") == {1, 2, 3}
    with pytest.raises(ValueError):
        faces.parse_face_ids("左边")


def test_boxes_from_mask_two_blobs():
    mask = torch.zeros(3, 64, 96)
    mask[:, 10:20, 10:22] = 1
    mask[:, 30:44, 60:70] = 1
    boxes = faces.boxes_from_mask(mask, 3)
    assert len(boxes) == 3
    sizes = sorted((b.w, b.h) for b in boxes[0])
    if len(boxes[0]) == 2:  # OpenCV available: one box per blob
        assert sizes == [(10.0, 14.0), (12.0, 10.0)]
    else:
        assert len(boxes[0]) == 1
