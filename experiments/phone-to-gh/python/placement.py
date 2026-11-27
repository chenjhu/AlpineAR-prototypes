"""After the new stone is laid on the wall: is it in the zone? (MESSAGES.md
messages 7 and 8, added 2026-11-24.)

The person photographs the wall again, with the QR marker where it was. The
new stone lies on top of the two base stones, so from above the three touch
and the usual detection cannot tell them apart. So the new stone is found
as what CHANGED since the layer photo:

1. Line the layer photo up with the new one. Texture points (SIFT) on the
   base stones and the marker, matched between the two photos, give the
   map (a homography; the stones' tops are near one plane). If too few
   points match, the marker alone gives it.
2. Compare the two, pixel by pixel. Changed = the texture is different
   (low correlation in a small window) or the colour is clearly different.
   A shadow keeps the texture and the colour's hue and only darkens, so it
   does not count.
3. The changed region that holds the tap (or else lies most in the zone) is
   the new stone. Its outline goes into the marker's cm frame.
4. The rule, in the wall's own frame from the zone (message 4's `wall_cm`):
   along the wall it covers 1/4 to 3/4 of each base stone, measured from
   the joint line (the quarter rule); across the wall its faces stay in line
   with the wall's within FACE_TOL_CM, and a stone deeper than the wall sits
   in its middle. If not, how far to move it.
"""
import time

import cv2
import numpy as np

ALONG_TOL_CM = 1.5    # the measurement is off by ~1 cm (real-scale test): allow that much along
FACE_TOL_CM = 2.5     # the rule: faces in line within 2.5 cm
SEEN_TOL_CM = 1.0     # and the measurement's ~1 cm on top of it, across
WORK_W = 640          # the comparison runs at this width
MIN_MATCHES = 25      # fewer SIFT matches than this: line up by the marker alone
NCC_WIN = 9           # the correlation window, work pixels
TEXTURED = 5.0        # grey std in the window above this: there is texture to compare
RICH = 12.0           # ... above this: stone texture (paper grain stays below)
NCC_CHANGED = 0.35    # correlation below this: other texture, so changed
COLOR_CHANGED = 22.0  # Lab distance above this (after the light is matched): changed


def _px(pts):
    return [[int(round(x)), int(round(y))] for x, y in pts]


def _cm(pts):
    return [[round(float(x), 1), round(float(y), 1)] for x, y in pts]


def _gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def register(layer, placed, mk0, mk1, region0):
    """Homography layer px -> placed px. `region0`: where to look for points in
    the layer photo (the base stones and the marker). Returns (H, how), H None
    if neither the texture nor the marker (mk1 None) gives it."""
    sift = cv2.SIFT_create(5000)
    k0, d0 = sift.detectAndCompute(_gray(layer), region0)
    k1, d1 = sift.detectAndCompute(_gray(placed), None)
    if d0 is not None and d1 is not None and len(k0) >= MIN_MATCHES and len(k1) >= MIN_MATCHES:
        pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(d0, d1, k=2)
        good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
        if len(good) >= MIN_MATCHES:
            p0 = np.float32([k0[m.queryIdx].pt for m in good])
            p1 = np.float32([k1[m.trainIdx].pt for m in good])
            H, inl = cv2.findHomography(p0, p1, cv2.RANSAC, 3.0)
            if H is not None and int(inl.sum()) >= MIN_MATCHES:
                return H, "texture (%d points)" % int(inl.sum())
    if mk1 is None:
        return None, "too few points match the layer photo"
    return np.linalg.inv(mk1.paper_h) @ mk0.paper_h, "marker"


class Seen:
    """The layer photo's marker, carried into the placed photo by the
    homography H (layer px -> placed px): when the placed photo shows no
    marker (cut off, too small), its cm come from the layer's."""

    def __init__(self, mk0, H, shape0):
        self.mk0, self.H, self.Hi, self.shape0 = mk0, H, np.linalg.inv(H), shape0

    def _map(self, pts, M):
        return cv2.perspectiveTransform(np.asarray(pts, np.float64).reshape(-1, 1, 2), M).reshape(-1, 2)

    def to_cm(self, pts):
        return self.mk0.to_cm(self._map(pts, self.Hi))

    def to_px(self, pts):
        return self._map(self.mk0.to_px(pts), self.H)

    def px_per_cm(self):
        c = self.to_px([[7.4, 7.4], [8.4, 7.4]])
        return float(np.linalg.norm(c[1] - c[0]))

    def square_mask(self, shape, margin_cm=0.5):
        m = self.mk0.square_mask(self.shape0, margin_cm)
        return cv2.warpPerspective(m, self.H, (shape[1], shape[0]), flags=cv2.INTER_NEAREST)


