"""Find faces in a generated video and follow them over time.

Detection uses YuNet (OpenCV's FaceDetectorYN, model bundled in ``models/``, MIT
licence, see THIRD_PARTY_NOTICES.md). Faces can also come from any other detector
as a per-frame MASK. Detections are linked into tracks, small gaps are filled, and
each track gets one square crop size with a smoothed centre per frame, so the crop
the refiner sees moves calmly with the face.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import torch

YUNET_MODEL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models",
                           "face_detection_yunet_2023mar.onnx")


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float
    score: float = 1.0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def size(self) -> float:
        return max(self.w, self.h)


@dataclass
class Track:
    id: int
    boxes: dict[int, Box] = field(default_factory=dict)  # frame -> box, contiguous after build_tracks
    detected: set[int] = field(default_factory=set)      # frames with a real detection (not interpolated)

    @property
    def start(self) -> int:
        return min(self.boxes)

    @property
    def end(self) -> int:  # inclusive
        return max(self.boxes)

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    def median_size(self) -> float:
        sizes = sorted(b.size for b in self.boxes.values())
        return sizes[len(sizes) // 2]


def _cv2():
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("找不到 OpenCV：请安装 opencv-python（pip install opencv-python），"
                           "或者把其他人脸检测节点输出的遮罩接到「人脸遮罩」输入") from exc
    if not hasattr(cv2, "FaceDetectorYN"):
        raise RuntimeError(f"OpenCV {cv2.__version__} 太旧，没有 FaceDetectorYN，请升级到 4.5.4 以上")
    return cv2


def detect_yunet(frames: torch.Tensor, score: float = 0.6, every: int = 1) -> list[list[Box]]:
    """Faces per frame of an IMAGE batch [F, H, W, 3] in 0..1. Frames skipped by
    ``every`` get no detections; the tracker fills them in."""
    cv2 = _cv2()
    count, height, width = frames.shape[0], frames.shape[1], frames.shape[2]
    try:
        detector = cv2.FaceDetectorYN.create(YUNET_MODEL, "", (width, height), float(score), 0.3, 5000)
    except cv2.error as exc:
        raise RuntimeError(f"OpenCV {cv2.__version__} 加载不了内置的人脸检测模型（需要 OpenCV 4.8 以上）。"
                           f"请升级：python -m pip install -U opencv-python；"
                           f"或者把其他人脸检测节点的遮罩接到「人脸遮罩」输入") from exc
    detector.setInputSize((width, height))
    result: list[list[Box]] = []
    for i in range(count):
        if i % every:
            result.append([])
            continue
        rgb = (frames[i, ..., :3].clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()
        _, faces = detector.detect(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        boxes = []
        if faces is not None:
            for f in faces:
                x, y, w, h = (float(v) for v in f[:4])
                if w > 2 and h > 2:
                    boxes.append(Box(x, y, w, h, float(f[14])))
        result.append(boxes)
    return result


def boxes_from_mask(mask: torch.Tensor, frame_count: int) -> list[list[Box]]:
    """Regions of a MASK ([F, H, W] or a single [H, W] for every frame), one box per
    connected blob when OpenCV is available, otherwise one box around all of it."""
    if mask.ndim == 2:
        mask = mask.unsqueeze(0)
    try:
        import cv2
    except ImportError:
        cv2 = None
    result: list[list[Box]] = []
    for i in range(frame_count):
        m = mask[min(i, mask.shape[0] - 1)] > 0.5
        if not bool(m.any()):
            result.append([])
            continue
        if cv2 is None:
            ys, xs = torch.nonzero(m, as_tuple=True)
            x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
            result.append([Box(x0, y0, x1 - x0, y1 - y0)])
            continue
        n, _, stats, _ = cv2.connectedComponentsWithStats(m.to(torch.uint8).cpu().numpy(), connectivity=8)
        result.append([Box(float(s[0]), float(s[1]), float(s[2]), float(s[3])) for s in stats[1:n] if s[4] >= 9])
    return result


def _smooth(values: list[float], radius: int) -> list[float]:
    out = []
    for i in range(len(values)):
        lo, hi = max(0, i - radius), min(len(values), i + radius + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def _iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0.0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    inter = ix * iy
    return inter / max(a.w * a.h + b.w * b.h - inter, 1e-6)


def build_tracks(detections: list[list[Box]], max_gap: int = 12, min_hits: int = 12,
                 smooth_radius: int = 4) -> list[Track]:
    """Link per-frame boxes into face tracks.

    A box joins the open track whose last box is nearest (centre distance under 1.5
    face sizes, which tolerates fast turns, and similar size). Tracks with fewer than
    ``min_hits`` detections (half a second) are dropped as false positives; where two
    tracks sit on the same face (one face split by a fast move), those frames go to the
    longer track. Gaps up to ``max_gap`` frames are interpolated, boxes smoothed.
    IDs follow first appearance, then left to right.
    """
    raw: list[dict[int, Box]] = []
    last_seen: list[int] = []
    for frame, boxes in enumerate(detections):
        open_ids = [i for i in range(len(raw)) if frame - last_seen[i] <= max_gap + 1]
        pairs = []
        for b_idx, box in enumerate(boxes):
            for t in open_ids:
                prev = raw[t][last_seen[t]]
                dist = ((box.cx - prev.cx) ** 2 + (box.cy - prev.cy) ** 2) ** 0.5 / max(prev.size, 1.0)
                ratio = box.size / max(prev.size, 1.0)
                if dist < 1.5 and 0.5 < ratio < 2.0:
                    pairs.append((dist, b_idx, t))
        used_boxes, used_tracks = set(), set()
        for _, b_idx, t in sorted(pairs):
            if b_idx in used_boxes or t in used_tracks:
                continue
            used_boxes.add(b_idx)
            used_tracks.add(t)
            raw[t][frame] = boxes[b_idx]
            last_seen[t] = frame
        for b_idx, box in enumerate(boxes):
            if b_idx not in used_boxes:
                raw.append({frame: box})
                last_seen.append(frame)

    tracks = []
    for hits in raw:
        if len(hits) < min_hits:
            continue
        frames = sorted(hits)
        filled: dict[int, Box] = {}
        for a, b in zip(frames, frames[1:] + [frames[-1]]):
            filled[a] = hits[a]
            for f in range(a + 1, b):  # linear interpolation over a gap
                t = (f - a) / (b - a)
                ba, bb = hits[a], hits[b]
                filled[f] = Box(ba.x + (bb.x - ba.x) * t, ba.y + (bb.y - ba.y) * t,
                                ba.w + (bb.w - ba.w) * t, ba.h + (bb.h - ba.h) * t, min(ba.score, bb.score))
        order = sorted(filled)
        cx = _smooth([filled[f].cx for f in order], smooth_radius)
        cy = _smooth([filled[f].cy for f in order], smooth_radius)
        w = _smooth([filled[f].w for f in order], smooth_radius)
        h = _smooth([filled[f].h for f in order], smooth_radius)
        boxes = {f: Box(cx[i] - w[i] / 2, cy[i] - h[i] / 2, w[i], h[i], filled[f].score) for i, f in enumerate(order)}
        tracks.append(Track(0, boxes, set(hits)))

    # The same face split into two tracks by a fast move: where tracks cover the same face,
    # the frames belong to the track with more detections; the other keeps its longest
    # remaining stretch, or goes away when too little is left.
    tracks.sort(key=lambda t: -len(t.detected))
    kept: list[Track] = []
    for track in tracks:
        clash = {f for other in kept for f in track.boxes
                 if f in other.boxes and _iou(track.boxes[f], other.boxes[f]) > 0.2}
        if clash:
            free = [f for f in sorted(track.boxes) if f not in clash]
            runs, run = [], []
            for f in free:
                if run and f != run[-1] + 1:
                    runs.append(run)
                    run = []
                run.append(f)
            if run:
                runs.append(run)
            best = max(runs, key=len) if runs else []
            track = Track(0, {f: track.boxes[f] for f in best}, {f for f in track.detected if f in set(best)})
        if len(track.detected) >= min_hits:
            kept.append(track)
    kept.sort(key=lambda t: (t.start, t.boxes[t.start].cx))
    for i, track in enumerate(kept):
        track.id = i + 1
    return kept


@dataclass(frozen=True)
class CropPlan:
    sizes: dict[int, int]                   # frame -> square crop side in source pixels
    corners: dict[int, tuple[int, int]]     # frame -> (x0, y0)
    centers: dict[int, tuple[float, float, float]]  # frame -> face centre (x, y) inside the crop, face size


def plan_crop(track: Track, frame_w: int, frame_h: int, frame_count: int, refine_size: int,
              context: float = 2.2, max_upscale: float = 4.0, size_radius: int = 12) -> CropPlan:
    """A square crop per frame that follows the face: the face size (smoothed over about
    a second so the crop does not pump) times ``context``, but at least ``refine_size /
    max_upscale`` so it is never blown up more than that. Frames before/after the
    track hold its first/last crop."""
    order = sorted(track.boxes)
    smooth = _smooth([track.boxes[f].size for f in order], size_radius)
    face_size = dict(zip(order, smooth))
    sizes, corners, centers = {}, {}, {}
    for f in range(frame_count):
        key = min(max(f, track.start), track.end)
        box = track.boxes[key]
        size = int(round(min(max(face_size[key] * context, refine_size / max_upscale), frame_w, frame_h)))
        x0 = int(round(min(max(box.cx - size / 2, 0), frame_w - size)))
        y0 = int(round(min(max(box.cy - size / 2, 0), frame_h - size)))
        sizes[f], corners[f], centers[f] = size, (x0, y0), (box.cx - x0, box.cy - y0, face_size[key])
    return CropPlan(sizes, corners, centers)


def paste_weights(track: Track, near: int = 2, fade: int = 4, fast: tuple[float, float] = (0.12, 0.35)) -> dict[int, float]:
    """How much of the redraw to use on each frame of the track.

    Full weight within ``near`` frames of a real detection, fading out over ``fade``
    more frames, so frames where the face was lost (back of the head, a blur in a fast
    spin) keep the original instead of getting an invented face. Fast-moving faces
    (centre moving more than ``fast[0]`` face sizes per frame, zero at ``fast[1]``)
    keep their natural motion blur.
    """
    detected = sorted(track.detected)
    weights = {}
    for f in range(track.start, track.end + 1):
        gap = min(abs(f - d) for d in detected)
        w = 1.0 if gap <= near else max(0.0, 1.0 - (gap - near) / fade)
        prev, nxt = track.boxes.get(f - 1, track.boxes[f]), track.boxes.get(f + 1, track.boxes[f])
        speed = (((nxt.cx - prev.cx) ** 2 + (nxt.cy - prev.cy) ** 2) ** 0.5 / 2) / max(track.boxes[f].size, 1.0)
        w *= min(1.0, max(0.0, (fast[1] - speed) / (fast[1] - fast[0])))
        weights[f] = w
    frames = sorted(weights)
    smoothed = _smooth([weights[f] for f in frames], 2)
    return {f: min(weights[f], s) if weights[f] == 0 else s for f, s in zip(frames, smoothed)}


def parse_face_ids(text: str) -> set[int] | None:
    """'1, 3' -> {1, 3}; empty -> None (all faces)."""
    ids = set()
    for part in (text or "").replace("，", ",").replace("、", ",").split(","):
        part = part.strip()
        if part:
            if not part.isdigit():
                raise ValueError(f"「只修这些脸」只能填数字，用逗号分开，例如 1,3（现在是：{text}）")
            ids.add(int(part))
    return ids or None


def describe_track(track: Track, frame_w: int) -> str:
    first = track.boxes[track.start]
    side = "左侧" if first.cx < frame_w / 3 else "右侧" if first.cx > frame_w * 2 / 3 else "中间"
    return (f"脸 {track.id}：{side}，第 {track.start}–{track.end} 帧（{track.start / 24:.1f}–{(track.end + 1) / 24:.1f}s），"
            f"大小约 {track.median_size():.0f}px")
