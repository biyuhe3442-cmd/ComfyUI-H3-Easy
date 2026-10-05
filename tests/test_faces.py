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


def test_plan_crop_size_and_bounds():
    track = faces.build_tracks(_moving(30, 2, 300, 0.0, 24))[0]  # small face at the left edge, low
    plan = faces.plan_crop(track, 960, 544, 50, refine_size=512, context=2.2)
    assert plan.size == 128  # 24 * 2.2 = 53 < 512 / 4
    for f, (x0, y0) in plan.corners.items():
        assert 0 <= x0 <= 960 - 128 and 0 <= y0 <= 544 - 128
    assert plan.corners[49] == plan.corners[29]  # after the track: hold the last position
    big = faces.build_tracks(_moving(30, 100, 50, 0.0, 400))[0]
    assert faces.plan_crop(big, 960, 544, 30, 512).size == 544  # never larger than the frame


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
