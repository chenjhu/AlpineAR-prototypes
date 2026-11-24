"""Drawing helpers: the AR overlay and the step-by-step debug panels.

Visual language follows the Mode 1 sketch: blue hatched = where the new stone
must be, white = where it is allowed to be, dashed lines = quarters.
"""
from __future__ import annotations

import cv2
import numpy as np

from rule_of_thirds import PlacementCheck, ZoneResult
from stone_detect import Detection, Stone

BLUE = (125, 110, 45)        # BGR, the hatch colour of the sketch
WHITE = (255, 255, 255)
STONE_COLORS = [(80, 200, 255), (255, 170, 60), (140, 230, 120), (200, 120, 255)]
GREEN = (90, 220, 90)
RED = (60, 60, 235)
FONT = cv2.FONT_HERSHEY_SIMPLEX


def _k(img) -> float:
    """Drawing sizes are tuned for ~960 px wide images; phone photos are
    4x bigger, so lines, hatching and text scale with the width."""
    return max(1.0, img.shape[1] / 960)


def _t(img, thickness) -> int:
    return max(1, round(thickness * _k(img)))


def _ipts(pts) -> np.ndarray:
    return np.round(np.asarray(pts, np.float32)).astype(np.int32).reshape(-1, 1, 2)


def dashed_line(img, p0, p1, color, thickness=1, dash=10, gap=7) -> None:
    p0, p1 = np.asarray(p0, np.float32), np.asarray(p1, np.float32)
    length = float(np.linalg.norm(p1 - p0))
    if length < 1:
        return
    d = (p1 - p0) / length
    dash, gap, thickness = dash * _k(img), gap * _k(img), _t(img, thickness)
    t = 0.0
    while t < length:
        a = p0 + d * t
        b = p0 + d * min(t + dash, length)
        cv2.line(img, tuple(np.round(a).astype(int)), tuple(np.round(b).astype(int)),
                 color, thickness, cv2.LINE_AA)
        t += dash + gap


def hatch(img, quad, color, spacing=12, thickness=3) -> None:
    """Diagonal hatching clipped to `quad`."""
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.fillPoly(mask, [_ipts(quad)], 255)
    x, y, w, h = cv2.boundingRect(_ipts(quad))
    spacing, thickness = max(2, round(spacing * _k(img))), _t(img, thickness)
    lines = np.zeros_like(mask)
    for k in range(-h, w + h, spacing):
        cv2.line(lines, (x + k, y), (x + k + h, y + h), 255, thickness, cv2.LINE_AA)
    sel = cv2.bitwise_and(lines, mask) > 0
    img[sel] = color


def blend_fill(img, quad, color, alpha) -> None:
    layer = img.copy()
    cv2.fillPoly(layer, [_ipts(quad)], color, cv2.LINE_AA)
    cv2.addWeighted(layer, alpha, img, 1 - alpha, 0, img)


