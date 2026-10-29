"""python -m pytest tests  (run from live-stone-on-paper/)"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stone_on_paper import StoneOnPaper, draw, order_corners  # noqa: E402

PPM = 2.0  # synthetic paper is drawn at 2 px per mm


def stone_polygon(cx, cy, rx, ry, seed):
    """Irregular stone outline in paper millimetres."""
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    r = 1 + rng.uniform(-0.12, 0.12, t.size)
    return np.stack([cx + rx * r * np.cos(t), cy + ry * r * np.sin(t)], 1)


def make_frame(stones_mm, corners, finger=True, seed=0):
    """A hand-held A4 sheet (landscape) with stones in a cluttered room."""
    rng = np.random.default_rng(seed)
    h, w = 720, 1280
    frame = rng.integers(40, 110, (h, w, 3), dtype=np.uint8)
    for _ in range(25):                      # furniture / posters
        x, y = rng.integers(0, w), rng.integers(0, h)
        colour = tuple(int(c) for c in rng.integers(0, 160, 3))
        cv2.rectangle(frame, (x, y), (x + rng.integers(40, 300),
                      y + rng.integers(40, 200)), colour, -1)
    frame = cv2.GaussianBlur(frame, (7, 7), 0)

    pw, ph = int(297 * PPM), int(210 * PPM)
    paper = np.full((ph, pw, 3), (235, 238, 240), np.uint8)
    for poly in stones_mm:
        pts = np.round(poly * PPM).astype(np.int32)
        shadow = np.zeros((ph, pw), np.uint8)
        cv2.fillPoly(shadow, [pts + 6], 255)
        shadow = cv2.GaussianBlur(shadow, (31, 31), 0)[..., None] / 255.0
        paper = (paper * (1 - 0.25 * shadow)).astype(np.uint8)
        grey = rng.integers(70, 120)
        texture = rng.integers(-15, 15, (ph, pw, 1))
        stone = np.clip(grey + texture + [0, 5, 10], 0, 255).astype(np.uint8)
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


def test_order_corners_is_clockwise_from_top_left():
    pts = np.float32([[10, 100], [100, 100], [10, 10], [100, 10]])
    assert order_corners(pts).tolist() == [[10, 10], [100, 10], [100, 100], [10, 100]]


def test_one_stone_area_and_size():
    poly = stone_polygon(150, 105, 50, 32, seed=1)
    true_area = cv2.contourArea(poly.astype(np.float32)) / 100
    res = StoneOnPaper().update(make_frame([poly], CORNERS), smoothing=0)
    assert res.paper is not None
    assert np.max(np.abs(res.paper - np.float32(CORNERS))) < 12
    assert len(res.stones) == 1                # the thumb is ignored
    s = res.stones[0]
    assert abs(s.area_cm2 - true_area) / true_area < 0.12
    assert 85 < s.length_mm < 115 and 55 < s.width_mm < 75


def test_two_stones():
    polys = [stone_polygon(80, 100, 35, 28, seed=2),
             stone_polygon(210, 110, 45, 30, seed=3)]
    res = StoneOnPaper().update(make_frame(polys, CORNERS), smoothing=0)
    assert len(res.stones) == 2


def test_no_paper():
    frame = np.random.default_rng(0).integers(30, 90, (720, 1280, 3), dtype=np.uint8)
    res = StoneOnPaper().update(frame)
    assert res.paper is None and res.stones == []
    draw(frame, res)                           # must not crash


def test_tracking_follows_moving_paper():
    poly = stone_polygon(150, 105, 50, 32, seed=1)
    tracker = StoneOnPaper()
    for dx in range(0, 60, 6):                 # paper slides right
        corners = [[x + dx, y] for x, y in CORNERS]
        res = tracker.update(make_frame([poly], corners, seed=dx), smoothing=0.5)
    assert len(res.stones) == 1
    assert np.max(np.abs(res.paper - np.float32(corners))) < 25
