"""Step 2 - turn two detected supporting stones into the zone for the next
stone ("place a joint on a rock and a rock on a joint", p.22).

Since 2026-11-23 the rule is in QUARTERS (the group's diagrams, "Alpine
ARchitecture" slides 1-14), no longer thirds; `fraction` keeps the old rule
one argument away. The file keeps its name so the imports elsewhere stay.

The phone looks straight down on the wall (top view). Everything is measured
in wall coordinates, not image axes: `u` runs along the wall (perpendicular
to the joint between the two stones), `n` runs across it (the wall depth). So
the wall may run in any direction in the picture.

The joint is one line, J, in the middle of whatever gap the outlines leave
(a gap is hard to see reliably in a photo, so it is not used on its own):
each stone reaches from its outer end (its outline's point furthest along
the wall) to J. Stone B (left) is x long, stone C (right) y long:

    must zone    (red area, E_min)  = [J - x/4, J + y/4]
        the new stone covers at least a quarter of each stone.
    allowed zone (red lines, E_max) = [J - 3x/4, J + 3y/4]
        and at most three quarters, so the outer quarters stay free for the
        neighbouring stones of the same course.

    so its length z:  x/4 + y/4  <=  z  <=  3x/4 + 3y/4

For a chosen stone of length z the green box (`place_box`) is where it can
travel freely and still follow the rule:

    [max(J - 3x/4, J + y/4 - z) , min(J + 3y/4, J - x/4 + z)]

Depth (across the wall): the new stone should be as deep as the average of
the two supporting stones, +-10 % (`stone_depth`). The drawn boxes span the
depth both stones share near the joint (`depth`), where the new stone rests.
Heights are not visible from above; that needs depth data.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from stone_detect import Stone

QUARTER = 0.25          # the rule: cover 1/4 .. 3/4 of each stone
DEPTH_TOLERANCE = 0.10  # new stone's depth: average of the two +- 10 %


@dataclass
class Span:
    lo: float
    hi: float

    @property
    def width(self) -> float:
        return self.hi - self.lo


@dataclass
class ZoneResult:
    left: Stone
    right: Stone
    origin: np.ndarray       # image point where u = n = 0 (left end of the wall line)
    u: np.ndarray            # unit vector along the wall, left -> right stone
    n: np.ndarray            # unit vector across the wall
    left_span: Span          # each stone as detected, along u (for drawing)
    right_span: Span
    joint: float             # u coordinate of the joint line J (middle of the gap)
    gap: float               # gap the outlines leave along u (<0: overlap); not used by the rule
    fraction: float          # the rule: cover fraction .. 1 - fraction of each stone
    must: Span               # E_min, the red area
    allowed: Span            # E_max, between the red lines
    depth: Span              # across the wall: where the new stone should sit (drawing)
    outer: Span              # across the wall: union of both stones (for drawing)
    stone_depth: Span        # how deep the new stone should be: average of the two +- 10 %

    @property
    def x(self) -> float:
        """Length of the left stone B: its outer end to the joint line."""
        return self.joint - self.left_span.lo

    @property
    def y(self) -> float:
        """Length of the right stone C: the joint line to its outer end."""
        return self.right_span.hi - self.joint

    def place_box(self, z: float) -> Span | None:
        """The green box: where a stone of length `z` (along the wall) can
        travel freely and still cover `fraction` .. 1 - `fraction` of both
        stones. None if no position works (z too short or too long)."""
        if z < self.must.width or z > self.allowed.width:
            return None
        return Span(max(self.allowed.lo, self.must.hi - z),
                    min(self.allowed.hi, self.must.lo + z))

    def to_image(self, a, b) -> np.ndarray:
        """Wall coordinates (a along u, b along n) -> image (x, y)."""
        a = np.asarray(a, np.float32)[..., None]
        b = np.asarray(b, np.float32)[..., None]
        return self.origin + a * self.u + b * self.n

    def box(self, span: Span) -> np.ndarray:
        """Quad (4, 2) in image coords for `span` (along) x `depth` (across)."""
        a = [span.lo, span.hi, span.hi, span.lo]
        b = [self.depth.lo, self.depth.lo, self.depth.hi, self.depth.hi]
        return self.to_image(a, b)

    def to_dict(self, px_per_unit: float = 1.0, unit: str = "px") -> dict:
        k = 1.0 / px_per_unit
        return {
            "unit": unit,
            "stone_length_min": round(self.must.width * k, 1),
            "stone_length_max": round(self.allowed.width * k, 1),
            "stone_depth_min": round(self.stone_depth.lo * k, 1),
            "stone_depth_max": round(self.stone_depth.hi * k, 1),
            "rule_fraction": self.fraction,
            "x": round(self.x * k, 1),
            "y": round(self.y * k, 1),
            "must_zone": [round(self.must.lo * k, 1), round(self.must.hi * k, 1)],
            "allowed_zone": [round(self.allowed.lo * k, 1), round(self.allowed.hi * k, 1)],
            "joint": round(self.joint * k, 1),
            "gap": round(self.gap * k, 1),
            "image_quads_px": {
                "must": self.box(self.must).round(1).tolist(),
                "allowed": self.box(self.allowed).round(1).tolist(),
            },
        }


@dataclass
class PlacementCheck:
    stone: Stone | None      # None when the span was marked by hand
    span: Span
    cover_left: float        # fraction of the left stone covered (want 1/4..3/4)
    cover_right: float
    ok: bool
    message: str


def _points(stone: Stone) -> np.ndarray:
    return stone.contour.reshape(-1, 2).astype(np.float32)


def pick_base_pair(stones: list[Stone]) -> tuple[Stone, Stone, list[Stone]]:
    """The two largest stones are the base pair, ordered left -> right (top
    -> bottom if the wall runs vertically in the picture)."""
    if len(stones) < 2:
        raise ValueError(f"need two base stones, found {len(stones)}")
    by_area = sorted(stones, key=lambda s: s.area, reverse=True)
    a, b = by_area[:2]
    dx, dy = b.centroid[0] - a.centroid[0], b.centroid[1] - a.centroid[1]
    if (dx if abs(dx) >= abs(dy) else dy) < 0:
        a, b = b, a
    return a, b, by_area[2:]


def _wall_direction(left: Stone, right: Stone) -> np.ndarray:
    """Unit vector along the wall. Best estimate: perpendicular to the joint,
    i.e. to the line where the two outlines run close together. Irregular
    stones pull their centres off the wall line, so the centre-to-centre
    direction is only the fallback (stones far apart / joint too short)."""
    c = np.asarray(right.centroid, np.float32) - np.asarray(left.centroid, np.float32)
    c /= np.linalg.norm(c)
    pl, pr = _points(left)[::4], _points(right)[::4]     # subsample for speed
    dist = lambda pts, other: np.abs(np.array(
        [cv2.pointPolygonTest(other.contour, (float(x), float(y)), True) for x, y in pts]))
    dl, dr = dist(pl, right), dist(pr, left)
    size = np.sqrt(min(left.area, right.area))
    band = min(dl.min(), dr.min()) + 0.06 * size
    near = np.concatenate([pl[dl <= band], pr[dr <= band]])
    if len(near) < 10:
        return c
    centred = near - near.mean(axis=0)
    _, sv, vt = np.linalg.svd(centred, full_matrices=False)
    j = vt[0]                                        # joint direction
    if 4 * sv[0] / np.sqrt(len(near)) < 0.3 * size:  # joint too short to trust
        return c
    u = np.array([j[1], -j[0]], np.float32)
    return u if u @ c > 0 else -u


def _depth_across(stone: Stone, n: np.ndarray) -> float:
    """A stone's depth: the side of its minimum-area rectangle that runs
    across the wall (closer to `n`). Its plain extent along `n` grows with
    every degree the wall direction is off (a 30 cm stone, 2 degrees: +1 cm);
    the rectangle follows the stone, so it is also right for a stone laid
    lengthwise into the wall."""
    box = cv2.boxPoints(cv2.minAreaRect(stone.contour.reshape(-1, 1, 2).astype(np.float32)))
    a, b = box[1] - box[0], box[2] - box[1]
    return float(np.linalg.norm(a if abs(a @ n) * np.linalg.norm(b) >= abs(b @ n) * np.linalg.norm(a) else b))


def compute_zone(left: Stone, right: Stone, fraction: float = QUARTER) -> ZoneResult:
    """The zones for the stone that goes on top of `left`/`right`
    (`fraction` = 1/4: the quarter rule; 1/3 gives the old rule of thirds)."""
    c_left = np.asarray(left.centroid, np.float32)
    u = _wall_direction(left, right)
    n = np.array([-u[1], u[0]], np.float32)

    def project(stone, origin):
        d = _points(stone) - origin
        return d @ u, d @ n

    # Put the origin at the left end of the left stone so u starts at 0.
    lu, _ = project(left, c_left)
    origin = c_left + float(lu.min()) * u
    lu, ln = project(left, origin)
    ru, rn = project(right, origin)
    L = Span(float(lu.min()), float(lu.max()))
    R = Span(float(ru.min()), float(ru.max()))

    # One joint line J in the middle of the gap; each stone reaches to it.
    joint = 0.5 * (L.hi + R.lo)
    x, y = joint - L.lo, R.hi - joint
    must = Span(joint - fraction * x, joint + fraction * y)
    allowed = Span(joint - (1 - fraction) * x, joint + (1 - fraction) * y)

    # Across the wall: the depth both stones share, measured near the joint
    # (inside the must zone) where the new stone actually rests; measuring
    # whole stones would let their far corners widen it. If the stones are
    # badly offset, fall back to the average of the two.
    near_l, near_r = ln[lu >= must.lo], rn[ru <= must.hi]
    # A stone that does not reach into the must zone (odd outlines, stones
    # overlapping along the wall): take all of it (real-scale test, 2026-11-24).
    if near_l.size == 0:
        near_l = ln
    if near_r.size == 0:
        near_r = rn
    dl = Span(float(near_l.min()), float(near_l.max()))
    dr = Span(float(near_r.min()), float(near_r.max()))
    depth = Span(max(dl.lo, dr.lo), min(dl.hi, dr.hi))
    if depth.width < 0.5 * min(dl.width, dr.width):
        depth = Span((dl.lo + dr.lo) / 2, (dl.hi + dr.hi) / 2)

    # How deep the new stone should be: the average depth of the two, +- 10 %.
    mean_depth = 0.5 * (_depth_across(left, n) + _depth_across(right, n))
    stone_depth = Span((1 - DEPTH_TOLERANCE) * mean_depth, (1 + DEPTH_TOLERANCE) * mean_depth)

    return ZoneResult(
        left=left, right=right, origin=origin, u=u, n=n,
        left_span=L, right_span=R, joint=joint, gap=R.lo - L.hi,
        fraction=fraction, must=must, allowed=allowed, depth=depth,
        outer=Span(float(min(ln.min(), rn.min())), float(max(ln.max(), rn.max()))),
        stone_depth=stone_depth,
    )


def check_placement(result: ZoneResult, candidate: Stone,
                    tolerance: float = 0.03) -> PlacementCheck:
    """Does `candidate` (a stone laid on top) follow the rule?
    `tolerance` is a fraction of each base stone's length."""
    cu = (_points(candidate) - result.origin) @ result.u
    return check_span(result, Span(float(cu.min()), float(cu.max())), candidate, tolerance)


