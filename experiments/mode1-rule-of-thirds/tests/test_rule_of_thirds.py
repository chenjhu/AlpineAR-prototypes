"""python -m pytest tests  (run from mode1_rule_of_thirds/)"""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_synthetic import make_scene  # noqa: E402
from rule_of_thirds import (  # noqa: E402
    Span, check_marked_points, check_placement, check_span, compute_zone, pick_base_pair)
from stone_detect import Stone, detect_placed_stone, detect_stones  # noqa: E402


def stone_from_contour(c) -> Stone:
    c = np.round(np.asarray(c, np.float32)).astype(np.int32).reshape(-1, 1, 2)
    m = cv2.moments(c)
    return Stone(contour=c, area=cv2.contourArea(c),
                 centroid=(m["m10"] / m["m00"], m["m01"] / m["m00"]),
                 bbox=cv2.boundingRect(c), min_rect=cv2.minAreaRect(c))


def rect_stone(x0, y0, x1, y1) -> Stone:
    return stone_from_contour([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])


# Top view: stone 1 is 300 long, stone 2 is 300 long, 10 apart; both 100 deep.
LEFT, RIGHT = rect_stone(0, 400, 300, 500), rect_stone(310, 400, 610, 500)


def test_zones_for_two_rectangles():
    r = compute_zone(LEFT, RIGHT)
    # joint line in the middle of the 10 gap; each stone reaches to it: x = y = 305
    assert r.joint == pytest.approx(305) and r.gap == pytest.approx(10)
    assert r.x == pytest.approx(305) and r.y == pytest.approx(305)
    assert r.must.lo == pytest.approx(305 - 305 / 4) and r.must.hi == pytest.approx(305 + 305 / 4)
    assert r.allowed.lo == pytest.approx(305 - 3 * 305 / 4) and r.allowed.hi == pytest.approx(305 + 3 * 305 / 4)
    assert r.depth.width == pytest.approx(100)
    # the must box lies on top of both stones, across the joint
    quad = r.box(r.must)
    assert quad[:, 0].min() == pytest.approx(228.75) and quad[:, 0].max() == pytest.approx(381.25)
    assert quad[:, 1].min() == pytest.approx(400) and quad[:, 1].max() == pytest.approx(500)


def test_length_rule_of_the_slides():
    # slide 14:  x/4 + y/4  <=  z  <=  3x/4 + 3y/4   (B 262, C 200 long, touching)
    r = compute_zone(rect_stone(0, 0, 262, 100), rect_stone(262, 0, 462, 100))
    assert r.must.width == pytest.approx(262 / 4 + 200 / 4)
    assert r.allowed.width == pytest.approx(3 * 262 / 4 + 3 * 200 / 4)


def test_old_rule_of_thirds_is_one_argument_away():
    r = compute_zone(rect_stone(0, 0, 300, 100), rect_stone(300, 0, 600, 100), fraction=1 / 3)
    assert (r.must.lo, r.must.hi) == pytest.approx((200, 400))
    assert (r.allowed.lo, r.allowed.hi) == pytest.approx((100, 500))


def test_green_box_for_a_chosen_stone():
    # slides 7-9: B and C 262 long, touching at 262; stone F is 215 long.
    r = compute_zone(rect_stone(0, 0, 262, 100), rect_stone(262, 0, 524, 100))
    box = r.place_box(215)
    # F's left end may go from (C's quarter line - 215) to B's 3/4 line
    assert (box.lo, box.hi) == pytest.approx((262 + 65.5 - 215, 262 - 65.5 + 215))
    # at both ends of the box F still covers a quarter of each stone
    for lo in (box.lo, box.hi - 215):
        assert check_span(r, Span(lo, lo + 215)).ok
    # the shortest stone has no room to move; the longest fills the allowed zone
    shortest, longest = r.place_box(r.must.width), r.place_box(r.allowed.width)
    assert (shortest.lo, shortest.hi) == pytest.approx((r.must.lo, r.must.hi))
    assert (longest.lo, longest.hi) == pytest.approx((r.allowed.lo, r.allowed.hi))
    assert r.place_box(r.must.width - 1) is None and r.place_box(r.allowed.width + 1) is None


