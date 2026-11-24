"""Collect the pictures from our tests into this folder, for the backup in git.

Run it after a test session (from experiments/phone-to-gh):

    python/.venv/Scripts/python.exe test_visuals/collect.py

It only adds what is not here yet; nothing is deleted anywhere.

1. phone/<date>/        real phone photos that reached Grasshopper (demo/inbox/, which git
                        ignores): the photo, the replies Grasshopper sent (.json), and in
                        overlays/ the photo with the reply drawn on it. sheet.jpg: all of the day.
                        Only 16:9 photos (the Pixel 8). The 4:3 ones in the inbox are the
                        real-scale test's own photos (realscale_test/round*/inputs/), sent by
                        step2_run_blind.py; they are not phone photos.
2. fake_gh/<date>/      the first phone tests (16-19 Nov), saved by python/fake_gh.py --save into
                        python/: photos/ the photos as received (layer_, candidate_), overlays/
                        what the system answered drawn on them (check_ = outlines, zone_ = zone,
                        fit_ = fit check), made smaller. sheet.jpg: all of the day.
3. realscale/roundN/    the real-scale test's screens per wall (screens_sN = the phone's screens,
                        truth_sN = the truth next to the answer), as JPG. Only the ones git does not
                        keep as PNG in realscale_test/.
"""

import json
import re
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # experiments/phone-to-gh
INBOX = ROOT / "demo" / "inbox"
FAKE_GH = ROOT / "python"
REALSCALE = ROOT / "realscale_test"

OVERLAY_WIDTH = 800       # fake_gh overlays are made smaller: they are for looking at
JPEG = [cv2.IMWRITE_JPEG_QUALITY, 85]

RED, WHITE, BLUE, GREEN, YELLOW = (0, 0, 255), (255, 255, 255), (255, 120, 0), (0, 160, 0), (0, 230, 255)
RESULT_COLOR = {"fits": (0, 200, 0)}


def stamp(name):
    m = re.search(r"(\d{8})_(\d{6})", name)
    return (m.group(1), m.group(2)) if m else (None, None)


def day(name):
    d, _ = stamp(name)
    return "%s-%s-%s" % (d[:4], d[4:6], d[6:])


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def poly(img, pts, color, width):
    if pts:
        cv2.polylines(img, [np.int32(pts).reshape(-1, 1, 2)], True, color, width, cv2.LINE_AA)


def text(img, s, xy, color, scale=0.9):
    x, y = int(xy[0]), int(xy[1])
    cv2.putText(img, s, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 5, cv2.LINE_AA)
    cv2.putText(img, s, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2, cv2.LINE_AA)


def banner(img, s):
    cv2.rectangle(img, (0, 0), (img.shape[1], 44), (30, 30, 30), -1)
    text(img, s, (10, 31), YELLOW, 0.8)


def draw_photo(img, outlines, zone):
    """Wall photo: the marker frame (x red, y green), the stones (red), the zone (white = may
    reach, blue = must cover), as the phone got them."""
    img = img.copy()
    if outlines and outlines.get("qr"):
        f = np.int32(outlines["qr"]["frame"])
        poly(img, f.tolist(), (200, 200, 200), 2)
        cv2.line(img, tuple(map(int, f[0])), tuple(map(int, f[1])), RED, 4)
        cv2.line(img, tuple(map(int, f[0])), tuple(map(int, f[3])), GREEN, 4)
    if zone:
        poly(img, zone.get("max"), WHITE, 3)
        poly(img, zone.get("min"), BLUE, 3)
    stones = (outlines or {}).get("stones", [])
    for s in stones:
        poly(img, s["outline"], RED, 3)
        x, y = np.mean(np.reshape(s["outline"], (-1, 2)), axis=0)
        text(img, str(s["id"]), (x, y), RED, 1.2)
    if outlines is None:
        msg = "no reply saved"
    else:
        msg = "%d stone(s)%s%s" % (len(stones), ", marker" if outlines.get("qr") else ", NO marker",
                                   ", zone" if zone and zone.get("max") else "")
    return img, msg


def draw_cand(img, fit):
    """Candidate photo: the stone the tap found (red) and the answer."""
    img = img.copy()
    if not fit:
        return img, "no reply saved"
    result = fit.get("result", "?")
    poly(img, fit.get("outline"), RESULT_COLOR.get(result, RED), 3)
    msg = result
    if fit.get("length_cm") is not None:
        msg += "  %.1f x %.1f cm" % (fit["length_cm"], fit.get("width_cm") or 0)
    if fit.get("need_depth_cm"):
        msg += "  (depth %.1f-%.1f)" % tuple(fit["need_depth_cm"])
    return img, msg