def label(img, text, org, color=WHITE, scale=0.55, bg=(30, 30, 30)) -> None:
    scale, weight, pad = scale * _k(img), _t(img, 1), _t(img, 4)
    (tw, th), base = cv2.getTextSize(text, FONT, scale, weight)
    x, y = int(org[0]), int(org[1])
    x = max(pad, min(x, img.shape[1] - tw - pad))
    y = max(th + pad, min(y, img.shape[0] - base - pad))
    cv2.rectangle(img, (x - pad, y - th - pad), (x + tw + pad, y + base + pad // 2), bg,
                  cv2.FILLED)
    cv2.putText(img, text, (x, y), FONT, scale, color, weight, cv2.LINE_AA)


def draw_stones(img, stones: list[Stone], rotated=False) -> np.ndarray:
    out = img.copy()
    for i, s in enumerate(stones):
        c = STONE_COLORS[i % len(STONE_COLORS)]
        cv2.drawContours(out, [s.contour], -1, c, _t(out, 2), cv2.LINE_AA)
        if rotated:
            box = cv2.boxPoints(s.min_rect)
            cv2.polylines(out, [_ipts(box)], True, c, _t(out, 1), cv2.LINE_AA)
        else:
            x, y, w, h = s.bbox
            cv2.rectangle(out, (x, y), (x + w, y + h), c, _t(out, 1), cv2.LINE_AA)
        label(out, f"stone {i + 1}", (s.bbox[0], s.bbox[1] - 6 * _k(out)), c)
    return out


def draw_rule_lines(img, r: ZoneResult) -> None:
    """Dashed quarter lines (thirds with the old rule) across both base
    stones, measured from the joint line as the zones are, seen from above."""
    pad = 0.15 * r.outer.width
    b0, b1 = r.outer.lo - pad, r.outer.hi + pad
    steps = int(round(1 / r.fraction))
    for i in range(1, steps + 1):
        for a in (r.joint - i * r.x / steps, r.joint + i * r.y / steps):
            dashed_line(img, r.to_image(a, b0), r.to_image(a, b1), WHITE, 1)
    dashed_line(img, r.to_image(r.joint, b0), r.to_image(r.joint, b1), BLUE, 2, 4, 4)


def draw_zone(img, r: ZoneResult) -> None:
    """The box for the next stone: white = allowed, blue hatched = must cover."""
    allowed_q, must_q = r.box(r.allowed), r.box(r.must)
    blend_fill(img, allowed_q, WHITE, 0.4)
    hatch(img, must_q, BLUE, spacing=14, thickness=4)
    cv2.polylines(img, [_ipts(allowed_q)], True, WHITE, _t(img, 2), cv2.LINE_AA)
    cv2.polylines(img, [_ipts(must_q)], True, BLUE, _t(img, 2), cv2.LINE_AA)


def draw_ar(img, r: ZoneResult, check: PlacementCheck | None = None,
            px_per_unit: float = 1.0, unit: str = "px") -> np.ndarray:
    """Top-view overlay a craftsperson would see on the phone: the box for
    the next stone lies on top of both base stones, across the joint."""
    out = img.copy()
    allowed_q = r.box(r.allowed)
    draw_rule_lines(out, r)
    draw_zone(out, r)
    s = _k(out)
    for i, stone in enumerate((r.left, r.right)):
        x, y = stone.centroid
        label(out, str(i + 1), (x - 6 * s, y + 6 * s), scale=0.7)

    k = 1.0 / px_per_unit
    top = allowed_q[np.argmin(allowed_q[:, 1])]
    label(out, f"next stone: length {r.must.width * k:.0f}-{r.allowed.width * k:.0f} {unit},"
               f" depth {r.stone_depth.lo * k:.0f}-{r.stone_depth.hi * k:.0f} {unit}", (top[0] - 170 * s, top[1] - 34 * s))
    label(out, "blue = must cover   white = allowed", (top[0] - 140 * s, top[1] - 10 * s),
          scale=0.45)

    if check is not None:
        c = GREEN if check.ok else RED
        if check.stone is not None:
            cv2.drawContours(out, [check.stone.contour], -1, c, _t(out, 3), cv2.LINE_AA)
        mid = (r.depth.lo + r.depth.hi) / 2
        ends = r.to_image([check.span.lo, check.span.hi], [mid, mid])
        cv2.line(out, tuple(np.round(ends[0]).astype(int)), tuple(np.round(ends[1]).astype(int)),
                 c, _t(out, 5), cv2.LINE_AA)
        for e in ends:
            cv2.circle(out, tuple(np.round(e).astype(int)), _t(out, 9), c, cv2.FILLED)
        label(out, f"{check.message}  (stone 1 {check.cover_left:.0%},"
                   f" stone 2 {check.cover_right:.0%})", (12 * s, out.shape[0] - 14 * s), c)
    return out


def detection_panels(bgr, det: Detection) -> dict[str, np.ndarray]:
    """Full-resolution BGR images for each step of `detect_stones`."""
    size = (bgr.shape[1], bgr.shape[0])
    up = lambda im: cv2.resize(im, size, interpolation=cv2.INTER_NEAREST)
    gray3 = lambda im: cv2.cvtColor(up(im), cv2.COLOR_GRAY2BGR)

    markers = det.debug["markers"]
    seg = np.zeros((*markers.shape, 3), np.uint8)
    for label_id in range(2, int(markers.max()) + 1):
        seg[markers == label_id] = STONE_COLORS[(label_id - 2) % len(STONE_COLORS)]
    seg[markers == -1] = WHITE
    seg = cv2.addWeighted(det.debug["smooth"], 0.4, seg, 0.6, 0)

    return {
        "1 input": bgr,
        "2 edges (Canny)": gray3(det.debug["edges"]),
        "3 difference from ground": cv2.applyColorMap(up(det.debug["ground_distance"]),
                                                      cv2.COLORMAP_INFERNO),
        "4 stone mask": gray3(det.debug["mask"]),
        "5 watershed split": up(seg),
        "6 stones + boxes": draw_stones(bgr, det.stones, rotated=True),
    }


def grid(panels: dict[str, np.ndarray], cols=3, tile_width=480) -> np.ndarray:
    tiles = []
    for name, im in panels.items():
        s = tile_width / im.shape[1]
        t = cv2.resize(im, (tile_width, int(im.shape[0] * s)), interpolation=cv2.INTER_AREA)
        label(t, name, (8, 22), scale=0.6)
        tiles.append(t)
    h = max(t.shape[0] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, 0, cv2.BORDER_CONSTANT) for t in tiles]
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    return np.vstack(rows)