def test_depth_range_is_average_plus_minus_ten_percent():
    r = compute_zone(rect_stone(0, 0, 300, 100), rect_stone(300, 10, 600, 70))   # 100 and 60 deep
    assert (r.stone_depth.lo, r.stone_depth.hi) == pytest.approx((72, 88))


def test_depth_is_what_both_stones_share():
    r = compute_zone(LEFT, rect_stone(310, 420, 610, 480))   # shallower stone 2
    assert r.depth.width == pytest.approx(60)


@pytest.mark.parametrize("angle", [35, 90, 150])
def test_wall_can_run_in_any_direction(angle):
    rot = cv2.getRotationMatrix2D((300, 450), angle, 1.0)
    turn = lambda s: stone_from_contour(cv2.transform(s.contour.astype(np.float32), rot))
    left, right, _ = pick_base_pair([turn(LEFT), turn(RIGHT)])
    r0, r1 = compute_zone(LEFT, RIGHT), compute_zone(left, right)
    assert r1.must.width == pytest.approx(r0.must.width, rel=0.02)
    assert r1.allowed.width == pytest.approx(r0.allowed.width, rel=0.02)
    assert r1.stone_depth.lo == pytest.approx(r0.stone_depth.lo, rel=0.02)


@pytest.mark.parametrize("x0, x1, ok", [
    (190, 430, True),     # covers 38% of stone 1, 41% of stone 2
    (250, 350, False),    # too short: 15% of stone 2
    (40, 360, False),     # reaches over 3/4 of stone 1 (87%)
])
def test_check_placement(x0, x1, ok):
    r = compute_zone(LEFT, RIGHT)
    assert check_placement(r, rect_stone(x0, 410, x1, 490)).ok is ok


def iou(stone: Stone, poly, shape) -> float:
    a = np.zeros(shape, np.uint8)
    b = np.zeros(shape, np.uint8)
    cv2.drawContours(a, [stone.contour], -1, 1, cv2.FILLED)
    cv2.fillPoly(b, [np.round(poly).astype(np.int32)], 1)
    return (a & b).sum() / max(1, (a | b).sum())


@pytest.mark.parametrize("seed, gap, angle", [(0, 14, 0), (1, 0, 0), (2, 10, -35), (5, 6, 60)])
def test_detects_both_synthetic_stones(seed, gap, angle):
    img, polys = make_scene(seed, gap=gap, angle=angle)
    stones = detect_stones(img).stones
    assert len(stones) == 2
    for s in stones:
        assert max(iou(s, p, img.shape[:2]) for p in polys) > 0.85


def test_click_seeds_split_touching_stones():
    img, polys = make_scene(1, gap=0)
    seeds = [tuple(p.mean(axis=0)) for p in polys]
    stones = detect_stones(img, seeds=seeds).stones
    assert len(stones) == 2


@pytest.mark.parametrize("placed, ok", [((-110, 120), True), ((30, 240), False)])
def test_before_after_placement(placed, ok):
    before, _ = make_scene(0)
    after, polys = make_scene(0, placed=placed)
    left, right, _ = pick_base_pair(detect_stones(before).stones)
    new = detect_placed_stone(before, after)
    assert new is not None and iou(new, polys[2], before.shape[:2]) > 0.8
    assert check_placement(compute_zone(left, right), new).ok is ok


def test_marked_points_use_extent_along_the_wall():
    r = compute_zone(LEFT, RIGHT)
    outline = [(190, 450), (300, 412), (430, 455), (310, 488)]   # around a good stone
    assert check_marked_points(r, outline).ok
    top_bottom = [(300, 412), (310, 488)]                           # across the wall only
    assert not check_marked_points(r, top_bottom).ok
