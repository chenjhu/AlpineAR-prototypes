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
from rule_of_thirds import compute_zone, pick_base_pair  # noqa: E402
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


def detect(img, stones, qr_id=10):
    """The Mode 1 detection on a BGR image; `stones` = how many to expect.
    Returns (stones, marker): marker = the QR `qr_id` found in the photo, or
    None (qr_id 0 = do not look).

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
                              min_area_frac=MIN_STONE_CM2 * ppc ** 2 / (w * h),
                              morph_frac=CLEAN_CM * ppc / w)
    params.plain_ground = is_plain(img)

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
    return [s for s in found if not touches(s)], marker


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
    found, marker = detect(img, a.stones, a.qr_id)
    if not found:
        sys.exit("no stones found" + ("" if marker else " (and no QR %d)" % a.qr_id))
    h, w = img.shape[:2]

    stem = a.photo.with_suffix("")
    stones = stones_file(found, (w, h), marker, a.ref_cm, a.photo.name)
    Path(str(stem) + ".json").write_text(json.dumps(stones, indent=1))
    outlines = outlines_message(found, (w, h), a.ts, marker)
    Path(str(stem) + ".outlines.json").write_text(json.dumps(outlines))
    zone = zone_message(found, (w, h), a.ts, marker)
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