def _window_stats(a, b, k):
    """Local means, stds and correlation of a and b in k x k windows."""
    blur = lambda x: cv2.boxFilter(x, -1, (k, k))  # noqa: E731
    ma, mb = blur(a), blur(b)
    va = np.maximum(blur(a * a) - ma * ma, 0)
    vb = np.maximum(blur(b * b) - mb * mb, 0)
    cov = blur(a * b) - ma * mb
    sa, sb = np.sqrt(va), np.sqrt(vb)
    return sa, sb, cov / (sa * sb + 1e-6)


def changed_mask(layer_warped, placed, valid):
    """Where the placed photo differs from the (lined-up) layer photo, at
    work size. Shadows (darker, same texture and hue) do not count."""
    a, b = layer_warped.astype(np.float32), placed.astype(np.float32)
    # The light may differ between the two photos: match each colour channel.
    v = valid > 0
    for c in range(3):
        ma, mb = np.median(a[..., c][v]), np.median(b[..., c][v])
        a[..., c] *= mb / max(ma, 1.0)
    a8, b8 = np.clip(a, 0, 255).astype(np.uint8), np.clip(b, 0, 255).astype(np.uint8)
    ga = cv2.GaussianBlur(_gray(a8).astype(np.float32), (0, 0), 1.0)
    gb = cv2.GaussianBlur(_gray(b8).astype(np.float32), (0, 0), 1.0)
    sa, sb, ncc = _window_stats(ga, gb, NCC_WIN)
    textured = (sa > TEXTURED) | (sb > TEXTURED)
    la = cv2.cvtColor(cv2.GaussianBlur(a8, (0, 0), 2.0), cv2.COLOR_BGR2LAB).astype(np.float32)
    lb = cv2.cvtColor(cv2.GaussianBlur(b8, (0, 0), 2.0), cv2.COLOR_BGR2LAB).astype(np.float32)
    dist = np.linalg.norm(la - lb, axis=2)
    hue = np.linalg.norm(la[..., 1:] - lb[..., 1:], axis=2)
    darker = (lb[..., 0] < la[..., 0]) & (lb[..., 0] > 0.2 * la[..., 0])   # a small stone close to the camera casts a deep shadow
    # A shadow: darker, the same hue, and where the new photo shows stone
    # texture, the same texture (a grey stone on white paper is darker with
    # the same hue too, but its texture is new).
    shadow = darker & (hue < 8) & ((sb < RICH) | (ncc > 0.6))
    changed = ((textured & (ncc < NCC_CHANGED)) | (dist > COLOR_CHANGED)) & ~shadow & v
    return changed.astype(np.uint8) * 255


