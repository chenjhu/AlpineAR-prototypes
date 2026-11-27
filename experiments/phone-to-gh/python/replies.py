"""Grasshopper's replies to one photo: the stone outlines (MESSAGES.md
message 2) and the zone for the next stone (message 4, the quarter rule of
../mode1-rule-of-thirds/rule_of_thirds.py) for a layer photo, or
the fit check (message 6) for a candidate stone's photo (message 5).

One place for this code, used by both
- Grasshopper: grasshopper/detect_photo.py runs this file with the Mode 1
  venv (Grasshopper's Python has no OpenCV), and
- python/fake_gh.py, the stand-in for Grasshopper,
so the two always send the same thing.

    python replies.py photo.jpg --ts 1763297262.123 --stones 2 --ref-cm 45 --qr-id 10

Detects once and writes next to the photo:
  photo.json           the stones in cm        -> "receive contours" (curves)
  photo.outlines.json  message 2               -> "reply to phone" sends it
  photo.zone.json      message 4               -> "reply to phone" sends it after a Yes

    python replies.py cand.jpg --ts 1763297400.0 --layer-ts 1763297262.123 --zone photo.zone.json --tap 640,360

A candidate stone's photo instead: writes cand.fit.json (message 6).

The second mode, "next to a laid stone" (message 1's `mode` = "next_to",
kept by Grasshopper as photo.msg.json; or --mode next_to): the zone is for a
stone next to the one laid last on this course (compute_zone_next_to). That
stone is the last placement check's (placed_*.placement.json in the same
folder), found again in this photo by its picture; see next_to_layer().
--tap: where the person tapped the stone (message 5's `tap`); the stone is
then grown from that point (detect_tapped), much more reliable.

The scale: if the QR marker (--qr-id, see qr_marker.py) lies in the photo,
everything in cm is in the marker's frame (x red, y green), the photo's tilt
taken out, and the marker's paper is covered before the stones are
detected (see detect()). Without it, as before: cm = the biggest stone's long side is
--ref-cm, origin at the photo's bottom-left, y up; no cm in the messages.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

EXPERIMENTS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EXPERIMENTS / "mode1-rule-of-thirds"))
sys.path.insert(0, str(EXPERIMENTS / "rhino-contour-to-gh" / "python"))
from photo_to_json import SIMPLIFY_PX, stones_to_dict  # noqa: E402
from qr_marker import find_marker, paint_ground  # noqa: E402
from rule_of_thirds import compute_zone, compute_zone_next_to, pick_base_pair  # noqa: E402
from stone_detect import DetectParams, detect_stones, plain_ground_distance, stone_from_points  # noqa: E402


# With the marker the detection's sizes are set in cm instead of as a share
# of the photo: the photo may hold a lot besides the stones (the paper,
# the ground around), and small test stones were merged with their
# neighbour or dropped as "too small" (2026-11-18).
MIN_STONE_CM2 = 8.0    # smaller blobs are not stones
CLEAN_CM = 0.5         # the clean-up kernel; gaps between stones wider than this stay open
PLAIN_SPREAD = 5.0     # a ground plainer than this is "plain" (white paper): see is_plain()


def is_plain(img):
    """Is the ground plain, like a white sheet? Then the detection takes as
    stone whatever is clearly not the ground's colour (DetectParams.plain_ground).
    The ground's spread (stone_detect.plain_ground_distance) on the photo at
    640 px, measured 2026-11-24: photos on paper 1.3-1.7, the phone photos on
    a table / floor 6-45."""
    small = cv2.resize(img, (640, max(1, round(640 * img.shape[0] / img.shape[1]))),
                       interpolation=cv2.INTER_AREA)
    small = cv2.bilateralFilter(small, 9, 50, 50)
    return plain_ground_distance(small, 0.06, 0.5)[1] <= PLAIN_SPREAD


def _tight_threshold(img, params):
    """A ground threshold between the photo's (Otsu over everything) and the
    stones' own (Otsu over what the first one calls stone). The first one
    takes the grey halo of shadow around the stones as stone too, which
    bridges a gap of a few mm between two stones: the next base stone C and
    the stones under the laid one were one outline (phone test, 2026-11-27)."""
    d = detect_stones(img, params)
    gd, fg = d.debug["ground_distance"], d.debug["mask"]
    if not fg.any():
        return None
    t0, _ = cv2.threshold(gd, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    t1, _ = cv2.threshold(gd[fg > 0].reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return 0.5 * (float(t0) + float(t1))


def _split_on_ground_distance(img, params, stones, min_px):
    """Fewer stones than expected: split them on the ground-distance image
    (how far each pixel's colour is from the ground). There each stone is
    bright and the gap between two touching stones is darker, even where the
    usual detection saw one stone: the gap's shadow was taken as stone, or a
    pale stone lost half its seed to the ground (phone tests 2026-11-27, two
    base stones side by side: "need two base stones, found 1"). The bright
    cores are kept while the threshold rises; of the levels where exactly
    `stones` of them stand apart, the one whose smallest core is biggest
    (the first level that splits often cuts the brighter stone in two before
    a pale one stands alone). They seed a watershed inside the stone mask.
    The outlines are the regions' convex hulls: a pale patch on a stone
    reads as ground and bit a notch into it. Returns full-resolution Stones,
    [] if they never come apart."""
    from stone_detect import _to_stone
    d = detect_stones(img, params)
    gd, fg, scale = d.debug["ground_distance"], d.debug["mask"], d.scale
    if not fg.any():
        return []
    t0, _ = cv2.threshold(gd[fg > 0].reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    core_px = 0.25 * min_px * scale ** 2
    cores, best = None, -1
    for level in range(int(t0), 250, 4):
        n, lab, st, _ = cv2.connectedComponentsWithStats(np.uint8((gd > level) & (fg > 0)))
        keep = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= core_px]
        if len(keep) == stones and min(st[i, cv2.CC_STAT_AREA] for i in keep) > best:
            cores, best = (lab, keep), min(st[i, cv2.CC_STAT_AREA] for i in keep)
    if cores is None:
        return []
    lab, keep = cores
    markers = np.zeros(gd.shape, np.int32)
    markers[cv2.dilate(fg, np.ones((5, 5), np.uint8)) == 0] = 1
    for k, i in enumerate(keep):
        markers[lab == i] = k + 2
    cv2.watershed(cv2.merge([255 - gd] * 3), markers)
    out = []
    kernel = np.ones((3, 3), np.uint8)
    for k in range(len(keep)):
        region = cv2.morphologyEx(np.uint8((markers == k + 2) & (fg > 0)) * 255, cv2.MORPH_OPEN, kernel)
        cs, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if cs:
            c = cv2.convexHull(max(cs, key=cv2.contourArea))
            if cv2.contourArea(c) >= min_px * scale ** 2:
                out.append(_to_stone(c, scale))
    # Hulls that overlap: the cut ran through a stone (the dark gap's shadow read as stone and
    # joined a pale stone to half its neighbour, 19:34:19). No split rather than a wrong zone.
    masks = []
    for st in out:
        m = np.zeros(img.shape[:2], np.uint8)
        cv2.drawContours(m, [st.contour], -1, 255, cv2.FILLED)
        masks.append(m)
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            if np.count_nonzero(masks[i] & masks[j]) > 0.1 * min(out[i].area, out[j].area):
                return []
    return sorted(out, key=lambda st: st.area, reverse=True)


def detect(img, stones, qr_id=10, min_cm2=MIN_STONE_CM2, tight=False):
    """The Mode 1 detection on a BGR image; `stones` = how many to expect.
    Returns (stones, marker): marker = the QR `qr_id` found in the photo, or
    None (qr_id 0 = do not look).

    `min_cm2`: smaller stones are dropped (with the marker). `tight`: the
    stricter ground threshold of _tight_threshold (the second mode's retry).

    Not a stone: anything cut by the photo's edge (a laptop, a knee) and,
    with the marker, anything touching its printed square (the rest of an
    uncut sheet). Those are painted over in the colour of the ground around
    them and the detection runs again, so they do not take the place of a
    real stone when the detection merges pieces down to `stones` (two
    touching stones were merged into one, 2026-11-18). So the stones must
    not touch the paper, nor the photo's edge.
    With the marker the detection's sizes are in cm (above)."""
    marker = find_marker(img, qr_id) if qr_id else None
    h, w = img.shape[:2]
    params = DetectParams(stones=stones)
    off_limits = np.zeros((h, w), np.uint8)
    off_limits[:3], off_limits[-3:], off_limits[:, :3], off_limits[:, -3:] = 255, 255, 255, 255
    if marker is not None:
        square = marker.square_mask(img.shape)
        img = paint_ground(img, square)
        off_limits |= cv2.dilate(square, np.ones((5, 5), np.uint8))
        ppc = marker.px_per_cm()
        params = DetectParams(stones=stones, work_width=min(w, 1280),
                              min_area_frac=min_cm2 * ppc ** 2 / (w * h),
                              morph_frac=CLEAN_CM * ppc / w)
    params.plain_ground = is_plain(img)
    if tight and not params.plain_ground:
        params.ground_thresh = _tight_threshold(img, params)

    def touches(s):
        one = np.zeros((h, w), np.uint8)
        cv2.drawContours(one, [s.contour], -1, 255, cv2.FILLED)
        return bool((one & off_limits).any())

    for _ in range(3):
        found = detect_stones(img, params).stones
        out = np.zeros((h, w), np.uint8)
        cv2.drawContours(out, [s.contour for s in found if touches(s)], -1, 255, cv2.FILLED)
        if not out.any():
            break
        img = paint_ground(img, cv2.dilate(out, np.ones((15, 15), np.uint8)))  # with its rim (shadow, blur)
    found = [s for s in found if not touches(s)]
    if marker is not None and len(found) < stones and not params.plain_ground:
        # Too few: split on the ground distance (only then, so photos that work stay the same).
        # Half the minimum size: a split-off stone came out 7-8 cm2 for 8 (the pale one).
        split = [s for s in _split_on_ground_distance(img, params, stones, 0.5 * min_cm2 * ppc ** 2)
                 if not touches(s)]
        if len(split) > len(found):
            found = split
    return found, marker


TAP_START_CM = 12.0    # first crop around a tap: this far each way
TAP_MIN_CM2 = 2.0      # a tapped stone may be small (the test pebbles were ~6 cm2)


GROUND_BORDER_SHARE = 0.5   # this much of the square's edge must look like ground


def _ground_test(img):
    """A test 'is this pixel ground?' from the photo's own border: the stones
    may not touch the photo's edge (see detect()), so the border is ground.
    Lab colour within the border's own spread of its median. A busy border
    (a table edge, the paper) gives a wide spread, so then almost everything
    counts as ground and nothing changes for small stones."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    b = 4
    border = np.concatenate([lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3),
                             lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)])
    med = np.median(border, axis=0)
    tol = 1.5 * float(np.percentile(np.linalg.norm(border - med, axis=1), 90)) + 4.0

    def test(pixels_bgr):
        p = cv2.cvtColor(pixels_bgr.reshape(-1, 1, 3), cv2.COLOR_BGR2LAB).astype(np.float32).reshape(-1, 3)
        return np.linalg.norm(p - med, axis=1) <= tol
    return test


def _ground_share(crop, is_ground, b=3):
    """How much of the crop's edge is ground."""
    edge = np.concatenate([crop[:b].reshape(-1, 3), crop[-b:].reshape(-1, 3),
                           crop[:, :b].reshape(-1, 3), crop[:, -b:].reshape(-1, 3)])
    return float(is_ground(edge).mean())


def detect_tapped(img, tap, qr_id=10):
    """One stone, the one the person tapped on (`tap` = (x, y) in photo
    pixels). Returns (stone or None, marker, info).

    Instead of guessing where the stones are, the detection grows the stone
    from the tap, and it looks only at a square around it: the ground's
    colour is learned from that square's border, so the rest of the paper,
    the table edge or shadows elsewhere in the photo do not count. If the
    stone reaches the square's edge, the square grows and it tries again."""
    marker = find_marker(img, qr_id) if qr_id else None
    h, w = img.shape[:2]
    if marker is not None:
        img = paint_ground(img, marker.square_mask(img.shape))
        ppc = marker.px_per_cm()
    else:
        ppc = w / 60.0  # no scale: guess a photo about 60 cm wide
    tx, ty = float(tap[0]), float(tap[1])
    if not (0 <= tx < w and 0 <= ty < h):
        return None, marker, "tap outside the photo"
    if is_plain(img):
        # Plain ground: the whole photo at once; the stone is what is not
        # ground around the tap, whatever its colours.
        params = DetectParams(stones=1, work_width=min(w, 1280), plain_ground=True,
                              min_area_frac=TAP_MIN_CM2 * ppc ** 2 / (w * h),
                              morph_frac=CLEAN_CM * ppc / w)
        found = detect_stones(img, params, seeds=[(tx, ty)]).stones
        if not found:
            return None, marker, "no stone at the tap"
        return stone_from_points(found[0].contour.reshape(-1, 2), hull=False), marker, ""
    is_ground = _ground_test(img)
    half = TAP_START_CM * ppc
    for _ in range(7):
        x0, y0 = int(max(0, tx - half)), int(max(0, ty - half))
        x1, y1 = int(min(w, tx + half)), int(min(h, ty + half))
        crop = img[y0:y1, x0:x1]
        cw, ch = x1 - x0, y1 - y0
        whole = cw >= w and ch >= h
        if not whole and _ground_share(crop, is_ground) < GROUND_BORDER_SHARE:
            # The square's edge is not ground: it is still inside the stone
            # (a real 40 cm stone in a 24 cm square), so the ground cannot be
            # learned from it. Grow first (real-scale test, 2026-11-24).
            half *= 1.8
            continue
        params = DetectParams(stones=1, work_width=cw,
                              min_area_frac=TAP_MIN_CM2 * ppc ** 2 / (cw * ch),
                              morph_frac=CLEAN_CM * ppc / cw)
        found = detect_stones(crop, params, seeds=[(tx - x0, ty - y0)]).stones
        if not found:
            return None, marker, "no stone at the tap"
        stone = found[0]
        bx, by, bw, bh = cv2.boundingRect(stone.contour)
        cut = ((bx <= 2 and x0 > 0) or (by <= 2 and y0 > 0)
               or (bx + bw >= cw - 2 and x1 < w) or (by + bh >= ch - 2 and y1 < h))
        if not cut:
            return stone_from_points(stone.contour.reshape(-1, 2) + [x0, y0], hull=False), marker, ""
        half *= 1.8
    return None, marker, "the tapped stone has no clear edge"


def _px(pts):
    return [[int(round(x)), int(round(y))] for x, y in pts]


def _cm(pts):
    return [[round(float(x), 1), round(float(y), 1)] for x, y in pts]


def _outline(stone):
    """The outline as sent: simplified, pixels of the photo."""
    return cv2.approxPolyDP(stone.contour, SIMPLIFY_PX, True).reshape(-1, 2)


def outlines_message(found, image_size, photo_ts, marker=None):
    """Message 2: one closed outline per detected stone, pixels of the photo,
    and in cm when the marker is in the photo."""
    out = []
    for i, s in enumerate(found):
        c = _outline(s)
        out.append({"id": i, "outline": _px(c), "outline_cm": _cm(marker.to_cm(c)) if marker else None})
    qr = {"id": marker.qr_id, "frame": _px(marker.frame_px())} if marker else None
    return {"photo_ts": photo_ts, "image_size": list(image_size), "qr": qr, "stones": out, "ts": time.time()}


def zone_message(found, image_size, photo_ts, marker=None):
    """Message 4: the zone (quarter rule) on the two largest stones. With the
    marker it is computed in cm (a true top view) and drawn back to pixels."""
    msg = {"photo_ts": photo_ts, "image_size": list(image_size), "max": [], "min": [],
           "max_cm": None, "min_cm": None, "length_cm": None, "depth_cm": None,
           "depth_range_cm": None, "wall_cm": None, "note": ""}
    try:
        if marker is None:
            r = compute_zone(*pick_base_pair(found)[:2])
            msg["max"], msg["min"] = _px(r.box(r.allowed)), _px(r.box(r.must))
        else:  # outlines in mm (Stone contours are integers), so mm / 10 = cm
            mm = [stone_from_points(marker.to_cm(s.contour) * 10, hull=False) for s in found]
            r = compute_zone(*pick_base_pair(mm)[:2])
            for key, span in (("max", r.allowed), ("min", r.must)):
                box = r.box(span) / 10.0
                msg[key], msg[key + "_cm"] = _px(marker.to_px(box)), _cm(box)
            msg["length_cm"] = [round(r.must.width / 10, 1), round(r.allowed.width / 10, 1)]
            msg["depth_cm"] = round(r.depth.width / 10, 1)
            msg["depth_range_cm"] = [round(r.stone_depth.lo / 10, 1), round(r.stone_depth.hi / 10, 1)]
            # The wall's own frame, for the check after placing (placement.py):
            # along = (p - origin) . u, across = (p - origin) . n, in cm.
            msg["wall_cm"] = {"origin": _cm([r.origin / 10])[0],
                              "u": [round(float(v), 5) for v in r.u], "n": [round(float(v), 5) for v in r.n],
                              "joint": round(r.joint / 10, 2), "x": round(r.x / 10, 2), "y": round(r.y / 10, 2),
                              "depth": [round(r.depth.lo / 10, 2), round(r.depth.hi / 10, 2)],
                              "fraction": r.fraction}
    except ValueError as e:  # e.g. fewer than two stones
        msg["note"] = str(e)
    msg["ts"] = time.time()
    return msg


ON_TWO, NEXT_TO = "on_two", "next_to"   # message 1's `mode` (MESSAGES.md)


def photo_mode(photo):
    """The mode the phone sent with the photo: Grasshopper keeps message 1's
    extra fields next to it as photo.msg.json. None there: the first mode."""
    try:
        return json.loads(Path(str(photo.with_suffix("")) + ".msg.json").read_text()).get("mode") or ON_TWO
    except (OSError, ValueError):
        return ON_TWO


def _mask(stone, shape):
    m = np.zeros(shape[:2], np.uint8)
    cv2.drawContours(m, [stone.contour], -1, 255, cv2.FILLED)
    return m


def laid_stone(img, marker, folder, qr_id=10):
    """The stone laid last on this course (D): the newest placement check in
    `folder` with an outline, found again in this photo by its picture
    (placement.locate_known_stone / match_known_stone) near where the marker
    says it was, so a nudged paper or stone does not matter. Returns
    (outline px or None, info)."""
    from placement import locate_known_stone, match_known_stone
    for f in sorted(folder.glob("placed_*.placement.json"), reverse=True):
        try:
            m = json.loads(f.read_text())
        except ValueError:
            continue
        if m.get("outline") and m.get("outline_cm"):
            break
    else:
        return None, "no placement check yet in this folder"
    prev = cv2.imread(str(f)[:-len(".placement.json")] + ".jpg")
    mk_prev = find_marker(prev, qr_id) if prev is not None and qr_id else None
    if mk_prev is None:
        return None, "the last placement photo (%s) has no marker" % f.name
    cm = np.float32(m["outline_cm"])
    near = marker.to_px(cm.mean(axis=0, keepdims=True))[0]
    radius = float(np.ptp(cm, axis=0).max()) * marker.px_per_cm()
    ppc0, ppc1 = mk_prev.px_per_cm(), marker.px_per_cm()
    outline, how = locate_known_stone(prev, m["outline"], img, ppc0, ppc1, near, radius)
    if outline is None:
        outline, why = match_known_stone(prev, m["outline"], img, ppc0, ppc1, near, radius)
        how = why if outline is not None else how + "; " + why
    if outline is None:
        return None, "the stone of %s is not found here (%s)" % (f.name, how)
    return outline, "laid stone from %s, %s" % (f.name, how)


def _course_axis(stones, near=None, reach=None):
    """Along the course: the long axis of the stones' pixels (those within
    `reach` of `near`), pointing to the photo's +x or +y, whichever it runs
    closer to (as pick_base_pair orders the base stones). On the phone, held
    upright, +y is the screen's right and +x its top: the wall is built from
    left to right, or from the bottom up when it runs up the screen."""
    pts = [s.contour.reshape(-1, 2).astype(np.float32) for s in stones
           if near is None or np.linalg.norm(np.array(s.centroid) - near) <= reach]
    pts = np.concatenate(pts)
    _, _, vt = np.linalg.svd(pts - pts.mean(axis=0), full_matrices=False)
    ax = vt[0]
    if (ax[0] if abs(ax[0]) >= abs(ax[1]) else ax[1]) < 0:
        ax = -ax
    return ax


def pick_next_to(found, laid, shape):
    """(B as seen, C) for the stone that goes next to `laid` (D). B: a stone
    under D that reaches past D's end (seen from above, D and the stones it
    lies on are often one outline). C: the next stone after B along the course,
    beyond D's end. Raises ValueError if there is none.

    Which end of D: the one with a free base stone C beyond it. Both ends are
    tried; the photo's axes say nothing about it (the first phone test,
    2026-11-27: C lay towards the photo's -x, only +x was looked at, so "no next
    base stone" every time). If both ends have one, the nearer C."""
    size = float(np.sqrt(max(laid.area, 1.0)))
    d_c = np.array(laid.centroid, np.float32)
    ax = _course_axis(found + [laid], d_c, 3 * size)
    best, errors = None, []
    for direction in (ax, -ax):
        try:
            got = _pick_along(found, laid, shape, direction, size)
        except ValueError as e:
            errors.append(str(e))
            continue
        if best is None or got[2] < best[2]:
            best = got
    if best is None:
        # the further one got: a base stone under D but no C beats no base stone at all
        raise ValueError(min(errors, key=lambda e: e.startswith("no base stone")))
    return best[0], best[1]


def _pick_along(found, laid, shape, ax, size):
    """pick_next_to towards `ax`: (B, C, distance from B's end to C)."""
    proj = lambda s: s.contour.reshape(-1, 2).astype(np.float32) @ ax
    d_end = float(proj(laid).max())
    near = cv2.dilate(_mask(laid, shape), np.ones((3, 3), np.uint8), iterations=max(1, int(0.15 * size)))
    under = [(int(np.count_nonzero(_mask(s, shape) & near)), s) for s in found]
    under = [(o, s) for o, s in under if o > 0 and proj(s).max() > d_end + 0.1 * size]
    if not under:
        raise ValueError("no base stone found under the laid stone's end")
    b = max(under, key=lambda t: t[0])[1]
    b_end = float(proj(b).max())
    across = np.array([-ax[1], ax[0]], np.float32)
    nexts = []
    for s in found:
        if s is b or proj(s).min() < d_end:
            continue
        off = abs(float((np.array(s.centroid) - np.array(b.centroid)) @ across))
        if off <= size:
            nexts.append((abs(float(proj(s).min()) - b_end) + off, s))
    if not nexts:
        raise ValueError("no next base stone after the laid stone")
    cost, c = min(nexts, key=lambda t: t[0])
    return b, c, cost


NEXT_TO_MIN_CM2 = 3.0  # the second mode: C may be a small or thin stone (7 cm2, phone test 2026-11-27)


def _without_laid(found, laid, shape):
    """`found` without the pieces of D the detection gave on their own (lying
    almost wholly inside it; the outline of A + D + B is half D, 2026-11-27)."""
    if laid is None:
        return list(found)
    dm = cv2.dilate(_mask(laid, shape), np.ones((7, 7), np.uint8))
    return [s for s in found if np.count_nonzero(_mask(s, shape) & dm) < 0.8 * max(s.area, 1.0)]


def next_to_layer(img, folder, stones, qr_id, photo_ts):
    """The layer photo in the second mode. Returns (found, marker, shown,
    context, zone): `shown` = the stones for message 2, only C, the new base
    stone the zone reaches onto (the group, 2026-11-27: "only the new stone");
    everything found when there is no zone. `context` = D and the stones
    under it, not drawn on the phone but kept in message 2 for the
    placement check (it lines the photos up on them).

    D (the laid stone) is the last placement check's (laid_stone); without
    one there is no zone and the phone shows "No zone: ...". The stones: the
    usual detection, and if that gives no C, once more with the tighter
    ground threshold (_tight_threshold)."""
    h, w = img.shape[:2]
    laid, info, tries = None, "no QR marker", []
    for tight in (False, True):
        found, marker = detect(img, stones, qr_id, NEXT_TO_MIN_CM2, tight)
        if not tries and marker is not None:
            outline, info = laid_stone(img, marker, folder, qr_id)
            laid = stone_from_points(np.float32(outline), hull=False) if outline is not None else None
        rest = _without_laid(found, laid, (h, w))
        zone, c = zone_message_next_to(rest, laid, (w, h), photo_ts, marker, info)
        tries.append((found, rest, marker, zone, c, tight))
        if c is not None or laid is None:
            break
    found, rest, marker, zone, c, tight = next((t for t in tries if t[4] is not None), tries[0])
    if c is None:
        return found, marker, found, [], zone
    if tight:
        zone["laid"] += "; stones found with the tighter ground threshold"
    return found, marker, [c], [laid] + [s for s in rest if s is not c], zone


def zone_message_next_to(found, laid, image_size, photo_ts, marker=None, info=""):
    """Message 4 in the second mode: the zone next to the laid stone `laid`
    (compute_zone_next_to), in cm. Its wall_cm has `start` (the laid stone's
    end, cm along u) and `rule` "next_to"; `x` is what is left of B (r_B).
    Returns (message, C or None)."""
    msg = {"photo_ts": photo_ts, "image_size": list(image_size), "max": [], "min": [],
           "max_cm": None, "min_cm": None, "length_cm": None, "depth_cm": None,
           "depth_range_cm": None, "wall_cm": None, "mode": NEXT_TO, "laid": info, "note": ""}
    c = None
    try:
        if marker is None:
            raise ValueError("no QR marker in the photo: the second mode needs it")
        if laid is None:
            raise ValueError("the laid stone is not found (%s)" % info)
        b, c = pick_next_to(found, laid, (image_size[1], image_size[0]))
        mm = lambda s: stone_from_points(marker.to_cm(s.contour) * 10, hull=False)
        try:
            r = compute_zone_next_to(mm(b), mm(c), mm(laid))
        except ValueError:
            c = None
            raise
        for key, span in (("max", r.allowed), ("min", r.must)):
            box = r.box(span) / 10.0
            msg[key], msg[key + "_cm"] = _px(marker.to_px(box)), _cm(box)
        msg["length_cm"] = [round(r.must.width / 10, 1), round(r.allowed.width / 10, 1)]
        msg["depth_cm"] = round(r.depth.width / 10, 1)
        msg["depth_range_cm"] = [round(r.stone_depth.lo / 10, 1), round(r.stone_depth.hi / 10, 1)]
        msg["wall_cm"] = {"origin": _cm([r.origin / 10])[0],
                          "u": [round(float(v), 5) for v in r.u], "n": [round(float(v), 5) for v in r.n],
                          "joint": round(r.joint / 10, 2), "x": round(r.x / 10, 2), "y": round(r.y / 10, 2),
                          "depth": [round(r.depth.lo / 10, 2), round(r.depth.hi / 10, 2)],
                          "fraction": r.fraction, "start": round(r.start / 10, 2), "rule": NEXT_TO}
    except ValueError as e:
        msg["note"] = str(e)
    msg["ts"] = time.time()
    return msg, c


def fit_result(a, b, need_length, need_depth=None):
    """The candidate's two sides a >= b (cm) against the zone. Returns
    (result, along, across): "fits" or what is wrong, and which side then
    goes along the wall / into it. Normally the long side goes along the
    wall; a stone that fits the other way round (long side into the wall)
    fits too. Without a depth range (an older zone message) only the length
    is checked."""
    def problem(along, across):
        lo, hi = need_length
        if along < lo:
            return "too_short"
        if along > hi:
            return "too_long"
        if need_depth and across < need_depth[0]:
            return "too_shallow"
        if need_depth and across > need_depth[1]:
            return "too_deep"
        return "fits"
    first = problem(a, b)
    if first != "fits" and problem(b, a) == "fits":
        return "fits", b, a
    return first, a, b


def candidate_stones(img, qr_id=10, tap=None):
    """The candidate stone of message 5: (stones, marker, note). With a tap
    (the person tapped the stone on the photo) only that stone, grown from
    the tap (detect_tapped); without one, the plain detection (the stone
    nearest the middle is taken later)."""
    if tap is None:
        found, marker = detect(img, 1, qr_id)
        return found, marker, ""
    stone, marker, info = detect_tapped(img, tap, qr_id)
    return ([stone] if stone is not None else []), marker, info


def fit_message(found, marker, image_size, photo_ts, layer_ts, zone, note=""):
    """Message 6: is the candidate (the stone nearest the photo's middle) as
    long and as deep as the zone wants? `zone` = message 4 of the layer
    photo, or None. `note`: from the detection (e.g. nothing at the tap)."""
    msg = {"photo_ts": photo_ts, "layer_ts": layer_ts, "result": "unknown",
           "length_cm": None, "width_cm": None, "need_cm": zone.get("length_cm") if zone else None,
           "need_depth_cm": zone.get("depth_range_cm") if zone else None,
           "along_cm": None, "across_cm": None,
           "image_size": list(image_size), "outline": [], "note": ""}
    notes = [note] if note else []
    if found:
        middle = np.array(image_size, float) / 2
        stone = min(found, key=lambda s: np.linalg.norm(np.array(s.centroid) - middle))
        msg["outline"] = _px(_outline(stone))
        if len(found) > 1:
            notes.append("%d stones in the photo, took the one in the middle" % len(found))
        if marker:
            (_, _), (a, b), _ = cv2.minAreaRect(np.float32(marker.to_cm(stone.contour)))
            msg["length_cm"], msg["width_cm"] = round(max(a, b), 1), round(min(a, b), 1)
    if not marker:
        notes.insert(0, "no QR marker in the photo, cannot measure")
    elif not found:
        # Nothing measured, so nothing to check (with a detection note, e.g.
        # "no stone at the tap", this crashed: real-scale test, 2026-11-24).
        if not note:
            notes.insert(0, "no stone found")
    elif not msg["need_cm"]:
        notes.insert(0, "no zone for this layer" + (": " + zone["note"] if zone and zone.get("note") else ""))
    else:
        msg["result"], msg["along_cm"], msg["across_cm"] = fit_result(
            msg["length_cm"], msg["width_cm"], msg["need_cm"], msg["need_depth_cm"])
        if msg["result"] == "fits" and msg["along_cm"] != msg["length_cm"]:
            notes.append("fits with its long side into the wall")
    msg["note"] = "; ".join(notes)
    msg["ts"] = time.time()
    return msg


def stones_file(found, image_size, marker, ref_cm, source):
    """photo.json for "receive contours": the outlines in cm."""
    if marker is None:  # as before: the biggest stone's long side = ref_cm
        return stones_to_dict(found, image_size, max(found[0].min_rect[1]) / ref_cm, "cm", source)
    out = []
    for i, s in enumerate(found):
        c = np.float32(marker.to_cm(_outline(s))).reshape(-1, 1, 2)
        m = cv2.moments(c)
        out.append({"id": i, "area": round(cv2.contourArea(c), 2),
                    "centroid": [round(m["m10"] / m["m00"], 2), round(m["m01"] / m["m00"], 2)],
                    "contour": [[round(float(x), 2), round(float(y), 2)] for x, y in c.reshape(-1, 2)]})
    return {"source": source, "unit": "cm", "frame": "QR %d (x red, y green)" % marker.qr_id,
            "px_per_unit": round(marker.px_per_cm(), 4), "image_size_px": list(image_size), "stones": out}


def draw(img, msg):
    """The photo with the outlines of message 2 and / or the zone of message 4
    (white = max, blue = min) drawn on it."""
    img = img.copy()
    if msg.get("qr"):
        f = np.int32(msg["qr"]["frame"])
        cv2.polylines(img, [f.reshape(-1, 1, 2)], True, (200, 200, 200), 2)
        cv2.line(img, tuple(map(int, f[0])), tuple(map(int, f[1])), (0, 0, 255), 4)    # x, red
        cv2.line(img, tuple(map(int, f[0])), tuple(map(int, f[3])), (0, 160, 0), 4)    # y, green
    for key, color in (("max", (255, 255, 255)), ("min", (255, 120, 0))):
        if msg.get(key):
            cv2.polylines(img, [np.int32(msg[key]).reshape(-1, 1, 2)], True, color, 3)
    for s in msg.get("stones", []):
        pts = np.int32(s["outline"]).reshape(-1, 1, 2)
        cv2.polylines(img, [pts], True, (0, 0, 255), 3)
        x, y = pts.reshape(-1, 2).mean(axis=0)
        cv2.putText(img, str(s["id"]), (int(x), int(y)), 0, 1.2, (0, 0, 255), 3)
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("photo", type=Path)
    ap.add_argument("--ts", type=float, required=True, help="the photo's ts from message 1 or 5")
    ap.add_argument("--stones", type=int, default=2, help="how many stones are in the photo")
    ap.add_argument("--ref-cm", type=float, help="layer photo: real length of the biggest stone in cm "
                    "(only used without the QR marker)")
    ap.add_argument("--qr-id", type=int, default=10, help="the QR marker in the photo (0 = do not look)")
    ap.add_argument("--zone", type=Path, help="candidate photo: the layer's .zone.json (message 4)")
    ap.add_argument("--layer-ts", type=float, help="candidate photo: layer_ts from message 5")
    ap.add_argument("--tap", help="candidate / placed photo: x,y where the person tapped the stone (photo pixels)")
    ap.add_argument("--placed", action="store_true", help="the wall after the new stone was laid: "
                    "check it against the zone (--zone; the layer photo and its outlines lie next to it)")
    ap.add_argument("--mode", choices=[ON_TWO, NEXT_TO], help="layer photo: the mode (default: the "
                    "photo's .msg.json from Grasshopper, else on_two)")
    ap.add_argument("--cand", type=Path, help="placed photo: the candidate photo of the stone that fitted "
                    "(its .fit.json next to it). Default: the last cand_*.fit.json for --layer-ts that fits, "
                    "next to the zone file")
    a = ap.parse_args()

    img = cv2.imread(str(a.photo))
    if img is None:
        sys.exit("cannot read %s" % a.photo)
    if a.placed:
        placed(img, a)
        return
    if a.layer_ts is not None:
        candidate(img, a)
        return
    if a.ref_cm is None:
        sys.exit("a layer photo needs --ref-cm")
    h, w = img.shape[:2]
    mode = a.mode or photo_mode(a.photo)
    if mode == NEXT_TO:
        found, marker, shown, context, zone = next_to_layer(img, a.photo.parent, a.stones, a.qr_id, a.ts)
        print("mode: next to a laid stone, " + zone["laid"])
    else:
        found, marker = detect(img, a.stones, a.qr_id)
        shown, context = found, []
    if not found:
        sys.exit("no stones found" + ("" if marker else " (and no QR %d)" % a.qr_id))
    if mode != NEXT_TO:
        zone = zone_message(found, (w, h), a.ts, marker)

    stem = a.photo.with_suffix("")
    stones = stones_file(shown + context, (w, h), marker, a.ref_cm, a.photo.name)
    Path(str(stem) + ".json").write_text(json.dumps(stones, indent=1))
    outlines = outlines_message(shown, (w, h), a.ts, marker)
    if context:
        # not drawn by the phone; the placement check lines the photos up on them too
        outlines["context"] = [_px(_outline(s)) for s in context]
    Path(str(stem) + ".outlines.json").write_text(json.dumps(outlines))
    Path(str(stem) + ".zone.json").write_text(json.dumps(zone))

    if marker:
        print("scale: QR %d in the photo (%.0f px/cm there), cm in its frame" % (marker.qr_id, marker.px_per_cm()))
    else:
        print("scale: NO QR %d in the photo, from ref_cm = %g (the biggest stone)" % (a.qr_id, a.ref_cm))
    print("%d stones from %s" % (len(found), a.photo.name))
    for s in stones["stones"]:
        print("  stone %d: area %.1f cm2, %d points" % (s["id"], s["area"], len(s["contour"])))
    if zone["note"]:
        print("zone: " + zone["note"])
    elif zone["length_cm"]:
        print("zone: next stone %.1f-%.1f cm long, %.1f-%.1f cm deep (sent after a Yes)" % (
            zone["length_cm"][0], zone["length_cm"][1], *zone["depth_range_cm"]))
    else:
        print("zone: ready, pixels only (sent after a Yes)")


def candidate(img, a):
    """Flow step 9: one stone, its length against the zone -> photo.fit.json."""
    tap = [float(v) for v in a.tap.split(",")] if a.tap else None
    found, marker, note = candidate_stones(img, a.qr_id, tap)
    zone = json.loads(a.zone.read_text()) if a.zone and a.zone.is_file() else None
    msg = fit_message(found, marker, img.shape[1::-1], a.ts, a.layer_ts, zone, note)
    Path(str(a.photo.with_suffix("")) + ".fit.json").write_text(json.dumps(msg))
    if msg["length_cm"] is not None:
        print("candidate: %.1f x %.1f cm" % (msg["length_cm"], msg["width_cm"]))
    print("result: %s%s%s" % (msg["result"],
                              " (zone wants %.1f-%.1f cm long" % tuple(msg["need_cm"])
                              + (", %.1f-%.1f cm deep)" % tuple(msg["need_depth_cm"]) if msg["need_depth_cm"] else ")")
                              if msg["need_cm"] else "",
                              ", " + msg["note"] if msg["note"] else ""))


def last_fitting_candidate(folder, layer_ts):
    """The newest candidate photo (cand_<time>.jpg) whose fit check (message 6)
    for this layer said "fits": the stone the person went on to lay."""
    best = None
    for f in sorted(folder.glob("cand_*.fit.json")):
        try:
            fit = json.loads(f.read_text())
        except ValueError:
            continue
        if fit.get("result") == "fits" and abs(float(fit.get("layer_ts", -1)) - layer_ts) < 0.001:
            jpg = Path(str(f)[:-len(".fit.json")] + ".jpg")
            if jpg.is_file():
                best = jpg
    return best


def placed(img, a):
    """After placing (messages 7-8): the new stone against the zone -> photo.placement.json."""
    from placement import placement_message
    if a.layer_ts is None or not a.zone:
        sys.exit("--placed needs --layer-ts and --zone")
    stem = str(a.zone)[:-len(".zone.json")] if str(a.zone).endswith(".zone.json") else str(a.zone.with_suffix(""))
    zone = json.loads(a.zone.read_text()) if a.zone.is_file() else None
    layer = cv2.imread(stem + ".jpg")
    outlines_path = Path(stem + ".outlines.json")
    outlines = json.loads(outlines_path.read_text()) if outlines_path.is_file() else {"stones": []}
    tap = [float(v) for v in a.tap.split(",")] if a.tap else None
    mk1 = find_marker(img, a.qr_id) if a.qr_id else None
    mk0 = find_marker(layer, a.qr_id) if a.qr_id and layer is not None else None
    if layer is None:
        zone = None
    cand_img = cand_outline = mk_cand = along = None
    cand_path = a.cand or last_fitting_candidate(Path(stem).parent, a.layer_ts)
    if cand_path is not None:
        fit = json.loads(Path(str(cand_path.with_suffix("")) + ".fit.json").read_text())
        cand_img = cv2.imread(str(cand_path))
        cand_outline = fit.get("outline")
        along = fit.get("along_cm")
        mk_cand = find_marker(cand_img, a.qr_id) if cand_img is not None and a.qr_id else None
    msg = placement_message(img, layer, mk1, mk0, outlines, zone, a.ts, a.layer_ts, tap,
                            cand_img, cand_outline, mk_cand, along)
    Path(str(a.photo.with_suffix("")) + ".placement.json").write_text(json.dumps(msg))
    d = msg["details"] or {}
    print("placed: %s%s%s" % (msg["result"],
                              ", move %.1f cm along, %.1f cm across" % (msg["move_along_cm"], msg["move_across_cm"])
                              if msg["result"] == "move" else "",
                              (", covers %.2f / %.2f of the base stones" % tuple(d["cover"]) if d else "")
                              + (", " + msg["note"] if msg["note"] else "")))


if __name__ == "__main__":
    main()
