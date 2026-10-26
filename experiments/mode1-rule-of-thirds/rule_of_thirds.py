"""Step 2 - turn two detected base stones into the virtual box for the next
stone ("place a joint on a rock and a rock on a joint", p.22).

The phone looks straight down on the wall (top view). Everything is measured
in wall coordinates, not image axes: `u` runs along the wall (perpendicular
to the joint between the two stones), `n` runs across it (the wall depth). So the wall
may run in any direction in the picture.

For a left stone L = [L0, L1] and a right stone R = [R0, R1] along `u`:

    must zone    (blue hatched)  = [L1 - wL/3, R0 + wR/3]
        the new stone has to cover at least this: the joint plus the inner
        third of each stone below it.
    allowed zone (white)         = [L0 + wL/3, R1 - wR/3]
        the new stone must stay inside this, so the outer thirds stay free
        for the neighbouring stones of the same layer.

Across the wall the box spans the depth both stones share, so the new stone
rests on both. Heights are not visible from above; that needs depth data.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from stone_detect import Stone

THIRD = 1.0 / 3.0


@dataclass
class Span:
    lo: float
    hi: float

    @property
    def width(self) -> float:
        return self.hi - self.lo


@dataclass
class ThirdsResult:
    left: Stone
    right: Stone
    origin: np.ndarray       # image point where u = n = 0 (left end of the wall line)
    u: np.ndarray            # unit vector along the wall, left -> right stone
    n: np.ndarray            # unit vector across the wall
    left_span: Span
    right_span: Span
    joint: float             # u coordinate of the joint (middle of the gap)
    gap: float               # gap between the stones along u (<0: overlap)
    must: Span
    allowed: Span
    depth: Span              # across the wall: where the new stone should sit
    outer: Span              # across the wall: union of both stones (for drawing)

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
            "stone_depth": round(self.depth.width * k, 1),
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
    cover_left: float        # fraction of the left stone covered (want 1/3..2/3)
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


def compute_thirds(left: Stone, right: Stone) -> ThirdsResult:
    """Rule-of-thirds zones for the stone that goes on top of `left`/`right`."""
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

    must = Span(L.hi - THIRD * L.width, R.lo + THIRD * R.width)
    allowed = Span(L.lo + THIRD * L.width, R.hi - THIRD * R.width)

    # Across the wall: the depth both stones share, measured near the joint
    # (inside the must zone) where the new stone actually rests; measuring
    # whole stones would let their far corners widen it. If the stones are
    # badly offset, fall back to the average of the two.
    near_l, near_r = ln[lu >= must.lo], rn[ru <= must.hi]
    dl = Span(float(near_l.min()), float(near_l.max()))
    dr = Span(float(near_r.min()), float(near_r.max()))
    depth = Span(max(dl.lo, dr.lo), min(dl.hi, dr.hi))
    if depth.width < 0.5 * min(dl.width, dr.width):
        depth = Span((dl.lo + dr.lo) / 2, (dl.hi + dr.hi) / 2)

    return ThirdsResult(
        left=left, right=right, origin=origin, u=u, n=n,
        left_span=L, right_span=R,
        joint=0.5 * (L.hi + R.lo), gap=R.lo - L.hi,
        must=must, allowed=allowed, depth=depth,
        outer=Span(float(min(ln.min(), rn.min())), float(max(ln.max(), rn.max()))),
    )


def check_placement(result: ThirdsResult, candidate: Stone,
                    tolerance: float = 0.03) -> PlacementCheck:
    """Does `candidate` (a stone laid on top) follow the rule of thirds?
    `tolerance` is a fraction of each base stone's width."""
    cu = (_points(candidate) - result.origin) @ result.u
    return check_span(result, Span(float(cu.min()), float(cu.max())), candidate, tolerance)


def check_marked_points(result: ThirdsResult, points,
                        tolerance: float = 0.03) -> PlacementCheck:
    """Same check from points clicked around the new stone's outline (the
    hand fallback when it cannot be segmented). Only their extent along the
    wall matters, so any points on the outline work."""
    a = (np.asarray(points, np.float32) - result.origin) @ result.u
    return check_span(result, Span(float(a.min()), float(a.max())), None, tolerance)


def check_span(result: ThirdsResult, span: Span, stone: Stone | None = None,
               tolerance: float = 0.03) -> PlacementCheck:
    L, R = result.left_span, result.right_span
    cover_left = float(np.clip((L.hi - span.lo) / L.width, 0, 1))
    cover_right = float(np.clip((span.hi - R.lo) / R.width, 0, 1))

    lo_ok, hi_ok = THIRD - tolerance, 2 * THIRD + tolerance
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
        ok=ok, message="rule of thirds OK" if ok else "; ".join(problems),
    )
