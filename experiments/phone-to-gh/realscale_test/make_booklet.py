"""Step-by-step pictures of one real-scale run for the booklet (2026-11-25).

Reads what the last run of the standard test wrote (round 3: inputs/,
outputs/replies.json = what the real system answered, sealed_truth/ for the
last picture) and draws, for one wall:

  01_stones          the CC0 rock photos and the stones cut from them
  02_wall_photo      the photo of the layer, as the phone sends it
  03_outlines        the stones the system found + the phone's question
  04_zone            the zone (contour + hatch) + the size on the phone + Preview
  05_candidates      four stones checked at the stone stock, as the phone shows them
  06_placement       the stone laid four ways and the system's answer
  08_accuracy        the system's outlines against the true stones, and the numbers

(07 is a screenshot of Rhino, taken separately.)

    ../python/.venv/Scripts/python.exe make_booklet.py --wall s1 --out <folder>
"""
import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

import step3_compare as s3
from step3_compare import Screen, contour_of, font, iou, poly_mask

HERE = Path(__file__).resolve().parent
RND = HERE / "round3"
W = 2400                       # figure width, px
BG = "white"
INK, GREY = (20, 20, 20), (110, 110, 110)


def title(img, head, sub=""):
    """A figure with a title and a line under it on top."""
    top = 150 if sub else 100
    out = Image.new("RGB", (img.width, img.height + top), BG)
    out.paste(img, (0, top))
    d = ImageDraw.Draw(out)
    d.text((40, 28), head, font=font(s3.MED, 52), fill=INK)
    if sub:
        d.text((40, 96), sub, font=font(s3.REG, 32), fill=GREY)
    return out


def row(images, gap=40, height=None, captions=None):
    """Images side by side at one height, each with a caption under it."""
    if height:
        images = [im.resize((round(im.width * height / im.height), height)) for im in images]
    cap_h = 70 if captions else 0
    hh = max(im.height for im in images)
    out = Image.new("RGB", (sum(im.width for im in images) + gap * (len(images) + 1), hh + cap_h + gap), BG)
    x = gap
    d = ImageDraw.Draw(out)
    for i, im in enumerate(images):
        out.paste(im, (x, 0))
        if captions:
            d.text((x, hh + 14), captions[i], font=font(s3.REG, 30), fill=INK)
        x += im.width + gap
    return out


