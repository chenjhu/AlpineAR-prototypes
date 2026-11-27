"""python -m pytest tests  (run from live-stone-on-paper/)"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stone_on_paper import Params, StoneTracker, draw, order_corners  # noqa: E402

PPM = 2.0  # synthetic paper is drawn at 2 px per mm


def lab_to_bgr(L, a, b):
    return cv2.cvtColor(np.uint8([[[L, a, b]]]), cv2.COLOR_LAB2BGR)[0, 0].astype(int)


# Colours sampled from a real webcam frame: a pale beige stone on white paper.
PAPER = lab_to_bgr(242, 125, 134)
BEIGE = lab_to_bgr(200, 125, 148)


def stone_polygon(cx, cy, rx, ry, seed):
    """Irregular stone outline in paper millimetres."""
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    r = 1 + rng.uniform(-0.12, 0.12, t.size)
    return np.stack([cx + rx * r * np.cos(t), cy + ry * r * np.sin(t)], 1)


def make_frame(stones_mm, corners, finger=True, seed=0, colour=None):
    """A hand-held A4 sheet (landscape) with stones in a cluttered room."""
    rng = np.random.default_rng(seed)
    h, w = 720, 1280
    frame = rng.integers(40, 110, (h, w, 3), dtype=np.uint8)
    for _ in range(25):                      # furniture / posters
        x, y = rng.integers(0, w), rng.integers(0, h)
        c = tuple(int(v) for v in rng.integers(0, 160, 3))
        cv2.rectangle(frame, (x, y), (x + rng.integers(40, 300),
                      y + rng.integers(40, 200)), c, -1)
    frame = cv2.GaussianBlur(frame, (7, 7), 0)

    pw, ph = int(297 * PPM), int(210 * PPM)
    paper = np.full((ph, pw, 3), PAPER, np.uint8)
    for poly in stones_mm:
        pts = np.round(poly * PPM).astype(np.int32)
        shadow = np.zeros((ph, pw), np.uint8)
        cv2.fillPoly(shadow, [pts + 8], 255)
        shadow = cv2.GaussianBlur(shadow, (31, 31), 0)[..., None] / 255.0
        paper = (paper * (1 - 0.1 * shadow)).astype(np.uint8)
        base = colour if colour is not None else np.array([95, 100, 105])
        texture = rng.integers(-12, 12, (ph, pw, 1))
        stone = np.clip(base + texture, 0, 255).astype(np.uint8)
        m = np.zeros((ph, pw), np.uint8)
        cv2.fillPoly(m, [pts], 255)
        paper[m > 0] = stone[m > 0]

    src = np.float32([[0, 0], [pw, 0], [pw, ph], [0, ph]])
    H = cv2.getPerspectiveTransform(src, np.float32(corners))
    warped = cv2.warpPerspective(paper, H, (w, h))
    inside = cv2.warpPerspective(np.full((ph, pw), 255, np.uint8), H, (w, h))
    frame[inside > 0] = warped[inside > 0]

    if finger:                               # thumb over the left edge
        tl, bl = np.float32(corners[0]), np.float32(corners[3])
        p = (0.6 * tl + 0.4 * bl).astype(int)
        cv2.ellipse(frame, (int(p[0]) + 10, int(p[1])), (45, 22), 10, 0, 360,
                    (120, 150, 210), -1)
    return cv2.add(frame, rng.integers(0, 6, frame.shape, dtype=np.uint8))


CORNERS = [[330, 140], [980, 170], [1010, 600], [300, 580]]
CUT_OFF = [[200, 250], [900, 280], [1200, 580], [-60, 760]]  # one corner off-frame


def run(frame):
    return StoneTracker(params=Params(smoothing=0)).update(frame)


def area_cm2(poly):
    return cv2.contourArea(poly.astype(np.float32)) / 100


def test_order_corners_is_clockwise_from_top_left():
    pts = np.float32([[10, 100], [100, 100], [10, 10], [100, 10]])
    assert order_corners(pts).tolist() == [[10, 10], [100, 10], [100, 100], [10, 100]]


def test_one_stone_area_and_size():
    poly = stone_polygon(150, 105, 50, 32, seed=1)
    res = run(make_frame([poly], CORNERS))
    assert res.paper is not None and res.corners is not None
    assert np.max(np.abs(res.corners - np.float32(CORNERS))) < 12
    assert len(res.stones) == 1                # the thumb is ignored
    s = res.stones[0]
    assert abs(s.area_cm2 - area_cm2(poly)) / area_cm2(poly) < 0.12
    assert 85 < s.length_mm < 115 and 55 < s.width_mm < 75


def test_pale_beige_stone_like_the_real_one():
    poly = stone_polygon(150, 105, 40, 30, seed=4)
    res = run(make_frame([poly], CORNERS, colour=BEIGE))
    assert len(res.stones) == 1
    assert abs(res.stones[0].area_cm2 - area_cm2(poly)) / area_cm2(poly) < 0.15


def test_corner_out_of_frame_still_finds_stone_without_scale():
    poly = stone_polygon(150, 105, 40, 30, seed=5)
    res = run(make_frame([poly], CUT_OFF, finger=False, colour=BEIGE))
    assert res.paper is not None and res.corners is None
    assert len(res.stones) == 1 and res.stones[0].area_cm2 is None


def test_two_stones():
    polys = [stone_polygon(80, 100, 35, 28, seed=2),
             stone_polygon(210, 110, 45, 30, seed=3)]
    assert len(run(make_frame(polys, CORNERS)).stones) == 2


def test_empty_paper_has_no_stones():
    assert run(make_frame([], CORNERS)).stones == []


def test_no_paper():
    frame = np.random.default_rng(0).integers(30, 90, (720, 1280, 3), dtype=np.uint8)
    res = run(frame)
    assert res.paper is None and res.stones == []
    draw(frame, res)                           # must not crash


def test_tracking_follows_moving_paper():
    poly = stone_polygon(150, 105, 50, 32, seed=1)
    tracker = StoneTracker(params=Params(smoothing=0.5))
    for dx in range(0, 60, 6):                 # paper slides right
        corners = [[x + dx, y] for x, y in CORNERS]
        frame = make_frame([poly], corners, seed=dx)
        res = tracker.update(frame)
        draw(frame, res, show_mask=True)       # mask view must not crash
    assert len(res.stones) == 1
    assert np.max(np.abs(res.corners - np.float32(corners))) < 25