def check_marked_points(result: ZoneResult, points,
                        tolerance: float = 0.03) -> PlacementCheck:
    """Same check from points clicked around the new stone's outline (the
    hand fallback when it cannot be segmented). Only their extent along the
    wall matters, so any points on the outline work."""
    a = (np.asarray(points, np.float32) - result.origin) @ result.u
    return check_span(result, Span(float(a.min()), float(a.max())), None, tolerance)


def check_span(result: ZoneResult, span: Span, stone: Stone | None = None,
               tolerance: float = 0.03) -> PlacementCheck:
    # Both stones measured to the joint line, as the zones are.
    J, f = result.joint, result.fraction
    cover_left = float(np.clip((J - span.lo) / result.x, 0, 1))
    cover_right = float(np.clip((span.hi - J) / result.y, 0, 1))

    lo_ok, hi_ok = f - tolerance, 1 - f + tolerance
    problems = []
    if cover_left < lo_ok:
        problems.append("covers too little of stone 1")
    elif cover_left > hi_ok:
        problems.append("reaches too far onto stone 1 (blocks its next joint)")
    if cover_right < lo_ok:
        problems.append("covers too little of stone 2")
    elif cover_right > hi_ok:
        problems.append("reaches too far onto stone 2 (blocks its next joint)")

    ok = not problems
    return PlacementCheck(
        stone=stone, span=span, cover_left=cover_left, cover_right=cover_right,
        ok=ok, message="placement OK" if ok else "; ".join(problems),
    )