def find_new_stone(layer, placed, H, mk1, zone_px, tap=None, stone_cm=30.0):
    """The new stone in the placed photo: (outline px (N, 2) or None, info).
    H: layer px -> placed px (register); mk1: the placed photo's marker (or a Seen).
    stone_cm: about how deep the new stone is (the zone's depth range), which
    sets the smallest change that counts and the clean-up: the test pebbles
    are 5 cm, real stones 30 cm (phone test 2026-11-25: a 12 cm2 pebble fell
    under a fixed 30 cm2 and a shadow at the photo's top was taken instead).
    Only a change that reaches into the zone (or holds the tap) counts."""
    h, w = placed.shape[:2]
    k = WORK_W / w
    S = np.diag([k, k, 1.0])
    size = (WORK_W, round(h * k))
    small = cv2.resize(placed, size, interpolation=cv2.INTER_AREA)
    warped = cv2.warpPerspective(layer, S @ H, size, flags=cv2.INTER_LINEAR)
    valid = cv2.warpPerspective(np.full(layer.shape[:2], 255, np.uint8), S @ H, size, flags=cv2.INTER_NEAREST)
    valid = cv2.erode(valid, np.ones((5, 5), np.uint8))
    # the marker's paper is not the new stone (and may have been nudged)
    paper = cv2.resize(mk1.square_mask(placed.shape, margin_cm=1.0), size, interpolation=cv2.INTER_NEAREST)
    valid[paper > 0] = 0
    ch = changed_mask(warped, small, valid)
    ppc = mk1.px_per_cm() * k
    ch = cv2.morphologyEx(ch, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    r = max(3, int(round(min(1.5, 0.15 * stone_cm) * ppc)) | 1)
    ch = cv2.morphologyEx(ch, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r)))
    cnts, _ = cv2.findContours(ch, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    min_cm2 = min(30.0, 0.25 * stone_cm * stone_cm)
    cnts = [c for c in cnts if cv2.contourArea(c) >= min_cm2 * ppc * ppc]
    if not cnts:
        return None, "nothing changed"
    zone = np.zeros(size[::-1], np.uint8)
    if zone_px is not None:
        cv2.fillPoly(zone, [np.int32(np.round(np.float32(zone_px) * k))], 255)

    def score(c):
        m = np.zeros(size[::-1], np.uint8)
        cv2.drawContours(m, [c], -1, 255, cv2.FILLED)
        if tap is not None:
            tx, ty = int(round(tap[0] * k)), int(round(tap[1] * k))
            if 0 <= ty < size[1] and 0 <= tx < size[0] and m[ty, tx]:
                return 1e12
        return float(((m > 0) & (zone > 0)).sum()) + 1e-3 * cv2.contourArea(c)
    best = max(cnts, key=score)
    if score(best) < 1:   # nothing reaches into the zone (a hand, a shadow elsewhere)
        return None, "nothing changed in the zone"
    filled = np.zeros(size[::-1], np.uint8)
    cv2.drawContours(filled, [best], -1, 255, cv2.FILLED)   # holes filled
    # smooth the rim a little (the comparison is noisy at the stone's edge)
    filled = cv2.morphologyEx(filled, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r)))
    cnts, _ = cv2.findContours(filled, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None, "nothing changed"
    return max(cnts, key=cv2.contourArea).reshape(-1, 2).astype(np.float64) / k, ""


FIT_MIN_CHANGED = 0.3   # the fitted outline must lie at least this much on changed pixels


def _ground_like(img):
    """Pixels that look like the bare ground: below the Otsu threshold of the
    distance to the photo border's colour, as the stone detection sees it
    (stone_detect.ground_distance). (A spread taken from the border itself
    took the stones for ground too: the border holds the paper and a grey
    table, 2026-11-27.)"""
    from stone_detect import ground_distance
    gd = ground_distance(cv2.bilateralFilter(img, 9, 50, 50), 0.06, 0.5)
    t, _ = cv2.threshold(gd, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return gd <= t


def fit_known_outline(layer, placed, H, mk1, outline_cm, zone_px, stone_cm=30.0):
    """The checked stone's own outline (`outline_cm`, from its candidate photo:
    the person lays the stone they checked last) put where it lies in the
    placed photo: of all turns (every 5 degrees, also turned over) and shifts
    near the zone, the one that covers the most of what changed since the
    layer photo and the least bare ground. Its size is the stone's, not that
    of what changed: when its texture and picture are not found, what changed
    was only part of it (a grey stone on grey base stones; phone test
    2026-11-27, a 4.5 x 2.1 cm stone came out 2.1 x 2.2). Returns (outline px
    or None, info)."""
    h, w = placed.shape[:2]
    k = WORK_W / w
    S = np.diag([k, k, 1.0])
    size = (WORK_W, round(h * k))
    small = cv2.resize(placed, size, interpolation=cv2.INTER_AREA)
    warped = cv2.warpPerspective(layer, S @ H, size, flags=cv2.INTER_LINEAR)
    valid = cv2.warpPerspective(np.full(layer.shape[:2], 255, np.uint8), S @ H, size, flags=cv2.INTER_NEAREST)
    valid = cv2.erode(valid, np.ones((5, 5), np.uint8))
    paper = cv2.resize(mk1.square_mask(placed.shape, margin_cm=1.0), size, interpolation=cv2.INTER_NEAREST)
    valid[paper > 0] = 0
    ch = changed_mask(warped, small, valid) > 0
    ground = _ground_like(small) & (valid > 0)
    F = ch.astype(np.float32) - 2.0 * ground.astype(np.float32)
    # where the stone's middle may be: within a stone's size of the zone
    near = np.zeros(size[::-1], np.uint8)
    zone = np.float32(zone_px) * k
    cv2.fillPoly(near, [np.int32(np.round(zone))], 255)
    ppc = mk1.px_per_cm() * k
    reach = max(3, int(round(0.5 * stone_cm * ppc)))
    near = cv2.dilate(near, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * reach + 1, 2 * reach + 1)))
    oc = np.float32(outline_cm)
    oc = oc - oc.mean(axis=0)
    mid_cm = mk1.to_cm(np.float32(zone_px)).mean(axis=0)
    best = None
    for flip in (1.0, -1.0):
        for deg in range(0, 360, 5):
            a = np.deg2rad(deg)
            R = np.float32([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
            pts = mk1.to_px((oc * [flip, 1.0]) @ R.T + mid_cm) * k
            lo = np.floor(pts.min(axis=0)).astype(int)
            kw, kh = (np.ceil(pts.max(axis=0)).astype(int) - lo + 1)
            kern = np.zeros((kh, kw), np.uint8)
            cv2.fillPoly(kern, [np.int32(np.round(pts - lo))], 1)
            area = float(kern.sum())
            if area < 4:
                continue
            anchor = (kw // 2, kh // 2)
            resp = cv2.filter2D(F, -1, kern.astype(np.float32), anchor=anchor, borderType=cv2.BORDER_CONSTANT)
            resp[near == 0] = -1e9
            y, x = np.unravel_index(int(np.argmax(resp)), resp.shape)
            if best is None or resp[y, x] > best[0]:
                best = (float(resp[y, x]), pts - lo - anchor + [x, y], kern, (x, y), anchor, area)
    if best is None:
        return None, "the checked stone's outline is empty"
    _, pts, kern, (x, y), anchor, area = best
    m = np.zeros(size[::-1], np.uint8)
    cv2.fillPoly(m, [np.int32(np.round(pts))], 1)
    on_changed = float((m.astype(bool) & ch).sum()) / max(float(m.sum()), 1.0)
    if on_changed < FIT_MIN_CHANGED:
        return None, "its outline does not fit what changed (%.0f %% on it)" % (100 * on_changed)
    return pts / k, "its outline from the stone stock fitted to what changed (%.0f %% on it)" % (100 * on_changed)


def tolerances(stone_cm):
    """(along, face, seen) in cm: the constants above for wall stones, smaller
    for small stones (the measurement's error shrinks with them: a 1.5 cm
    tolerance on a 3 cm test pebble let it reach right across, 2026-11-25)."""
    return (min(ALONG_TOL_CM, 0.06 * stone_cm), min(FACE_TOL_CM, 0.1 * stone_cm),
            min(SEEN_TOL_CM, 0.04 * stone_cm))


MIN_STONE_POINTS = 8   # texture points of the checked stone that must agree on where it lies


def locate_known_stone(cand, cand_outline, placed, ppc_cand, ppc_placed, near=None, radius_px=None):
    """Find the stone that was checked at the stone stock (message 5: `cand`,
    its outline `cand_outline` in that photo's pixels) in the photo after
    placing, by its own texture: SIFT points on the stone in the candidate
    photo matched to points in the placed photo near `near` (the tap, or the
    zone's middle) within `radius_px`, and one turn + shift + scale that most
    of them agree on (RANSAC). Its known outline is then carried over. The
    scale must be the two photos' px-per-cm ratio (+-25 %), so a match on a
    base stone of the same rock does not pass. Returns (outline px or None, info).
    (Idea from the phone test 2026-11-25: the new stone is known, it only has
    to be found; finding it as 'what changed' took in its shadow and nudged
    base stones.)"""
    outline = np.float32(cand_outline).reshape(-1, 2)
    m0 = np.zeros(cand.shape[:2], np.uint8)
    cv2.fillPoly(m0, [np.int32(outline)], 255)
    m0 = cv2.erode(m0, np.ones((5, 5), np.uint8))       # not its rim (the ground shows there)
    m1 = None
    if near is not None and radius_px:
        m1 = np.zeros(placed.shape[:2], np.uint8)
        cv2.circle(m1, (int(near[0]), int(near[1])), int(radius_px), 255, cv2.FILLED)
    sift = cv2.SIFT_create(3000, contrastThreshold=0.02)
    k0, d0 = sift.detectAndCompute(_gray(cand), m0)
    k1, d1 = sift.detectAndCompute(_gray(placed), m1)
    if d0 is None or d1 is None or len(k0) < MIN_STONE_POINTS or len(k1) < MIN_STONE_POINTS:
        return None, "too little texture on the stone"
    pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(d0, d1, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.8 * p[1].distance]
    if len(good) < MIN_STONE_POINTS:
        return None, "the stone's texture is not found (%d points)" % len(good)
    p0 = np.float32([k0[m.queryIdx].pt for m in good])
    p1 = np.float32([k1[m.trainIdx].pt for m in good])
    A, inl = cv2.estimateAffinePartial2D(p0, p1, method=cv2.RANSAC, ransacReprojThreshold=4.0,
                                         maxIters=5000, confidence=0.995)
    if A is None or int(inl.sum()) < MIN_STONE_POINTS:
        return None, "the stone's texture is not found (%d points agree)" % (0 if inl is None else int(inl.sum()))
    scale = float(np.hypot(A[0, 0], A[1, 0]))
    want = ppc_placed / ppc_cand
    if not 0.75 * want <= scale <= 1.25 * want:
        return None, "the stone's texture matched at the wrong size (x%.2f, want x%.2f)" % (scale, want)
    moved = outline @ A[:, :2].T + A[:, 2]
    return moved, "found by its own texture (%d points)" % int(inl.sum())


MATCH_MIN = 0.45      # the whole-stone match must correlate at least this well


def _rotate(img, angle, size, border):
    """`img` turned by `angle` degrees about its middle, on a size x size canvas."""
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    M[:, 2] += (size / 2 - w / 2, size / 2 - h / 2)
    return cv2.warpAffine(img, M, (size, size), flags=cv2.INTER_LINEAR, borderValue=border), M


def match_known_stone(cand, cand_outline, placed, ppc_cand, ppc_placed, near, radius_px, before=None,
                      zone_px=None, zone_margin_px=0):
    """The stone that fitted at the stone stock, found in the photo after
    placing by its WHOLE top face: its picture from the candidate photo,
    scaled to this photo's px per cm and turned in steps, slid over the area
    around `near` (normalised correlation, only the stone's own pixels). Steadier
    than texture points on a small stone (a 5 cm pebble gave SIFT 1-8 points,
    phone test 2026-11-27). `before`: the layer photo lined up with this one;
    a place that matches as well there is a base stone of the same rock, not
    the new one (4 of 8 phone photos went to a base stone without this).
    `zone_px`: the allowed zone in this photo; the stone's middle must lie in it
    (+ zone_margin_px), as a laid stone overlaps it (2 of 8 went to bare paper).
    Returns (outline px or None, info)."""
    outline = np.float32(cand_outline).reshape(-1, 2)
    x, y, w, h = cv2.boundingRect(np.int32(outline))
    scale = ppc_placed / ppc_cand
    g0 = cv2.GaussianBlur(_gray(cand), (0, 0), 1.0)
    crop = g0[y:y + h, x:x + w]
    m0 = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m0, [np.int32(outline - [x, y])], 255)
    tw, th = max(4, round(w * scale)), max(4, round(h * scale))
    tmpl = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_AREA)
    mask = cv2.erode(cv2.resize(m0, (tw, th), interpolation=cv2.INTER_NEAREST), np.ones((3, 3), np.uint8))
    if mask.sum() < 255 * 50:
        return None, "the stone is too small in the photo"
    size = int(np.ceil(np.hypot(tw, th))) + 2
    g1 = cv2.GaussianBlur(_gray(placed), (0, 0), 1.0)
    H1, W1 = g1.shape
    cx, cy = float(near[0]), float(near[1])
    r = radius_px + size / 2
    x0, y0 = int(max(0, cx - r)), int(max(0, cy - r))
    x1, y1 = int(min(W1, cx + r)), int(min(H1, cy + r))
    win = g1[y0:y1, x0:x1]
    win0 = None
    if before is not None:
        win0 = cv2.GaussianBlur(_gray(before), (0, 0), 1.0)[y0:y1, x0:x1]
    if win.shape[0] <= size or win.shape[1] <= size:
        return None, "the zone is too near the photo's edge"
    # where the template's middle may land: within radius_px of `near`
    yy, xx = np.mgrid[0:win.shape[0] - size + 1, 0:win.shape[1] - size + 1]
    allowed = (xx + x0 + size / 2 - cx) ** 2 + (yy + y0 + size / 2 - cy) ** 2 <= radius_px ** 2
    if zone_px is not None:
        zm = np.zeros(g1.shape, np.uint8)
        cv2.fillPoly(zm, [np.int32(np.round(zone_px))], 255)
        if zone_margin_px > 0:
            k = int(2 * zone_margin_px) | 1
            zm = cv2.dilate(zm, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        cxs = np.clip((xx + x0 + size // 2).astype(int), 0, W1 - 1)
        cys = np.clip((yy + y0 + size // 2).astype(int), 0, H1 - 1)
        allowed &= zm[cys, cxs] > 0

    def best_at(angle):
        t, M = _rotate(tmpl, angle, size, 0)
        m, _ = _rotate(mask, angle, size, 0)
        m = np.uint8(m > 127) * 255
        res = cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED, mask=m)
        res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
        score = res.copy()
        if win0 is not None:
            # what was there before matching as well counts against it
            res0 = np.nan_to_num(cv2.matchTemplate(win0, t, cv2.TM_CCOEFF_NORMED, mask=m), nan=0.0, posinf=0.0, neginf=0.0)
            score = res - np.maximum(res0, 0)
        score[~allowed] = -2
        score[res < MATCH_MIN] = -2
        i = int(np.argmax(score))
        return float(score.flat[i]), divmod(i, res.shape[1]), M, float(res.flat[i])

    best = max(((best_at(a), a) for a in range(0, 360, 10)), key=lambda t: t[0][0])
    (score, loc, M, corr), angle = best
    for a in np.arange(angle - 8, angle + 9, 2):
        cand_best = best_at(float(a))
        if cand_best[0] > score:
            (score, loc, M, corr), angle = cand_best, float(a)
    if score < (0.2 if win0 is not None else MATCH_MIN):
        return None, "the stone's picture is not found (best %.2f)" % score
    (ty, tx) = loc
    pts = (outline - [x, y]) * scale                       # in the scaled crop
    pts = pts @ M[:, :2].T + M[:, 2]                       # turned onto the canvas
    pts = pts + [tx + x0, ty + y0]                         # where the canvas lies in the photo
    return pts, "found by its whole picture (match %.2f, %.2f better than before placing, turned %d deg)" % (
        corr, score, round(angle) % 360)


def known_stone_at_tap(cand_outline_cm, along_cm, tap_cm, wall):
    """The checked stone's outline (cm, from the stone stock) put where the
    person tapped it, turned the way the fit check said it goes: the side that
    is `along_cm` long along the wall. For when its texture cannot be matched
    (laid another face up). Its outline in cm, the marker's frame."""
    pts = np.asarray(cand_outline_cm, np.float64)
    (cx, cy), (a, b), ang = cv2.minAreaRect(np.float32(pts))
    side = np.array([np.cos(np.radians(ang)), np.sin(np.radians(ang))])   # direction of side a
    if along_cm is not None and abs(b - along_cm) < abs(a - along_cm):
        side = np.array([-side[1], side[0]])                               # side b goes along
    u = np.asarray(wall["u"], np.float64)
    turn = np.arctan2(u[1], u[0]) - np.arctan2(side[1], side[0])
    R = np.array([[np.cos(turn), -np.sin(turn)], [np.sin(turn), np.cos(turn)]])
    return (pts - [cx, cy]) @ R.T + np.asarray(tap_cm, np.float64)


def check(outline_cm, wall, stone_cm=30.0):
    """The rule (module docstring) for the stone's outline in cm against the
    wall frame `wall` (message 4's wall_cm). Returns (result, along_shift,
    across_shift, info): result "ok" or "move"; the shifts (cm, along u and
    across n) that put it right, 0 where it is right already."""
    p = np.asarray(outline_cm, np.float64) - wall["origin"]
    t, s = p @ np.asarray(wall["u"]), p @ np.asarray(wall["n"])
    J, x, y, f = wall["joint"], wall["x"], wall["y"], wall.get("fraction", 0.25)
    c0, c1, e0, e1 = t.min(), t.max(), s.min(), s.max()
    d0, d1 = wall["depth"]
    tol, face_tol, seen_tol = tolerances(stone_cm)
    # along: shifts that keep f <= cover <= 1-f on both base stones (with the tolerance)
    s_lo = max(J - c0 - (1 - f) * x - tol, J + f * y - tol - c1)
    s_hi = min(J - c0 - f * x + tol, J + (1 - f) * y + tol - c1)
    if wall.get("start") is not None:
        # Next to a laid stone (rule_of_thirds.compute_zone_next_to): its left end
        # touches the laid stone's end `start` (within the tolerance), its right end
        # covers f .. 1-f of C as above; x is what was left of B.
        S = wall["start"]
        s_lo = max(S - tol - c0, J + f * y - tol - c1)
        s_hi = min(S + tol - c0, J + (1 - f) * y + tol - c1)
    # across: faces in line, or a deeper stone in the middle
    ft = face_tol + seen_tol
    if e1 - e0 <= d1 - d0 + 2 * face_tol:
        t_lo, t_hi = d0 - ft - e0, d1 + ft - e1
    else:
        mid = 0.5 * (d0 + d1) - 0.5 * (e0 + e1)
        t_lo, t_hi = mid - ft, mid + ft
    info = {"cover": [round(float((J - c0) / x), 2), round(float((c1 - J) / y), 2)],
            "length_cm": round(float(c1 - c0), 1), "depth_cm": round(float(e1 - e0), 1),
            "shift_along_cm": [round(float(s_lo), 1), round(float(s_hi), 1)],
            "shift_across_cm": [round(float(t_lo), 1), round(float(t_hi), 1)]}
    if s_lo > s_hi:
        return "wrong_size", 0.0, 0.0, info
    move_u = 0.0 if s_lo <= 0 <= s_hi else 0.5 * (s_lo + s_hi)
    move_n = 0.0 if t_lo <= 0 <= t_hi else 0.5 * (t_lo + t_hi)
    return ("ok" if move_u == 0 and move_n == 0 else "move"), move_u, move_n, info


def placement_message(placed, layer, mk1, mk0, layer_outlines, zone, photo_ts, layer_ts, tap=None,
                      cand=None, cand_outline=None, mk_cand=None, along_cm=None):
    """Message 8. `layer_outlines` = message 2 of the layer photo, `zone` =
    its message 4 (both as saved next to the layer photo). `cand`,
    `cand_outline`, `mk_cand`: the photo, outline (message 6) and marker of the
    stone that fitted at the stone stock: then that stone is looked for by its
    own texture first (locate_known_stone); else, or if that fails, as what changed."""
    h, w = placed.shape[:2]
    msg = {"photo_ts": photo_ts, "layer_ts": layer_ts, "result": "unknown", "image_size": [w, h],
           "outline": [], "outline_cm": None, "base": [], "max": [], "min": [], "arrow": [],
           "move_cm": None, "move_along_cm": None, "move_across_cm": None, "details": None, "note": ""}

    def done(note):
        msg["note"] = note
        msg["ts"] = time.time()
        return msg
    if layer is None or mk0 is None or not zone or not zone.get("max_cm"):
        return done("no zone in cm for this layer (the layer photo had no marker)")
    wall = zone.get("wall_cm")
    if not wall:
        return done("the zone has no wall frame (made before 2026-11-24): photograph the layer again")
    region0 = np.zeros(layer.shape[:2], np.uint8)
    for s in layer_outlines.get("stones", []):
        cv2.fillPoly(region0, [np.int32(s["outline"])], 255)
    for o in layer_outlines.get("context", []):  # the second mode: D and the stones under it
        cv2.fillPoly(region0, [np.int32(o)], 255)
    region0 = cv2.dilate(region0, np.ones((15, 15), np.uint8)) | mk0.square_mask(layer.shape)
    H, how = register(layer, placed, mk0, mk1, region0)
    if H is None:
        return done("cannot line this photo up with the layer photo: no QR marker, " + how)
    if mk1 is None:
        mk1, how = Seen(mk0, H, layer.shape), how + ", marker from the layer photo"
    # the zone in this photo, through the marker
    msg["max"] = _px(mk1.to_px(np.float32(zone["max_cm"])))
    msg["min"] = _px(mk1.to_px(np.float32(zone["min_cm"])))
    # the base stones of the layer photo, in this photo (the phone draws them red, as at the start)
    for st in layer_outlines.get("stones", []):
        pts = cv2.perspectiveTransform(np.float64(st["outline"]).reshape(-1, 1, 2), H).reshape(-1, 2)
        msg["base"].append(_px(pts))
    stone_cm = (zone.get("depth_range_cm") or [30.0])[0]
    outline, found_by = None, ""
    if cand is not None and cand_outline and mk_cand is not None:
        # Where to look: the tap if there is one (only a hint now), else the must zone's
        # middle, where the stone has to lie anyway; small stones are hard to tap on a phone.
        near = tap if tap is not None else np.float32(msg["min"]).mean(axis=0)
        radius = (1.5 if tap is not None else 2.0) * stone_cm * mk1.px_per_cm()
        outline, found_by = locate_known_stone(cand, cand_outline, placed, mk_cand.px_per_cm(),
                                               mk1.px_per_cm(), near, radius)
        if outline is None:
            before = cv2.warpPerspective(layer, H, (w, h), flags=cv2.INTER_LINEAR)
            outline, why = match_known_stone(cand, cand_outline, placed, mk_cand.px_per_cm(),
                                             mk1.px_per_cm(), near, radius, before,
                                             np.float32(msg["max"]), 0)
            found_by = why if outline is not None else found_by + "; " + why
    if outline is None and tap is not None and cand_outline and mk_cand is not None:
        # The person tapped the new stone: its known outline there, along the wall.
        cm_known = known_stone_at_tap(mk_cand.to_cm(np.float32(cand_outline)), along_cm,
                                      mk1.to_cm(np.float32([tap]))[0], wall)
        outline = mk1.to_px(np.float32(cm_known))
        found_by = "its outline from the stone stock put at the tap, along the wall" + (
            " (%s)" % found_by if found_by else "")
    if outline is None and cand_outline and mk_cand is not None:
        # Its texture and picture are not found: its own outline, fitted to what changed.
        outline, why = fit_known_outline(layer, placed, H, mk1, mk_cand.to_cm(np.float32(cand_outline)),
                                         msg["max"], stone_cm)
        found_by = why + ("; " + found_by if found_by else "")
        if outline is None:
            found_by = "not fitted: " + found_by
    if outline is None:
        outline, why = find_new_stone(layer, placed, H, mk1, msg["max"], tap, stone_cm)
        if outline is None:
            return done("no new stone found (%s%s; lined up by %s)" % (why, "; " + found_by if found_by else "", how))
        found_by = "found as what changed" + ("; " + found_by if found_by else "")
    simple = cv2.approxPolyDP(np.float32(outline).reshape(-1, 1, 2), 2.0, True).reshape(-1, 2)
    cm = mk1.to_cm(simple)
    msg["outline"], msg["outline_cm"] = _px(simple), _cm(cm)
    result, mu, mn, info = check(cm, wall, stone_cm)
    msg["result"], msg["details"] = result, info
    msg["move_along_cm"], msg["move_across_cm"] = round(mu, 1), round(mn, 1)
    move = mu * np.asarray(wall["u"]) + mn * np.asarray(wall["n"])
    msg["move_cm"] = [round(float(move[0]), 1), round(float(move[1]), 1)]
    if result == "move":
        mid = cm.mean(axis=0)
        msg["arrow"] = _px(mk1.to_px(np.float32([mid, mid + move])))
    notes = [found_by, "lined up by " + how]
    if result == "wrong_size":
        notes.append("no shift makes it right: the stone does not fit this zone")
    return done("; ".join(notes))
