"""Grasshopper's replies to one photo: the stone outlines (MESSAGES.md
message 2) and the rule-of-thirds zone (message 4) for a layer photo, or
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

    python replies.py cand.jpg --ts 1763297400.0 --layer-ts 1763297262.123 --zone photo.zone.json

A candidate stone's photo instead: writes cand.fit.json (message 6).

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
from rule_of_thirds import compute_thirds, pick_base_pair  # noqa: E402
from stone_detect import DetectParams, detect_stones, stone_from_points  # noqa: E402


# With the marker the detection's sizes are set in cm instead of as a share
# of the photo: the photo may hold a lot besides the stones (the paper,
# the ground around), and small test stones were merged with their
# neighbour or dropped as "too small" (2026-11-18).
MIN_STONE_CM2 = 8.0    # smaller blobs are not stones
CLEAN_CM = 0.5         # the clean-up kernel; gaps between stones wider than this stay open


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
    """Message 4: the rule-of-thirds zone on the two largest stones. With the
    marker it is computed in cm (a true top view) and drawn back to pixels."""
    msg = {"photo_ts": photo_ts, "image_size": list(image_size), "max": [], "min": [],
           "max_cm": None, "min_cm": None, "length_cm": None, "depth_cm": None, "note": ""}
    try:
        if marker is None:
            r = compute_thirds(*pick_base_pair(found)[:2])
            msg["max"], msg["min"] = _px(r.box(r.allowed)), _px(r.box(r.must))
        else:  # outlines in mm (Stone contours are integers), so mm / 10 = cm
            mm = [stone_from_points(marker.to_cm(s.contour) * 10, hull=False) for s in found]
            r = compute_thirds(*pick_base_pair(mm)[:2])
            for key, span in (("max", r.allowed), ("min", r.must)):
                box = r.box(span) / 10.0
                msg[key], msg[key + "_cm"] = _px(marker.to_px(box)), _cm(box)
            msg["length_cm"] = [round(r.must.width / 10, 1), round(r.allowed.width / 10, 1)]
            msg["depth_cm"] = round(r.depth.width / 10, 1)
    except ValueError as e:  # e.g. fewer than two stones
        msg["note"] = str(e)
    msg["ts"] = time.time()
    return msg


def fit_message(found, marker, image_size, photo_ts, layer_ts, zone):
    """Message 6: is the candidate (the stone nearest the photo's middle) as
    long as the zone wants? `zone` = message 4 of the layer photo, or None."""
    msg = {"photo_ts": photo_ts, "layer_ts": layer_ts, "result": "unknown",
           "length_cm": None, "width_cm": None, "need_cm": zone.get("length_cm") if zone else None,
           "image_size": list(image_size), "outline": [], "note": ""}
    notes = []
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
        notes.insert(0, "no stone found")
    elif not msg["need_cm"]:
        notes.insert(0, "no zone for this layer" + (": " + zone["note"] if zone and zone.get("note") else ""))
    else:
        lo, hi = msg["need_cm"]
        msg["result"] = "too_short" if msg["length_cm"] < lo else "too_long" if msg["length_cm"] > hi else "fits"
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
    a = ap.parse_args()

    img = cv2.imread(str(a.photo))
    if img is None:
        sys.exit("cannot read %s" % a.photo)
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
        print("zone: next stone %.1f-%.1f cm long, %.1f cm deep (sent after a Yes)" % (
            zone["length_cm"][0], zone["length_cm"][1], zone["depth_cm"]))
    else:
        print("zone: ready, pixels only (sent after a Yes)")


def candidate(img, a):
    """Flow step 9: one stone, its length against the zone -> photo.fit.json."""
    found, marker = detect(img, 1, a.qr_id)
    zone = json.loads(a.zone.read_text()) if a.zone and a.zone.is_file() else None
    msg = fit_message(found, marker, img.shape[1::-1], a.ts, a.layer_ts, zone)
    Path(str(a.photo.with_suffix("")) + ".fit.json").write_text(json.dumps(msg))
    if msg["length_cm"] is not None:
        print("candidate: %.1f x %.1f cm" % (msg["length_cm"], msg["width_cm"]))
    print("result: %s%s%s" % (msg["result"],
                              " (zone wants %.1f-%.1f cm)" % tuple(msg["need_cm"]) if msg["need_cm"] else "",
                              ", " + msg["note"] if msg["note"] else ""))


if __name__ == "__main__":
    main()