def sheet(tiles, path, width=420, cols=5):
    """All pictures of a day side by side, each with its name and what the system said."""
    if not tiles:
        return
    cells = []
    for img, label in tiles:
        h = int(img.shape[0] * width / img.shape[1])
        t = cv2.resize(img, (width, h), interpolation=cv2.INTER_AREA)
        t = cv2.copyMakeBorder(t, 0, 40, 0, 0, cv2.BORDER_CONSTANT, value=(30, 30, 30))
        for i, line in enumerate(label.split("\n")[:2]):
            cv2.putText(t, line[:60], (5, h + 16 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.45, YELLOW, 1, cv2.LINE_AA)
        cells.append(t)
    hmax = max(c.shape[0] for c in cells)
    cells = [cv2.copyMakeBorder(c, 0, hmax - c.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(30, 30, 30)) for c in cells]
    while len(cells) % cols:
        cells.append(np.full_like(cells[0], 30))
    rows = [np.hstack(cells[i:i + cols]) for i in range(0, len(cells), cols)]
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 80])


def copy(src, dst):
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return 1
    return 0


def phone():
    added, days = 0, {}
    for jpg in sorted(INBOX.glob("*.jpg"), key=lambda p: stamp(p.name) + (p.name,)):
        if jpg.name.endswith(".qr.jpg") or not jpg.name.startswith(("photo_", "cand_")):
            continue
        img = cv2.imread(str(jpg))
        if img is None or abs(img.shape[1] / img.shape[0] - 16 / 9) > 0.05:
            continue                     # not a phone photo (the real-scale test's 4:3 photos)
        out = HERE / "phone" / day(jpg.name)
        stem = jpg.name[:-4]
        added += copy(jpg, out / jpg.name)
        for extra in INBOX.glob(stem + ".*json"):
            added += copy(extra, out / extra.name)
        if jpg.name.startswith("photo_"):
            drawn, msg = draw_photo(img, load(INBOX / (stem + ".outlines.json")), load(INBOX / (stem + ".zone.json")))
            kind = "wall"
        else:
            drawn, msg = draw_cand(img, load(INBOX / (stem + ".fit.json")))
            kind = "new stone"
        banner(drawn, "%s  %s:  %s" % (stem, kind, msg))
        ov = out / "overlays" / (stem + ".jpg")
        if not ov.exists():
            ov.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(ov), drawn, JPEG)
            added += 1
        days.setdefault(out, []).append((drawn, "%s\n%s: %s" % (stem, kind, msg)))
    for out, tiles in days.items():
        sheet(tiles, out / "sheet.jpg")
    return added


def fake_gh():
    added, days = 0, {}
    files = sorted(FAKE_GH.glob("*.jpg"), key=lambda p: stamp(p.name) + (p.name,))
    for jpg in files:
        kind = jpg.name.split("_")[0]
        if stamp(jpg.name)[0] is None:
            continue
        out = HERE / "fake_gh" / day(jpg.name)
        img = cv2.imread(str(jpg))
        if img is None:
            continue
        if kind in ("layer", "candidate", "received"):
            added += copy(jpg, out / "photos" / jpg.name)
        else:
            dst = out / "overlays" / jpg.name
            if not dst.exists():
                small = cv2.resize(img, (OVERLAY_WIDTH, int(img.shape[0] * OVERLAY_WIDTH / img.shape[1])),
                                   interpolation=cv2.INTER_AREA)
                dst.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(dst), small, [cv2.IMWRITE_JPEG_QUALITY, 80])
                added += 1
        days.setdefault(out, []).append((img, jpg.name[:-4]))
    for out, tiles in days.items():
        sheet(tiles, out / "sheet.jpg", width=320, cols=8)
    return added


def realscale():
    added = 0
    for png in sorted(REALSCALE.glob("round*/outputs/*_s[0-9].png")):
        rnd = png.parent.parent.name
        if rnd == "round3" and png.name.startswith("truth_"):
            continue                     # kept as PNG in realscale_test/round3/outputs/
        dst = HERE / "realscale" / rnd / (png.stem + ".jpg")
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(dst), cv2.imread(str(png)), JPEG)
            added += 1
    return added


def main():
    for name, fn in (("phone", phone), ("fake_gh", fake_gh), ("realscale", realscale)):
        print("%-10s %d file(s) added" % (name, fn()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
