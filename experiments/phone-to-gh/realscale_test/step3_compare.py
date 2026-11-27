"""Step 3 of the real-scale test: open the sealed truth, compare, draw.

Reads outputs/replies.json (what the system answered in step 2) and
sealed_truth/ (step 1). Writes:

  outputs/screens_<scene>.png   the phone's screens, as the phone draws them
                                (same layout numbers as OutlineReview / AlpineUI)
  outputs/truth_<scene>.png     the system's outlines (red) on the true stones (cyan),
                                and each candidate stone with its result
  outputs/results.json          the numbers of REPORT.md

    python step3_compare.py --round round2
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
INP, TRUTH, OUT = HERE / "inputs", HERE / "sealed_truth", HERE / "outputs"

# ------------------------------------------------------------ phone drawing
SW, SH = 1080, 2400                          # Pixel 8 screen
h = round(SH * 0.065)                        # AlpineUI.ButtonHeight
REG, MED = r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\seguisb.ttf"
CARD, GLASS, BLUE = (28, 28, 31, 199), (43, 43, 46, 209), (10, 132, 255, 255)
GREEN, RED, DIM = (48, 209, 88), (255, 69, 58), (255, 255, 255, 140)


def font(path, size):
    return ImageFont.truetype(path, max(8, round(size)))


class Screen:
    """The photo as the phone shows it: turned for portrait, scaled to fill
    the screen, centred (OutlineReview.TurnFor / ScreenToPhoto)."""

    def __init__(self, photo_path):
        photo = cv2.imread(str(photo_path))
        self.ph, self.pw = photo.shape[:2]
        self.k = max(SW / self.ph, SH / self.pw)
        rot = cv2.resize(cv2.rotate(photo, cv2.ROTATE_90_COUNTERCLOCKWISE), None, fx=self.k, fy=self.k)
        y0, x0 = (rot.shape[0] - SH) // 2, (rot.shape[1] - SW) // 2
        self.y0, self.x0 = y0, x0
        self.img = Image.fromarray(cv2.cvtColor(rot[y0:y0 + SH, x0:x0 + SW], cv2.COLOR_BGR2RGB)).convert("RGBA")

    def pt(self, x, y):
        dx, dy = (x - self.pw / 2) * self.k, (y - self.ph / 2) * self.k
        return SW / 2 + dy, SH / 2 - dx

    def layer(self):
        ov = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        return ov, ImageDraw.Draw(ov)

    def put(self, ov):
        self.img = Image.alpha_composite(self.img, ov)

    def outline(self, pts, color, width_px):
        if not pts:
            return
        ov, d = self.layer()
        p = [self.pt(*q) for q in pts]
        d.line(p + p[:1], fill=color, width=max(1, round(width_px * self.k)), joint="curve")
        self.put(ov)

    def hatch(self, pts, color, spacing=8, width=2):
        """OutlineReview.DrawHatch: 45-degree lines inside the outline (photo
        pixels, counted with y up like the texture) and a 1 px edge."""
        if not pts:
            return
        m = np.zeros((self.ph, self.pw), np.uint8)
        cv2.fillPoly(m, [np.int32(np.round(pts))], 1)
        yy, xx = np.mgrid[0:self.ph, 0:self.pw]
        m = (m.astype(bool) & (((xx + (self.ph - 1 - yy)) % spacing) < width)).astype(np.uint8)
        big = cv2.resize(cv2.rotate(m, cv2.ROTATE_90_COUNTERCLOCKWISE), None, fx=self.k, fy=self.k,
                         interpolation=cv2.INTER_NEAREST)[self.y0:self.y0 + SH, self.x0:self.x0 + SW]
        rgba = np.zeros((SH, SW, 4), np.uint8)
        rgba[big > 0] = color
        self.put(Image.fromarray(rgba, "RGBA"))
        self.outline(pts, color, 1)

    def arrow(self, a, b, color):
        """An arrow from photo point a to b (OutlineReview.DrawArrow)."""
        ov, d = self.layer()
        (x0, y0), (x1, y1) = self.pt(*a), self.pt(*b)
        wdt = 8
        d.line((x0, y0, x1, y1), fill=color, width=wdt)
        ang = math.atan2(y1 - y0, x1 - x0)
        head = 40
        for da in (2.6, -2.6):
            d.line((x1, y1, x1 + head * math.cos(ang + da), y1 + head * math.sin(ang + da)), fill=color, width=wdt)
        self.put(ov)

    def tap(self, x, y):
        ov, d = self.layer()
        cx, cy = self.pt(x, y)
        r = h * 0.25
        d.line((cx - r, cy, cx + r, cy), fill=(255, 51, 255, 255), width=6)
        d.line((cx, cy - r, cx, cy + r), fill=(255, 51, 255, 255), width=6)
        self.put(ov)

    def card(self, message, buttons):
        ov, d = self.layer()
        lx, ly, lw, lh = SW * 0.05, SH * 0.70, SW * 0.9, h * 1.3
        d.rounded_rectangle((lx, ly, lx + lw, ly + lh), radius=h * 0.32, fill=CARD)
        f = font(REG, h * 0.27)
        lines, cur = [], ""
        for wd in message.split():
            if d.textlength((cur + " " + wd).strip(), font=f) > lw - 2 * h * 0.32:
                lines.append(cur)
                cur = wd
            else:
                cur = (cur + " " + wd).strip()
        lines.append(cur)
        step = h * 0.36
        y0 = ly + lh / 2 - step * (len(lines) - 1) / 2
        for i, s in enumerate(lines):
            d.text((lx + lw / 2, y0 + i * step), s, font=f, fill=(255, 255, 255, 242), anchor="mm")
        by, gap = ly + lh + h * 0.25, SW * 0.03
        bw = (lw - gap) / 2
        for i, (label, primary) in enumerate(buttons):
            x = lx + i * (bw + gap)
            d.rounded_rectangle((x, by, x + bw, by + h), radius=h / 2, fill=BLUE if primary else GLASS)
            d.text((x + bw / 2, by + h / 2), label, font=font(MED, h * 0.27), fill="white", anchor="mm")
        self.put(ov)

    def size_panel(self, need_l, need_d, fit=None):
        """OutlineReview.DrawSizePanel. fit = (result, along, across) or None."""
        ov, d = self.layer()
        top = max(h * 0.3 + 80, SH * 0.085)
        px, pw, ph = SW * 0.05, SW * 0.78, h * 3.5
        d.rounded_rectangle((px, top, px + pw, top + ph), radius=h * 0.32, fill=CARD)
        pad = h * 0.4
        d.text((px + pad, top + h * 0.22), "NEXT STONE", font=font(MED, h * 0.19), fill=DIM)
        mid_l, mid_d = sum(need_l) / 2, sum(need_d) / 2
        ratio = min(3, max(0.5, mid_l / max(mid_d, 0.1)))
        ax, ay, aw, ah = px + pad, top + h * 0.75, pw * 0.34, h * 2.3
        maxw, maxh = aw - h * 0.45, ah - h * 0.45
        sw = min(maxw, maxh * ratio)
        sh = sw / ratio
        sx, sy = ax + (maxw - sw) / 2, ay + (maxh - sh) / 2
        checked, fits = fit is not None, fit is not None and fit[0] == "fits"
        fill = (255, 255, 255, 41) if not checked else (GREEN + (89,) if fits else RED + (89,))
        d.rounded_rectangle((sx, sy, sx + sw, sy + sh), radius=h * 0.16, fill=fill)
        lw_, tick, lc = max(2, h * 0.02), h * 0.1, (255, 255, 255, 153)
        ly = sy + sh + h * 0.22
        d.rectangle((sx, ly - lw_ / 2, sx + sw, ly + lw_ / 2), fill=lc)
        d.rectangle((sx, ly - tick, sx + lw_, ly + tick), fill=lc)
        d.rectangle((sx + sw - lw_, ly - tick, sx + sw, ly + tick), fill=lc)
        dx = sx + sw + h * 0.22
        d.rectangle((dx - lw_ / 2, sy, dx + lw_ / 2, sy + sh), fill=lc)
        d.rectangle((dx - tick, sy, dx + tick, sy + lw_), fill=lc)
        d.rectangle((dx - tick, sy + sh - lw_, dx + tick, sy + sh), fill=lc)
        tx = ax + aw + h * 0.3

        def block(y, label, need, measured):
            small, big = h * 0.19, h * 0.5
            d.text((tx, y), label, font=font(MED, small), fill=DIM)
            y += small * 1.45
            rng = "%s–%s" % (cm(need[0]), cm(need[1]))
            d.text((tx, y), rng, font=font(MED, big), fill=(255, 255, 255))
            rw = d.textlength(rng, font=font(MED, big))
            d.text((tx + rw + h * 0.08, y + big * 0.5), "cm", font=font(REG, small * 1.2), fill=DIM)
            y += big * 1.2
            if checked:
                ok = need[0] <= measured <= need[1]
                d.text((tx, y), "this stone %s" % cm(measured), font=font(MED, small * 1.15),
                       fill=GREEN if ok else RED)
            return y + small * 1.5

        y = block(top + h * 0.72, "LENGTH · along the wall", need_l, fit[1] if fit else 0)
        block(y + h * 0.15, "DEPTH · into the wall", need_d, fit[2] if fit else 0)
        self.put(ov)

    def tile(self, title, wide=540):
        img = self.img.convert("RGB").resize((wide, round(wide * SH / SW)))
        d = ImageDraw.Draw(img)
        d.rectangle((0, img.height - 50, wide, img.height), fill=(255, 255, 255))
        d.text((12, img.height - 42), title, font=font(MED, 26), fill=(0, 0, 0))
        return img


def cm(v):
    return "%.1f" % v if v < 10 else "%.0f" % v


# --------------------------------------------------------------- comparing
def poly_mask(pts, shape):
    m = np.zeros(shape, np.uint8)
    if pts:
        cv2.fillPoly(m, [np.int32(pts)], 255)
    return m


def iou(a, b):
    a, b = a > 0, b > 0
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 0.0


def contour_of(mask):
    cs = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    return max(cs, key=cv2.contourArea).reshape(-1, 2).tolist() if cs else []


def rng(v):
    return "%.1f–%.1f" % tuple(v) if v else "—"


def sheet(tiles, cols, pad=20):
    w, hh = tiles[0].width, max(t.height for t in tiles)
    rows = math.ceil(len(tiles) / cols)
    out = Image.new("RGB", (cols * w + (cols - 1) * pad, rows * hh + (rows - 1) * pad), "white")
    for i, t in enumerate(tiles):
        out.paste(t, ((i % cols) * (w + pad), (i // cols) * (hh + pad)))
    return out


def label(img, lines, width):
    """Text under an image tile."""
    f = font(REG, 22)
    out = Image.new("RGB", (width, img.height + 30 * len(lines) + 16), "white")
    out.paste(img, (0, 0))
    d = ImageDraw.Draw(out)
    for i, (s, col) in enumerate(lines):
        d.text((10, img.height + 8 + 30 * i), s, font=f, fill=col)
    return out


def main():
    global INP, TRUTH, OUT
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--round", default="round2")
    rnd = HERE / ap.parse_args().round
    INP, TRUTH, OUT = rnd / "inputs", rnd / "sealed_truth", rnd / "outputs"
    t = (TRUTH / "truth.json").read_text()
    assert hashlib.sha256(t.encode()).hexdigest() == (TRUTH / "truth.sha256").read_text().strip(), "truth changed"
    truth = json.loads(t)
    replies = json.loads((OUT / "replies.json").read_text())
    results = {}
    for scene, tr in truth.items():
        rp = replies[scene]
        layer = INP / tr["photo"]
        shape = cv2.imread(str(layer)).shape[:2]
        outl = rp.get("outlines") or {"stones": []}
        sys_polys = [s["outline"] for s in outl["stones"]]
        true_masks = {k: cv2.imread(str(TRUTH / ("%s_layer_%s.png" % (scene, k))), 0) for k in ("A", "B")}
        stone_iou = {k: max([iou(poly_mask(p, shape), m) for p in sys_polys] or [0]) for k, m in true_masks.items()}
        zone = rp.get("zone") or {}
        res = {"px_per_cm": tr["px_per_cm"], "frame_cm": tr["frame_cm"], "tilt_deg": tr["tilt_deg"],
               "found_outlines": len(sys_polys), "iou": stone_iou,
               "true_stones_cm": {k: v["true_cm"] for k, v in tr["stones"].items()},
               "true_length": tr["zone"]["length_cm"], "true_depth": tr["zone"]["depth_range_cm"],
               "sys_length": zone.get("length_cm"), "sys_depth": zone.get("depth_range_cm"),
               "zone_note": zone.get("note"), "candidates": []}

        # Screens: 1 outlines + Yes/No, 2 after Yes, 3 a checked stone, 4 Preview.
        tiles = []
        s1 = Screen(layer)
        for p in sys_polys:
            s1.outline(p, (255, 0, 0, 255), 3)
        n = len(sys_polys)
        s1.card("Use this stone?" if n == 1 else "Use these two stones?" if n == 2 else "Use these %d stones?" % n,
                [("Yes", True), ("No", False)])
        tiles.append(s1.tile("1  %d outlines: use these stones?" % n))
        s2 = Screen(layer)
        if zone.get("note"):
            s2.card("No zone: %s" % zone["note"], [("Preview", False), ("New photo", False)])
        elif zone.get("length_cm"):
            s2.size_panel(zone["length_cm"], zone["depth_range_cm"])
            s2.card("Find a stone fitting to the requirements, then tap on it to check it",
                    [("Preview", False), ("New photo", False)])
        else:
            s2.card("No size without the QR marker in the photo. Take the photo again with it",
                    [("Preview", False), ("New photo", False)])
        tiles.append(s2.tile("2  after Yes: the size"))

        cand_tiles = []
        place_tiles, place_truth = [], []
        shown = False
        for c, ct in zip(rp.get("candidates", []), tr["candidates"]):
            fit = c["fit"]
            cpath = INP / c["photo"]
            cshape = cv2.imread(str(cpath)).shape[:2]
            cmask = cv2.imread(str(TRUTH / ("%s_C.png" % c["photo"][:-4])), 0)
            ciou = iou(poly_mask(fit["outline"], cshape), cmask) if fit and fit["outline"] else 0.0
            got = fit["result"] if fit else "no answer"
            res["candidates"].append({"photo": c["photo"], "why": ct["why"], "true_cm": ct["true_cm"],
                                      "expected": ct["expected"], "result": got,
                                      "sys_cm": [fit["length_cm"], fit["width_cm"]] if fit else None,
                                      "note": fit["note"] if fit else "no reply within 30 s",
                                      "iou": ciou, "seconds": c["fit_s"]})
            # The phone's screen for one checked stone (the first with an answer, else the first).
            if not shown and (fit or c is rp["candidates"][-1]):
                s3 = Screen(cpath)
                s3.tap(*c["tap"])
                if fit and fit["result"] not in ("unknown",):
                    ok = fit["result"] == "fits"
                    s3.outline(fit["outline"], (0, 255, 0, 255) if ok else (255, 0, 0, 255), 3)
                    s3.size_panel(zone["length_cm"], zone["depth_range_cm"],
                                  (fit["result"], fit["along_cm"], fit["across_cm"]))
                    s3.card("This stone fits. Tap Preview to preview the placement" if ok
                            else "Wrong size. Try another stone or shape it",
                            [("Preview", ok), ("New photo", False)])
                elif fit:
                    if zone.get("length_cm"):
                        s3.size_panel(zone["length_cm"], zone["depth_range_cm"])
                    s3.card("No check: %s. Tap the stone again" % fit["note"],
                            [("Preview", False), ("New photo", False)])
                else:
                    if zone.get("length_cm"):
                        s3.size_panel(zone["length_cm"], zone["depth_range_cm"])
                    s3.card("No answer from Grasshopper, tap the stone again",
                            [("Preview", False), ("New photo", False)])
                tiles.append(s3.tile("3  tapped %s: %s" % (c["photo"][3:-4], got)))
                shown = True

            # Truth tile for every candidate.
            img = cv2.imread(str(cpath))
            cv2.drawContours(img, [np.int32(contour_of(cmask))], -1, (255, 255, 0), 2)
            if fit and fit["outline"]:
                ok = fit["result"] == "fits"
                cv2.polylines(img, [np.int32(fit["outline"])], True, (0, 220, 0) if ok else (0, 0, 255), 3)
            tx, ty = map(int, c["tap"])
            cv2.drawMarker(img, (tx, ty), (255, 0, 255), cv2.MARKER_CROSS, 40, 4)
            tile = Image.fromarray(cv2.cvtColor(cv2.resize(img, (480, 360)), cv2.COLOR_BGR2RGB))
            exp_ok = ct["expected"] == got
            cand_tiles.append(label(tile, [
                ("%s (%s): true %.1f x %.1f cm -> %s" % (c["photo"][3:-4], ct["why"], *ct["true_cm"], ct["expected"]),
                 (0, 0, 0)),
                ("system: %s%s" % (got, ", %.1f x %.1f cm" % (fit["length_cm"], fit["width_cm"])
                                   if fit and fit["length_cm"] else ""), (0, 140, 0) if exp_ok else (200, 0, 0)),
                (((fit["note"] if fit else "") or ("no reply: the check crashed" if not fit else ""))[:52],
                 (90, 90, 90))], 480))

        # After placing (messages 7-8): the wall again, the new stone checked.
        res["placed"] = []
        for c, pt in zip(rp.get("placed", []), tr.get("placements", [])):
            msg = c["placement"]
            ppath = INP / c["photo"]
            pshape = cv2.imread(str(ppath)).shape[:2]
            pmask = cv2.imread(str(TRUTH / ("%s_C.png" % c["photo"][:-4])), 0)
            piou = iou(poly_mask(msg["outline"], pshape), pmask) if msg and msg["outline"] else 0.0
            got = msg["result"] if msg else "no answer"
            ang = None
            if msg and msg.get("arrow") and pt["expected"] == "move":
                va = np.subtract(msg["arrow"][1], msg["arrow"][0])
                vb = np.subtract(pt["move_px"][1], pt["move_px"][0])
                ang = math.degrees(math.acos(np.clip(va @ vb / (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-9), -1, 1)))
            near = abs(pt["slack_cm"]) < 1.5   # within the measurement: either answer is right
            right = (got == pt["expected"] and (ang is None or ang < 45)) or (near and got in ("ok", "move"))
            res["placed"].append({"photo": c["photo"], "why": pt["why"], "expected": pt["expected"],
                                  "slack_cm": pt["slack_cm"], "result": got, "near": near, "right": right,
                                  "true_move_cm": pt["move_cm"],
                                  "sys_move_cm": [msg["move_along_cm"], msg["move_across_cm"]] if msg else None,
                                  "arrow_off_deg": ang, "iou": piou,
                                  "note": msg["note"] if msg else "no reply within 30 s", "seconds": c["placement_s"]})
            # the phone's screen after "Check placement", for each placed photo
            s5 = Screen(ppath)
            if msg and msg["max"]:
                s5.outline(msg["max"], (255, 255, 255, 255), 2)
                s5.hatch(msg["min"], (26, 128, 255, 255))
            if msg and msg["outline"]:
                s5.outline(msg["outline"], (0, 255, 0, 255) if got == "ok" else (255, 0, 0, 255), 3)
            if msg and msg.get("arrow"):
                s5.arrow(msg["arrow"][0], msg["arrow"][1], (255, 214, 10, 255))
            if got == "ok":
                text = "Well placed. Tap Next stone for the next one"
            elif got == "move":
                text = "Move the stone about %d cm the way the arrow shows, then check again" % round(
                    math.hypot(msg["move_along_cm"], msg["move_across_cm"]))
            elif msg:
                text = "No check: %s" % msg["note"]
            else:
                text = "No answer from Grasshopper, check again"
            s5.card(text, [("Check again", got != "ok"), ("Next stone", got == "ok")])
            place_tiles.append(s5.tile("5  %s (%s): %s" % (c["photo"][3:-4], pt["why"], got)))
            # truth tile
            img = cv2.imread(str(ppath))
            cv2.drawContours(img, [np.int32(contour_of(pmask))], -1, (255, 255, 0), 2)
            if msg and msg["outline"]:
                cv2.polylines(img, [np.int32(msg["outline"])], True, (0, 220, 0) if got == "ok" else (0, 0, 255), 3)
            if msg and msg.get("arrow"):
                cv2.arrowedLine(img, tuple(msg["arrow"][0]), tuple(msg["arrow"][1]), (0, 0, 255), 4, tipLength=0.25)
            if pt["expected"] == "move":
                cv2.arrowedLine(img, tuple(map(int, pt["move_px"][0])), tuple(map(int, pt["move_px"][1])),
                                (255, 255, 0), 3, tipLength=0.25)
            tile = Image.fromarray(cv2.cvtColor(cv2.resize(img, (480, 360)), cv2.COLOR_BGR2RGB))
            place_truth.append(label(tile, [
                ("%s (%s): true -> %s (%s %.1f cm), move %.1f / %.1f cm" % (
                    c["photo"][3:-4], pt["why"], pt["expected"], "slack" if pt["slack_cm"] >= 0 else "off",
                    abs(pt["slack_cm"]), *pt["move_cm"]), (0, 0, 0)),
                ("system: %s%s, overlap %.0f%%%s" % (
                    got, ", move %.1f / %.1f cm" % (msg["move_along_cm"], msg["move_across_cm"]) if got == "move" else "",
                    100 * piou, ", arrow off %.0f deg" % ang if ang is not None else ""),
                 (0, 140, 0) if right else (200, 0, 0)),
                ((msg["note"] if msg else "no reply")[:60], (90, 90, 90))], 480))

        s4 = Screen(layer)
        for p in sys_polys:
            s4.outline(p, (255, 0, 0, 255), 3)
        s4.outline(zone.get("max") or [], (255, 255, 255, 255), 2)      # allowed zone: a contour
        s4.hatch(zone.get("min") or [], (26, 128, 255, 255))             # must zone: a hatch
        s4.card("Align the red outlines with your stones, then place the new stone so it covers the hatched "
                "area without crossing the white outline.", [("Back", False), ("Check placement", True)])
        tiles.append(s4.tile("4  Preview"))
        sheet(tiles, 4).save(OUT / ("screens_%s.png" % scene))
        if place_tiles:
            sheet(place_tiles, 4).save(OUT / ("screens_placed_%s.png" % scene))

        # Truth sheet: the layer (true = cyan, system = red, zone boxes) + the candidates.
        img = cv2.imread(str(layer))
        for k, m in true_masks.items():
            cv2.drawContours(img, [np.int32(contour_of(m))], -1, (255, 255, 0), 2)
        for p in sys_polys:
            cv2.polylines(img, [np.int32(p)], True, (0, 0, 255), 2)
        for key, col in (("max", (255, 255, 255)), ("min", (255, 128, 26))):
            if zone.get(key):
                cv2.polylines(img, [np.int32(zone[key])], True, col, 2)
        top = Image.fromarray(cv2.cvtColor(cv2.resize(img, (960, 720)), cv2.COLOR_BGR2RGB))
        top = label(top, [
            ("%s  photo %d cm wide on the ground (%.1f px/cm), camera tilt %d deg" % (
                scene, tr["frame_cm"], tr["px_per_cm"], tr["tilt_deg"]), (0, 0, 0)),
            ("true stones A %.1f x %.1f, B %.1f x %.1f cm  |  system outlines: %d, overlap with A %.0f%%, B %.0f%%" % (
                *tr["stones"]["A"]["true_cm"], *tr["stones"]["B"]["true_cm"], len(sys_polys),
                100 * stone_iou["A"], 100 * stone_iou["B"]), (0, 0, 0)),
            ("length  true %s  system %s cm   |   depth  true %s  system %s cm%s" % (
                rng(tr["zone"]["length_cm"]), rng(zone.get("length_cm")), rng(tr["zone"]["depth_range_cm"]),
                rng(zone.get("depth_range_cm")), ("   (" + zone["note"] + ")") if zone.get("note") else ""),
             (0, 0, 0)),
            ("cyan = true stone, red = system outline, white / orange = system zone boxes", (90, 90, 90))], 960)
        cands = sheet(cand_tiles + place_truth, 2)
        out = Image.new("RGB", (max(top.width, cands.width), top.height + cands.height + 20), "white")
        out.paste(top, (0, 0))
        out.paste(cands, (0, top.height + 20))
        out.save(OUT / ("truth_%s.png" % scene))
        results[scene] = res
        print(scene, "done")
    (OUT / "results.json").write_text(json.dumps(results, indent=1))
    summary(results)


def summary(results):
    """The numbers to compare between runs of the standard test."""
    right = total = 0
    for scene, r in results.items():
        print("%s  outlines %d, overlap A %.0f%% B %.0f%% | length true %s system %s | depth true %s system %s" % (
            scene, r["found_outlines"], 100 * r["iou"]["A"], 100 * r["iou"]["B"], rng(r["true_length"]),
            rng(r["sys_length"]), rng(r["true_depth"]), rng(r["sys_depth"])))
        for c in r["candidates"]:
            total += 1
            right += c["expected"] == c["result"]
            print("   %s %-5s true %.1f x %.1f -> %-11s system %-11s %s" % (
                c["photo"][3:8], c["why"], *c["true_cm"], c["expected"], c["result"],
                "%.1f x %.1f" % tuple(c["sys_cm"]) if c["sys_cm"] and c["sys_cm"][0] else ""))
    print("candidates right: %d of %d" % (right, total))
    pr = pt = 0
    for scene, r in results.items():
        for c in r.get("placed", []):
            pt += 1
            pr += c["right"]
            print("   %s %-6s true %-4s (%s %.1f) system %-7s %s overlap %.0f%%%s" % (
                c["photo"][3:10], c["why"], c["expected"], "slack" if c["slack_cm"] >= 0 else "off",
                abs(c["slack_cm"]), c["result"],
                "move %.1f/%.1f" % tuple(c["sys_move_cm"]) if c["result"] == "move" else "",
                100 * c["iou"], ", arrow off %.0f deg" % c["arrow_off_deg"] if c["arrow_off_deg"] is not None else ""))
    if pt:
        print("placements right: %d of %d" % (pr, pt))


if __name__ == "__main__":
    main()
