"""Step 1 - find the outline of each stone in a single RGB frame.

Classic computer vision only, so it runs on any laptop with no training data:

1. smooth the frame (bilateral filter keeps stone edges sharp),
2. Canny edges - the "edge detection" view of the scene,
3. model the ground colour from the image border and mark every pixel that
   differs from it as "stone",
4. split touching stones with a distance-transform + watershed: each stone
   gets one seed in its thickest part, and the watershed floods outwards
   along the colour gradient until neighbouring stones meet at the joint.
   Stones joined by a narrow neck separate with a stricter seed threshold;
   stones that touch flush separate once the Canny edges are cut out of the
   mask (the joint between two stones shows up as an edge line). We try
   these and keep whichever finds the most stones, then merge back the
   weakest splits until the expected number of stones is left. A real joint
   is a sharp, dark line (the shadow in the gap); a cut through one stone
   is not.

Seeds can also be given by hand (one click per stone), which is the robust
mode for a live demo and also a plausible AR interaction ("tap each stone").
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class Stone:
    contour: np.ndarray            # (N, 1, 2) int32, full-resolution pixel coords
    area: float
    centroid: tuple[float, float]
    bbox: tuple[int, int, int, int]  # axis-aligned x, y, w, h
    min_rect: tuple                # cv2.minAreaRect, for a rotated box view


@dataclass
class DetectParams:
    work_width: int = 640          # frames are downscaled to this for speed
    border_frac: float = 0.06      # image border band used to sample the ground
    ground_thresh: float | None = None  # colour distance; None -> Otsu
    lightness_weight: float = 0.5  # < 1 makes shadows count less than colour
    canny_sigma: float = 0.33
    morph_frac: float = 0.016      # clean-up kernel, as a fraction of the width
    min_area_frac: float = 0.01    # ignore blobs smaller than 1% of the frame
    max_area_frac: float = 0.7
    max_stones: int = 6            # more seeds than this = over-segmented, rejected
    stones: int = 2                # expected base stones; extra splits are merged
    min_joint_score: float = 6.0   # a split must look at least this much like a joint
    seed_radius_px: int = 6


@dataclass
class Detection:
    stones: list[Stone]
    debug: dict[str, np.ndarray] = field(default_factory=dict)  # work-res images
    scale: float = 1.0             # work-res / full-res


def auto_canny(gray: np.ndarray, sigma: float = 0.33) -> np.ndarray:
    """Canny with thresholds picked from the median intensity."""
    median = float(np.median(gray))
    lower = int(max(0, (1.0 - sigma) * median))
    upper = int(min(255, (1.0 + sigma) * median))
    return cv2.Canny(gray, lower, upper)


def ground_distance(bgr: np.ndarray, border_frac: float,
                    lightness_weight: float) -> np.ndarray:
    """Per-pixel Lab distance to the median colour of the image border."""
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    h, w = lab.shape[:2]
    b = max(2, int(border_frac * min(h, w)))
    border = np.concatenate([
        lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3),
        lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3),
    ])
    ground = np.median(border, axis=0)
    diff = lab - ground
    diff[..., 0] *= lightness_weight
    dist = np.linalg.norm(diff, axis=2)
    return cv2.normalize(dist, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, contours, -1, 255, cv2.FILLED)
    return filled


def _remove_small(mask: np.ndarray, min_area: float) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = np.zeros_like(mask)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            keep[labels == i] = 255
    return keep


def _cores_from_distance(mask: np.ndarray, frac: float) -> tuple[int, np.ndarray]:
    """One seed per 'thick part' of each blob, normalised per blob so a
    small stone is not lost next to a big one."""
    dt = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    n, labels = cv2.connectedComponents(mask)
    cores = np.zeros(mask.shape, np.uint8)
    for i in range(1, n):
        region = labels == i
        peak = dt[region].max()
        cores[region & (dt > frac * peak)] = 255
    return cv2.connectedComponents(cores)


def _watershed(smooth: np.ndarray, sure_bg: np.ndarray,
               seed_labels: np.ndarray) -> np.ndarray:
    markers = np.zeros(smooth.shape[:2], np.int32)
    markers[sure_bg > 0] = 1
    markers[seed_labels > 0] = seed_labels[seed_labels > 0] + 1  # stones: 2..n+1
    cv2.watershed(smooth, markers)
    return markers


def _joint_score(markers, a, b, g, grad) -> float | None:
    """How much the line between segments a and b looks like a joint: a
    sharp, dark line (the shadow in the gap between two stones). A cut
    through one stone is neither. None if a and b do not touch."""
    grow = lambda l: cv2.dilate(np.uint8(markers == l), None, iterations=2) > 0
    line = grow(a) & grow(b) & (markers == -1)
    if line.sum() < 10:
        return None
    inner = (cv2.erode(np.uint8(markers == a), None, iterations=4)
             | cv2.erode(np.uint8(markers == b), None, iterations=4)) > 0
    sharpness = np.median(grad[line]) / (np.median(grad[inner]) + 1.0)
    darkness = max(0.0, float(np.median(g[inner]) - np.median(g[line])))
    return float(sharpness * (1 + darkness / 20))


def _merge_weak_splits(markers: np.ndarray, gray: np.ndarray,
                       target: int, min_score: float) -> None:
    """Undo over-segmentation in place: keep merging the two neighbouring
    segments whose shared line looks least like a joint, until at most
    `target` segments are left and every remaining line scores >= min_score."""
    g = gray.astype(np.float32)
    grad = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    while True:
        labels = [l for l in range(2, int(markers.max()) + 1) if (markers == l).any()]
        pairs = [(_joint_score(markers, a, b, g, grad), a, b)
                 for i, a in enumerate(labels) for b in labels[i + 1:]]
        pairs = [p for p in pairs if p[0] is not None]
        if not pairs:
            return
        score, a, b = min(pairs)
        if len(labels) <= target and score >= min_score:
            return
        line = (cv2.dilate(np.uint8(markers == a), None, iterations=2) > 0) & (markers == -1)
        markers[markers == b] = a
        markers[line & (cv2.dilate(np.uint8(markers == a), None, iterations=1) > 0)] = a


def _to_stone(contour: np.ndarray, scale: float) -> Stone:
    """Work-resolution contour -> Stone in full-resolution pixels."""
    c = np.round(contour.astype(np.float32) / scale).astype(np.int32)
    m = cv2.moments(c)
    return Stone(contour=c, area=cv2.contourArea(c),
                 centroid=(m["m10"] / m["m00"], m["m01"] / m["m00"]),
                 bbox=cv2.boundingRect(c), min_rect=cv2.minAreaRect(c))


def detect_stones(bgr: np.ndarray, params: DetectParams | None = None,
                  seeds: list[tuple[float, float]] | None = None) -> Detection:
    """Return the stones in `bgr`, largest first. `seeds` are optional
    (x, y) full-resolution points, one per stone."""
    p = params or DetectParams()
    h0, w0 = bgr.shape[:2]
    scale = min(1.0, p.work_width / w0)
    img = cv2.resize(bgr, None, fx=scale, fy=scale,
                     interpolation=cv2.INTER_AREA) if scale < 1 else bgr.copy()
    h, w = img.shape[:2]

    smooth = cv2.bilateralFilter(img, 9, 50, 50)
    gray = cv2.cvtColor(smooth, cv2.COLOR_BGR2GRAY)
    edges = auto_canny(gray, p.canny_sigma)

    dist = ground_distance(smooth, p.border_frac, p.lightness_weight)
    if p.ground_thresh is None:
        _, fg = cv2.threshold(dist, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        _, fg = cv2.threshold(dist, p.ground_thresh, 255, cv2.THRESH_BINARY)
    k = max(3, int(p.morph_frac * w) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel)
    fg = _fill_holes(fg)
    fg = _remove_small(fg, p.min_area_frac * h * w)

    sure_bg = cv2.bitwise_not(cv2.dilate(fg, kernel, iterations=2))

    if seeds:
        seed_labels = np.zeros((h, w), np.int32)
        for i, (x, y) in enumerate(seeds):
            cv2.circle(seed_labels, (int(x * scale), int(y * scale)),
                       p.seed_radius_px, i + 1, cv2.FILLED)
        markers = _watershed(smooth, sure_bg, seed_labels)
    else:
        # Keep the seeding that separates the most stones (ties: the first,
        # i.e. the gentlest). Slivers left by the edge cut are dropped so
        # they do not become seeds of their own. (No morphological opening
        # here: its dilation would bridge the thin cut again.)
        edge_cut = cv2.bitwise_and(fg, cv2.bitwise_not(cv2.dilate(edges, None)))
        edge_cut = _remove_small(edge_cut, p.min_area_frac * h * w)
        best = None
        for src, frac in itertools.product((fg, edge_cut), (0.5, 0.65, 0.8)):
            n, labels = _cores_from_distance(src, frac)
            if n - 1 <= p.max_stones and (best is None or n > best[0]):
                best = (n, labels, src)
        _, seed_labels, cut = best
        markers = _watershed(smooth, sure_bg, seed_labels)
        _merge_weak_splits(markers, gray, p.stones, p.min_joint_score)

    stones = []
    min_area = p.min_area_frac * h * w
    max_area = p.max_area_frac * h * w
    for label in range(2, int(markers.max()) + 1):
        # The watershed may flood into the uncertain band around the mask
        # (e.g. a contact shadow); keep only what the mask calls stone.
        region = cv2.bitwise_and(np.uint8(markers == label) * 255, fg)
        region = cv2.morphologyEx(region, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue
        c = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(c)
        if not min_area <= area <= max_area:
            continue
        stones.append(_to_stone(c, scale))
    stones.sort(key=lambda s: s.area, reverse=True)

    debug = {"smooth": smooth, "edges": edges, "ground_distance": dist,
             "mask": fg, "markers": markers}
    if not seeds:
        debug["split_mask"] = cut
    return Detection(stones=stones, debug=debug, scale=scale)


def find_homography(src: np.ndarray, dst: np.ndarray,
                    min_inliers: int = 25) -> np.ndarray:
    """3x3 homography mapping pixels of photo `src` onto photo `dst` (handheld
    phone: it moved, turned or zoomed between the shots). SIFT features on
    the stone texture are matched and the homography is fitted with RANSAC;
    a newly placed stone has no partner features and drops out as outliers."""
    def feats(im):
        s = min(1.0, 1200 / max(im.shape[:2]))
        g = cv2.cvtColor(cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA),
                         cv2.COLOR_BGR2GRAY)
        kp, des = cv2.SIFT_create(4000).detectAndCompute(g, None)
        return np.float32([k.pt for k in kp]) / s, des

    ps, ds = feats(src)
    pd, dd = feats(dst)
    if ds is None or dd is None:
        raise RuntimeError("no texture to align the photos")
    matches = cv2.BFMatcher().knnMatch(ds, dd, k=2)
    good = [m for m, n in (x for x in matches if len(x) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < min_inliers:
        raise RuntimeError(f"photos do not match ({len(good)} matches)")
    H, inl = cv2.findHomography(ps[[m.queryIdx for m in good]], pd[[m.trainIdx for m in good]],
                                cv2.RANSAC, 8.0)
    if H is None or inl.sum() < min_inliers:
        raise RuntimeError("photos could not be aligned")
    return H


def align_to(before: np.ndarray, after: np.ndarray,
             min_inliers: int = 25) -> tuple[np.ndarray, np.ndarray]:
    """Warp `after` into the view of `before`. Returns (warped after, valid mask)."""
    H = find_homography(after, before, min_inliers)
    size = (before.shape[1], before.shape[0])
    warped = cv2.warpPerspective(after, H, size)
    valid = cv2.warpPerspective(np.full(after.shape[:2], 255, np.uint8), H, size)
    return warped, valid


def stone_from_points(points, hull: bool = True) -> Stone:
    """Stone from an outline given as points: their convex hull (for a few
    clicks) or, with hull=False, the points as they are (a full contour)."""
    pts = np.asarray(points, np.float32).reshape(-1, 1, 2)
    return _to_stone(cv2.convexHull(pts) if hull else pts, 1.0)


def detect_placed_stone(before: np.ndarray, after: np.ndarray,
                        params: DetectParams | None = None,
                        valid: np.ndarray | None = None) -> Stone | None:
    """The new stone is whatever changed between the photo before and after
    placing it (from above it hides the joint, so it cannot be told apart
    from the base stones in one photo). `after` must be in the same view as
    `before` (see align_to); `valid` masks out what the after photo did not
    cover."""
    p = params or DetectParams()
    scale = min(1.0, p.work_width / before.shape[1])
    small = lambda im: cv2.GaussianBlur(
        cv2.resize(im, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), (5, 5), 0)
    a = cv2.cvtColor(small(before), cv2.COLOR_BGR2LAB).astype(np.float32)
    b = cv2.cvtColor(small(after), cv2.COLOR_BGR2LAB).astype(np.float32)
    d = b - a
    d[..., 0] *= p.lightness_weight     # a shadow changes brightness, not colour
    diff = np.linalg.norm(d, axis=2)
    if valid is not None:
        v = cv2.resize(valid, (diff.shape[1], diff.shape[0]), interpolation=cv2.INTER_NEAREST)
        diff[cv2.erode(v, None, iterations=3) == 0] = 0
    diff = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    h, w = mask.shape
    k = max(3, int(p.morph_frac * w) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = _fill_holes(cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    if cv2.contourArea(c) < p.min_area_frac * h * w:
        return None
    return _to_stone(c, scale)
