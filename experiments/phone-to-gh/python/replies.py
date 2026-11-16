"""Grasshopper's replies to one photo: the stone outlines (MESSAGES.md
message 2) and the rule-of-thirds zone (message 4).

One place for this code, used by both
- Grasshopper: grasshopper/detect_photo.py runs this file with the Mode 1
  venv (Grasshopper's Python has no OpenCV), and
- python/fake_gh.py, the stand-in for Grasshopper,
so the two always send the same thing.

    python replies.py photo.jpg --ts 1763297262.123 --stones 2 --ref-cm 45

Detects once and writes next to the photo:
  photo.json           the stones in cm, y up  -> "receive contours" (curves)
  photo.outlines.json  message 2, pixels       -> "reply to phone" sends it
  photo.zone.json      message 4, pixels       -> "reply to phone" sends it after a Yes
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
from rule_of_thirds import compute_thirds, pick_base_pair  # noqa: E402
from stone_detect import DetectParams, detect_stones  # noqa: E402


def detect(img, stones):
    """The Mode 1 detection on a BGR image; `stones` = how many to expect."""
    return detect_stones(img, DetectParams(stones=stones)).stones


def outlines_message(found, image_size, photo_ts):
    """Message 2: one closed outline per detected stone, pixels of the photo."""
    out = []
    for i, s in enumerate(found):
        c = cv2.approxPolyDP(s.contour, SIMPLIFY_PX, True).reshape(-1, 2)
        out.append({"id": i, "outline": [[int(x), int(y)] for x, y in c]})
    return {"photo_ts": photo_ts, "image_size": list(image_size), "stones": out, "ts": time.time()}


def zone_message(found, image_size, photo_ts):
    """Message 4: the rule-of-thirds zone on the two largest stones."""
    msg = {"photo_ts": photo_ts, "image_size": list(image_size), "max": [], "min": [], "note": ""}
    try:
        left, right, _ = pick_base_pair(found)
        r = compute_thirds(left, right)
        msg["max"] = [[int(round(x)), int(round(y))] for x, y in r.box(r.allowed)]
        msg["min"] = [[int(round(x)), int(round(y))] for x, y in r.box(r.must)]
    except ValueError as e:  # e.g. fewer than two stones
        msg["note"] = str(e)
    msg["ts"] = time.time()
    return msg


def draw(img, msg):
    """The photo with the outlines of message 2 and / or the zone of message 4
    (white = max, blue = min) drawn on it."""
    img = img.copy()
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
    ap.add_argument("--ts", type=float, required=True, help="the photo's ts from message 1")
    ap.add_argument("--stones", type=int, default=2, help="how many stones are in the photo")
    ap.add_argument("--ref-cm", type=float, required=True, help="real length of the biggest stone in cm")
    a = ap.parse_args()

    img = cv2.imread(str(a.photo))
    if img is None:
        sys.exit("cannot read %s" % a.photo)
    found = detect(img, a.stones)
    if not found:
        sys.exit("no stones found")
    h, w = img.shape[:2]

    # the same file photo_to_json.py writes (cm, y up), for the curves in Rhino
    px_per_cm = max(found[0].min_rect[1]) / a.ref_cm
    stem = a.photo.with_suffix("")
    stones = stones_to_dict(found, (w, h), px_per_cm, "cm", a.photo.name)
    Path(str(stem) + ".json").write_text(json.dumps(stones, indent=1))
    outlines = outlines_message(found, (w, h), a.ts)
    Path(str(stem) + ".outlines.json").write_text(json.dumps(outlines))
    zone = zone_message(found, (w, h), a.ts)
    Path(str(stem) + ".zone.json").write_text(json.dumps(zone))

    print("%d stones from %s" % (len(found), a.photo.name))
    for s in stones["stones"]:
        print("  stone %d: area %.1f cm2, %d points" % (s["id"], s["area"], len(s["contour"])))
    print("zone: %s" % (zone["note"] or "ready (sent after a Yes)"))


if __name__ == "__main__":
    main()