def fit_width(img, width=W):
    if img.width <= width:
        out = Image.new("RGB", (width, img.height), BG)
        out.paste(img, ((width - img.width) // 2, 0))
        return out
    return img.resize((width, round(img.height * width / img.width)))


def pil(bgr):
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def save(img, path):
    img.save(path, quality=92)
    print("->", path.name, img.size)


def phone(screen):
    return screen.img.convert("RGB")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--wall", default="s1")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    out = a.out
    out.mkdir(parents=True, exist_ok=True)
    s3.INP, s3.TRUTH, s3.OUT = RND / "inputs", RND / "sealed_truth", RND / "outputs"
    rp = json.loads((RND / "outputs" / "replies.json").read_text())[a.wall]
    tr = json.loads((RND / "sealed_truth" / "truth.json").read_text())[a.wall]
    inp = RND / "inputs"
    layer_path = inp / tr["photo"]
    layer = cv2.imread(str(layer_path))
    outlines, zone = rp["outlines"], rp["zone"]
    pre = "%s_" % a.wall

    # 01 the stones: CC0 photo -> cut out, for the two base stones and the stone that is laid
    tiles, caps = [], []
    for role, key in (("base stone A", tr["stones"]["A"]["source"]), ("base stone B", tr["stones"]["B"]["source"]),
                      ("new stone", tr["placements"][0]["source"])):
        src = cv2.imread(str(HERE / "world" / "sources" / "stones3" / ("%s.jpg" % key)))
        cut = cv2.imread(str(HERE / "world" / "cutouts_round3" / ("%s.png" % key)), cv2.IMREAD_UNCHANGED)
        rgba = cv2.cvtColor(cut, cv2.COLOR_BGRA2RGBA)
        canvas = Image.new("RGB", (rgba.shape[1], rgba.shape[0]), (236, 238, 240))
        canvas.paste(Image.fromarray(rgba), (0, 0), Image.fromarray(rgba))
        tiles += [pil(src), canvas]
        caps += ["%s: rock photo no. %s" % (role, key), "cut out from its background"]
    fig = row(tiles, height=360, captions=[c[:34] for c in caps])
    save(title(fit_width(fig), "1  The stones",
               "CC0 rock specimens (GeoDIL, Wikimedia Commons), cut out and scaled to real wall-stone sizes (30-40 cm)"),
         out / (pre + "01_stones.jpg"))

    # 02 the photo the phone sends
    img = pil(layer)
    save(title(fit_width(img.resize((1600, 1200))), "2  The photo of the layer",
               "As the phone sends it: 1280 x 960 px, %d cm wide on the ground, the QR marker for the scale" %
               round(tr["frame_cm"])), out / (pre + "02_wall_photo.jpg"))

    # 03 the outlines the system found, and the phone's question
    v = layer.copy()
    f = np.int32(outlines["qr"]["frame"])
    cv2.polylines(v, [f.reshape(-1, 1, 2)], True, (200, 200, 200), 2)
    cv2.line(v, tuple(map(int, f[0])), tuple(map(int, f[1])), (0, 0, 255), 4)
    cv2.line(v, tuple(map(int, f[0])), tuple(map(int, f[3])), (0, 160, 0), 4)
    for st in outlines["stones"]:
        cv2.polylines(v, [np.int32(st["outline"]).reshape(-1, 1, 2)], True, (0, 0, 255), 4)
    sc = Screen(layer_path)
    for st in outlines["stones"]:
        sc.outline(st["outline"], (255, 0, 0, 255), 3)
    sc.card("Use these two stones?", [("Yes", True), ("No", False)])
    fig = row([pil(v), phone(sc)], height=1200,
              captions=["Grasshopper: two outlines, the marker frame (x red, y green)", "the phone"])
    save(title(fit_width(fig), "3  The stones found",
               "Detected in Grasshopper %.1f s after the photo was sent; the outlines go back to the phone" %
               rp["outlines_s"]), out / (pre + "03_outlines.jpg"))

    # 04 the zone
    v = layer.copy()
    for st in outlines["stones"]:
        cv2.polylines(v, [np.int32(st["outline"]).reshape(-1, 1, 2)], True, (0, 0, 255), 3)
    m = np.zeros(layer.shape[:2], np.uint8)
    cv2.fillPoly(m, [np.int32(zone["min"])], 255)
    yy, xx = np.mgrid[0:m.shape[0], 0:m.shape[1]]
    hatch = (m > 0) & (((xx + yy) % 12) < 3)
    v[hatch] = (255, 128, 26)
    cv2.polylines(v, [np.int32(zone["min"]).reshape(-1, 1, 2)], True, (255, 128, 26), 2)
    cv2.polylines(v, [np.int32(zone["max"]).reshape(-1, 1, 2)], True, (255, 255, 255), 4)
    s2 = Screen(layer_path)
    s2.size_panel(zone["length_cm"], zone["depth_range_cm"])
    s2.card("Find a stone fitting to the requirements, then tap on it to check it", [("Preview", False), ("New photo", False)])
    s4 = Screen(layer_path)
    for st in outlines["stones"]:
        s4.outline(st["outline"], (255, 0, 0, 255), 3)
    s4.outline(zone["max"], (255, 255, 255, 255), 2)
    s4.hatch(zone["min"], (26, 128, 255, 255))
    s4.card("Align the red outlines with your stones, then place the new stone so it covers the hatched area "
            "without crossing the white outline.", [("Back", False), ("Check placement", True)])
    fig = row([pil(v), phone(s2), phone(s4)], height=1200,
              captions=["white: may reach   hatched: must cover", "after Yes: the size", "Preview: where it goes"])
    save(title(fit_width(fig), "4  Where the next stone goes",
               "Quarter rule: length %.0f-%.0f cm along the wall, depth %.0f-%.0f cm (average of the two +-10 %%)" % (
                   *zone["length_cm"], *zone["depth_range_cm"])), out / (pre + "04_zone.jpg"))

    # 05 the candidates, each as the phone shows it
    tiles, caps = [], []
    for c, ct in zip(rp["candidates"], tr["candidates"]):
        fit = c["fit"]
        sc = Screen(inp / c["photo"])
        sc.tap(*c["tap"])
        ok = fit["result"] == "fits"
        sc.outline(fit["outline"], (0, 255, 0, 255) if ok else (255, 0, 0, 255), 3)
        sc.size_panel(zone["length_cm"], zone["depth_range_cm"], (fit["result"], fit["along_cm"], fit["across_cm"]))
        sc.card("This stone fits.\nTap Preview to preview the placement" if ok
                else "Wrong size. Try another stone or shape it", [("Preview", ok), ("New photo", False)])
        tiles.append(phone(sc))
        caps.append("%s: %s" % (fit["result"].replace("_", " "), "%.0f x %.0f cm" % (fit["length_cm"], fit["width_cm"])))
    fig = row(tiles, height=1200, captions=caps)
    save(title(fit_width(fig), "5  Checking stones at the stone stock",
               "Tap a stone on the screen: it is photographed with the marker, measured and checked against the size"),
         out / (pre + "05_candidates.jpg"))

    # 06 after placing
    tiles, caps = [], []
    for c, pt in zip(rp.get("placed", []), tr["placements"]):
        msg = c["placement"]
        sc = Screen(inp / c["photo"])
        for b in msg.get("base") or []:
            sc.outline(b, (255, 0, 0, 255), 3)
        sc.outline(msg["max"], (255, 255, 255, 255), 2)
        sc.hatch(msg["min"], (26, 128, 255, 255))
        ok = msg["result"] == "ok"
        sc.outline(msg["outline"], (0, 255, 0, 255) if ok else (255, 214, 10, 255), 3)
        if msg.get("arrow"):
            sc.arrow(msg["arrow"][0], msg["arrow"][1], (255, 214, 10, 255))
        n = math.hypot(msg["move_along_cm"] or 0, msg["move_across_cm"] or 0)
        sc.card("Well placed. Tap Next stone for the next one" if ok else
                "Move the stone about %d cm the way the arrow shows, then check again" % round(n),
                [("Check again", not ok), ("Next stone", ok)])
        tiles.append(phone(sc))
        laid = {"good": "laid in the middle", "along": "shifted 4 cm along the wall",
                "out": "7 cm out of the wall face", "turned": "in the middle, turned 5 deg"}[pt["why"]]
        caps.append("%s -> %s" % (laid, "ok" if ok else "move %d cm" % round(n)))
    fig = row(tiles, height=1200, captions=caps)
    save(title(fit_width(fig), "6  Checking the stone after it is laid",
               "Tap the new stone: it is found by its own texture, checked against the zone, and an arrow says where to move it"),
         out / (pre + "06_placement.jpg"))

    # 08 accuracy: true stones (cyan) vs system (red), and the numbers of all four walls
    v = layer.copy()
    shape = layer.shape[:2]
    ious = []
    for k in ("A", "B"):
        tm = cv2.imread(str(RND / "sealed_truth" / ("%s_layer_%s.png" % (a.wall, k))), 0)
        cv2.drawContours(v, [np.int32(contour_of(tm))], -1, (255, 255, 0), 5)
        ious.append(max(iou(poly_mask(st["outline"], shape), tm) for st in outlines["stones"]))
    for st in outlines["stones"]:
        cv2.polylines(v, [np.int32(st["outline"]).reshape(-1, 1, 2)], True, (0, 0, 255), 3)
    res = json.loads((RND / "outputs" / "results.json").read_text())
    lines = []
    cand_r = cand_n = pl_r = pl_n = 0
    for wall, r in res.items():
        cr = sum(c["expected"] == c["result"] for c in r["candidates"])
        pr = sum(c["right"] for c in r.get("placed", []))
        cand_r += cr
        cand_n += len(r["candidates"])
        pl_r += pr
        pl_n += len(r.get("placed", []))
        lines.append("%s   stones found %.0f %% / %.0f %%   length true %s, system %s cm   candidates %d/4   placements %d/4" % (
            wall, 100 * r["iou"]["A"], 100 * r["iou"]["B"], s3.rng(r["true_length"]), s3.rng(r["sys_length"]), cr, pr))
    panel = Image.new("RGB", (1300, 1200), BG)
    d = ImageDraw.Draw(panel)
    d.text((0, 0), "All four walls of the test (round 3)", font=font(s3.MED, 40), fill=INK)
    y = 80
    for ln in lines:
        parts = ln.split("   ")
        for p in parts:
            d.text((0, y), p, font=font(s3.REG, 30), fill=INK if p is parts[0] else GREY)
            y += 42
        y += 24
    d.text((0, y + 10), "candidates right: %d of %d" % (cand_r, cand_n), font=font(s3.MED, 36), fill=INK)
    d.text((0, y + 60), "placements right: %d of %d" % (pl_r, pl_n), font=font(s3.MED, 36), fill=INK)
    d.text((0, y + 130), "The truth is kept apart: the system never sees it.", font=font(s3.REG, 28), fill=GREY)
    fig = row([pil(v).resize((1600, 1200)), panel], height=1200,
              captions=["cyan: true stones   red: found by the system (overlap %.0f %%, %.0f %%)" % (100 * ious[0], 100 * ious[1]), ""])
    save(title(fit_width(fig), "8  How exact",
               "Compared with the true stones of the test world, which were sealed before the system ran"),
         out / (pre + "08_accuracy.jpg"))


if __name__ == "__main__":
    main()
