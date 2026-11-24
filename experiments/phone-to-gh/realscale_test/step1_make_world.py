"""Step 1 of the real-scale test: build the "world" (2026-11-24).

Makes photos of dry-stone-wall stones at their real size, as the phone
would take them, from CC0 photos of rock specimens (Wikimedia Commons,
GeoDIL) and CC0 ground textures (see world/SOURCES.md):

  inputs/       what the phone gives the system: the photos and the taps.
                Step 2 reads only this folder.
  sealed_truth/ the true stones (masks, sizes in cm), the true zone and the
                expected fit result. Written here, read only by step 3.

Isolation: this script imports nothing of the system (no replies.py, no
rule_of_thirds.py, no stone_detect.py). The stones are cut from their
photos with their own plain background, the truth zone is computed with
the slides' formula written out again below, and the marker texture is
cut from a real phone photo once (world/marker_tracker10.png, made with
--make-marker, which uses qr_marker.py only to find the marker's corners).

    python step1_make_world.py --round round2 --stones DIR [--grounds DIR]

Round 1: textured grounds, stones as they come. Round 2 (the prototype's
set-up, 2026-11-24): a plain white ground, near-square blocks of about the
same size, laid in line with almost no gap.
Each round writes to its own folder: <round>/inputs, <round>/sealed_truth.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
W, H = 1280, 960            # the photo the phone sends (long side 1280 px, 4:3)
PAPER_CM = 14.8             # the marker's paper, cut on its crop marks
RNG = np.random.default_rng(20261124)
WHITE = None                # ground = None: a plain white ground
PAPER = {"grain": 6.0, "blotch": 0.0}   # the white ground's grain and slow unevenness (set per round)


# ---------------------------------------------------------------- the stones
def cut_stone(path):
    """A specimen photo -> (BGR, mask) of the stone alone. The background is
    one plain colour (black, white or blue): it is learned from the photo's
    border and everything far from it in Lab is stone."""
    img = cv2.imread(str(path))
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    border = np.concatenate([lab[:6].reshape(-1, 3), lab[-6:].reshape(-1, 3),
                             lab[:, :6].reshape(-1, 3), lab[:, -6:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    spread = np.percentile(np.linalg.norm(border - bg, axis=1), 90)
    dist = np.linalg.norm(lab - bg, axis=2)
    fg = (dist > max(18.0, 2.5 * spread)).astype(np.uint8) * 255
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab_cc, stats, _ = cv2.connectedComponentsWithStats(fg)
    big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = np.uint8(lab_cc == big) * 255
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    mask = np.zeros_like(mask)
    cv2.drawContours(mask, cnts, -1, 255, cv2.FILLED)        # fill holes
    mask = cv2.erode(mask, np.ones((5, 5), np.uint8))       # drop the background's rim
    # The specimens carry a teal number sticker: paint it over with the stone.
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    sticker = cv2.inRange(hsv, (80, 90, 60), (105, 255, 255)) & mask
    sticker = cv2.dilate(sticker, np.ones((9, 9), np.uint8)) & mask
    img = cv2.inpaint(img, sticker, 7, cv2.INPAINT_TELEA)
    return img, mask


def upright(img, mask):
    """Turn the stone so its minimum-area rectangle is axis-aligned, long side
    along x; crop to it. Returns (BGR, mask)."""
    cnt = max(cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)
    (cx, cy), (rw, rh), ang = cv2.minAreaRect(cnt)
    if rw < rh:
        ang += 90
        rw, rh = rh, rw
    pad = int(max(img.shape[:2]))
    big_img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    big_mask = cv2.copyMakeBorder(mask, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    M = cv2.getRotationMatrix2D((cx + pad, cy + pad), ang, 1.0)
    size = big_img.shape[1::-1]
    r_img = cv2.warpAffine(big_img, M, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    r_mask = cv2.warpAffine(big_mask, M, size, flags=cv2.INTER_LINEAR)
    x0, y0 = int(cx + pad - rw / 2), int(cy + pad - rh / 2)
    return r_img[y0:y0 + int(rh), x0:x0 + int(rw)], r_mask[y0:y0 + int(rh), x0:x0 + int(rw)]


# ------------------------------------------------------------------ painting
class Canvas:
    """One photo: the ground plane in cm (x right, y down in the photo), seen
    from above at `ppc` pixels per cm, then a small camera tilt."""

    def __init__(self, ground, frame_cm, tilt_deg=0.0):
        self.ppc = W / frame_cm
        self.masks = []          # (name, mask uint8) in plane pixels
        self.tilt = tilt_deg
        if ground is None:
            # White paper / a white floor: near white with a faint grain.
            grain = cv2.GaussianBlur(RNG.normal(0, PAPER["grain"], (H, W)).astype(np.float32), (0, 0), 2.0)
            if PAPER["blotch"]:
                # Real paper / a floor is not lit evenly: slow, irregular unevenness.
                slow = cv2.GaussianBlur(RNG.normal(0, 1, (H, W)).astype(np.float32), (0, 0), 60)
                grain += PAPER["blotch"] * slow / (slow.std() + 1e-6)
            self.img = np.dstack([np.full((H, W), v, np.float32) + grain for v in (236, 238, 240)])
            return
        g = cv2.imread(str(ground), cv2.IMREAD_COLOR)
        k = max(W / g.shape[1], H / g.shape[0]) * RNG.uniform(1.0, 1.3)
        g = cv2.resize(g, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        y0, x0 = RNG.integers(0, g.shape[0] - H + 1), RNG.integers(0, g.shape[1] - W + 1)
        self.img = g[y0:y0 + H, x0:x0 + W].astype(np.float32)
        if RNG.random() < 0.5:
            self.img = self.img[:, ::-1].copy()

    def px(self, x_cm, y_cm):
        return x_cm * self.ppc, y_cm * self.ppc

    def paste(self, name, bgr, mask, length_cm, depth_cm, centre_cm, angle_deg):
        """The stone `bgr`/`mask` (upright, long side along x), scaled to
        length x depth cm, turned by angle_deg, its centre at centre_cm."""
        lw, dh = max(2, round(length_cm * self.ppc)), max(2, round(depth_cm * self.ppc))
        s_img = cv2.resize(bgr, (lw, dh), interpolation=cv2.INTER_AREA).astype(np.float32)
        s_mask = cv2.resize(mask, (lw, dh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
        cx, cy = self.px(*centre_cm)
        M = cv2.getRotationMatrix2D((lw / 2, dh / 2), -angle_deg, 1.0)
        M[:, 2] += (cx - lw / 2, cy - dh / 2)
        warped = cv2.warpAffine(s_img, M, (W, H), flags=cv2.INTER_LINEAR)
        alpha = cv2.warpAffine(s_mask, M, (W, H), flags=cv2.INTER_LINEAR)
        alpha = cv2.GaussianBlur(alpha, (3, 3), 0.6)[..., None]
        self.img = self.img * (1 - alpha) + warped * alpha
        self.masks.append((name, np.uint8(alpha[..., 0] > 0.5) * 255))

    def paste_marker(self, marker, centre_cm, angle_deg):
        side = round(PAPER_CM * self.ppc)
        m = cv2.resize(marker, (side, side), interpolation=cv2.INTER_AREA).astype(np.float32)
        cx, cy = self.px(*centre_cm)
        M = cv2.getRotationMatrix2D((side / 2, side / 2), -angle_deg, 1.0)
        M[:, 2] += (cx - side / 2, cy - side / 2)
        warped = cv2.warpAffine(m, M, (W, H), flags=cv2.INTER_LINEAR)
        alpha = cv2.warpAffine(np.ones((side, side), np.float32), M, (W, H))[..., None]
        self.img = self.img * (1 - alpha) + warped * alpha
        self.masks.append(("marker", np.uint8(alpha[..., 0] > 0.5) * 255))

    def finish(self):
        """Light falling off to one side, sensor noise, a little blur, the
        camera tilt; returns (photo BGR uint8, {name: mask})."""
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        a = RNG.uniform(0, 2 * math.pi)
        light = 1.0 + 0.12 * ((xx / W - 0.5) * math.cos(a) + (yy / H - 0.5) * math.sin(a))
        r2 = ((xx - W / 2) / W) ** 2 + ((yy - H / 2) / H) ** 2
        img = self.img * (light * (1 - 0.25 * r2))[..., None]
        img = cv2.GaussianBlur(img, (0, 0), 0.7) + RNG.normal(0, 2.5, img.shape)
        img = np.clip(img, 0, 255).astype(np.uint8)
        masks = dict(self.masks)
        if self.tilt:
            # A camera tipped by `tilt` degrees about the photo's x axis: the
            # far side of the ground gets smaller (a plain keystone).
            t = math.tan(math.radians(self.tilt)) * 0.6
            src = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
            dst = np.float32([[W * t / 2, 0], [W * (1 - t / 2), 0], [W, H], [0, H]])
            Hm = cv2.getPerspectiveTransform(src, dst)
            img = cv2.warpPerspective(img, Hm, (W, H), borderMode=cv2.BORDER_REFLECT)
            masks = {k: cv2.warpPerspective(m, Hm, (W, H), flags=cv2.INTER_NEAREST) for k, m in masks.items()}
        return img, masks


# --------------------------------------------------------------------- truth
def sides_cm(mask, ppc):
    """The true stone's minimum-area rectangle, cm (long, short). Measured on
    the flat plane (before the tilt)."""
    cnt = max(cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)
    (_, _), (a, b), _ = cv2.minAreaRect(cnt)
    return max(a, b) / ppc, min(a, b) / ppc


def span_along(mask, ppc, u):
    ys, xs = np.nonzero(mask)
    t = (xs * u[0] + ys * u[1]) / ppc
    return float(t.min()), float(t.max())


def slide_zone(mask_a, mask_b, ppc, wall_deg):
    """The slides' quarter rule, written out on its own: x, y = how far each
    stone reaches from the joint line J (middle of the gap) along the wall;
    the next stone's length z: x/4 + y/4 <= z <= 3x/4 + 3y/4; its depth: the
    average of the two stones' depths +- 10 %."""
    u = (math.cos(math.radians(wall_deg)), math.sin(math.radians(wall_deg)))
    a_lo, a_hi = span_along(mask_a, ppc, u)
    b_lo, b_hi = span_along(mask_b, ppc, u)
    J = 0.5 * (a_hi + b_lo)
    x, y = J - a_lo, b_hi - J
    da, db = sides_cm(mask_a, ppc)[1], sides_cm(mask_b, ppc)[1]
    d = 0.5 * (da + db)
    return {"x_cm": x, "y_cm": y, "gap_cm": b_lo - a_hi,
            "length_cm": [x / 4 + y / 4, 3 * x / 4 + 3 * y / 4],
            "depth_range_cm": [0.9 * d, 1.1 * d], "depths_cm": [da, db]}


def expected_fit(a, b, length, depth):
    """Same question as the phone asks: long side along the wall, or else the
    other way round."""
    def problem(along, across):
        if along < length[0]:
            return "too_short"
        if along > length[1]:
            return "too_long"
        if across < depth[0]:
            return "too_shallow"
        if across > depth[1]:
            return "too_deep"
        return "fits"
    first = problem(a, b)
    return "fits" if first != "fits" and problem(b, a) == "fits" else first


def tap_point(mask):
    """Where a person taps: well inside the stone (its most inner point)."""
    d = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    y, x = np.unravel_index(np.argmax(d), d.shape)
    return [int(x), int(y)]


# --------------------------------------------------------------------- world
# Real dry-stone-wall sizes (cm). frame = how wide the photo is on the ground
# (phone ~1 m up: ~110 cm; ~1.6 m up: ~190 cm).
ROUND1 = [
    dict(name="s1", ground="Gray_Gravel_.jpg", frame=110, tilt=0, wall=0,
         a=("13", 38, 24), b=("21", 33, 27), gap=1.5),
    dict(name="s2", ground="Dirt_diff_8k.png", frame=150, tilt=8, wall=-12,
         a=("01", 46, 30), b=("17", 29, 23), gap=3.0),
    dict(name="s3", ground="Ground084_8K.png", frame=190, tilt=0, wall=6,
         a=("15", 35, 25), b=("18", 41, 28), gap=2.0),
    dict(name="s4", ground="Ground_dirt_.jpg", frame=150, tilt=4, wall=0,
         a=("04", 40, 26), b=("11", 36, 22), gap=1.0),
]
# Round 2: stones not used in round 1 (world/sources/stones2), near-square
# blocks of about the same size, faces in line, gap 0.3-0.6 cm, white ground.
ROUND2 = [
    dict(name="s1", ground=WHITE, frame=110, tilt=0, wall=0,
         a=("55", 34, 30), b=("54", 32, 29), gap=0.4),
    dict(name="s2", ground=WHITE, frame=130, tilt=0, wall=-8,
         a=("52", 38, 31), b=("51", 36, 30), gap=0.3),
    dict(name="s3", ground=WHITE, frame=150, tilt=0, wall=5,
         a=("57", 33, 28), b=("34", 35, 29), gap=0.6),
    dict(name="s4", ground=WHITE, frame=150, tilt=6, wall=0,
         a=("42", 36, 32), b=("36", 34, 30), gap=0.5),
]
# Round 3: like round 2, with stones not used before (world/sources/stones3),
# and a white ground as uneven as real paper (its spread ~1.5, see replies.is_plain).
ROUND3 = [
    dict(name="s1", ground=WHITE, frame=110, tilt=0, wall=3,
         a=("75", 35, 30), b=("71", 33, 29), gap=0.4),
    dict(name="s2", ground=WHITE, frame=130, tilt=5, wall=-6,
         a=("66", 37, 31), b=("84", 36, 32), gap=0.3),
    dict(name="s3", ground=WHITE, frame=150, tilt=0, wall=0,
         a=("76", 34, 29), b=("61", 36, 30), gap=0.5),
    dict(name="s4", ground=WHITE, frame=150, tilt=6, wall=8,
         a=("85", 38, 32), b=("81", 35, 30), gap=0.6),
]
ROUNDS = {
    "round1": dict(scenes=ROUND1, candidates=["02", "08", "09", "10", "12", "14", "16", "19", "20"],
                   face_play=1.0, turn_play=3.0, seed=20261124),
    "round2": dict(scenes=ROUND2, candidates=["46", "41", "38", "56", "48", "44", "40", "49"],
                   face_play=0.3, turn_play=1.5, seed=20261125),
    "round3": dict(scenes=ROUND3, candidates=["70", "69", "77", "74", "83", "67", "73", "63"],
                   face_play=0.3, turn_play=1.5, seed=20261126, paper={"grain": 10.0, "blotch": 5.0}),
}
CANDIDATE_FRAME = 100       # phone ~0.9 m above one stone on the ground


def candidate_sizes(zone):
    """Stones a builder could pick up, chosen against the true zone: one that
    fits, one just inside the depth range, one too deep, one too long."""
    lo, hi = zone["length_cm"]
    dlo, dhi = zone["depth_range_cm"]
    mid_d = 0.5 * (dlo + dhi)
    return [("fits", min(hi - 3, max(lo + 3, 0.5 * (lo + hi))), mid_d),
            ("edge", 0.5 * (lo + hi), dlo + 0.6),
            ("deep", 0.5 * (lo + hi), dhi * 1.25),
            ("long", hi * 1.15, mid_d)]


def make_marker(photo, out):
    import sys
    sys.path.insert(0, str(HERE.parent / "python"))
    from qr_marker import find_marker
    img = cv2.imread(str(photo))
    mk = find_marker(img, 10)
    ppc, m = 30, 0.0
    dst = np.float32([[0, 0], [PAPER_CM, 0], [PAPER_CM, PAPER_CM], [0, PAPER_CM]]) * ppc
    src = mk.to_px(np.float32([[m, m], [PAPER_CM - m, m], [PAPER_CM - m, PAPER_CM - m], [m, PAPER_CM - m]]))
    # cm frame: y up in the QR's view; the image's rows run down, so flip y.
    side = round(PAPER_CM * ppc)
    Hm = cv2.getPerspectiveTransform(np.float32(src), dst[[3, 2, 1, 0]])
    cv2.imwrite(str(out), cv2.warpPerspective(img, Hm, (side, side)))
    print("marker ->", out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--round", default="round2", choices=sorted(ROUNDS))
    ap.add_argument("--stones", type=Path, help="folder of specimen photos NN.jpg")
    ap.add_argument("--grounds", type=Path, help="folder of ground textures")
    ap.add_argument("--make-marker", type=Path, help="a real photo with the marker: cut it out and stop")
    a = ap.parse_args()
    world = HERE / "world"
    world.mkdir(exist_ok=True)
    if a.make_marker:
        return make_marker(a.make_marker, world / "marker_tracker10.png")

    global RNG
    cfg = ROUNDS[a.round]
    RNG = np.random.default_rng(cfg["seed"])
    PAPER.update(cfg.get("paper", {}))
    inputs, truth = HERE / a.round / "inputs", HERE / a.round / "sealed_truth"
    inputs.mkdir(parents=True, exist_ok=True)
    truth.mkdir(parents=True, exist_ok=True)
    marker = cv2.imread(str(world / "marker_tracker10.png"))
    stones = {p.stem: upright(*cut_stone(p)) for p in sorted(a.stones.glob("*.jpg"))}
    cuts = world / ("cutouts_" + a.round)
    cuts.mkdir(exist_ok=True)
    for k, (img, mask) in stones.items():
        cv2.imwrite(str(cuts / ("%s.png" % k)), np.dstack([img, mask]))

    taps, all_truth = {}, {}
    cand_pool = list(cfg["candidates"])
    ground = lambda name: None if name is WHITE else a.grounds / name
    for sc in cfg["scenes"]:
        cv = Canvas(ground(sc["ground"]), sc["frame"], sc["tilt"])
        fw, fh = sc["frame"], sc["frame"] * H / W
        u = np.array([math.cos(math.radians(sc["wall"])), math.sin(math.radians(sc["wall"]))])
        n = np.array([-u[1], u[0]])
        (ka, la, da), (kb, lb, db) = sc["a"], sc["b"]
        joint = np.array([fw * 0.5, fh * 0.42])
        # Faces in line (the wall's face, n = 0), a little play as in a real wall.
        fp, tp = cfg["face_play"], cfg["turn_play"]
        ca = joint - u * (sc["gap"] / 2 + la / 2) + n * (da / 2 + RNG.uniform(-fp, fp))
        cb = joint + u * (sc["gap"] / 2 + lb / 2) + n * (db / 2 + RNG.uniform(-fp, fp))
        cv.paste("A", *stones[ka], la, da, ca, sc["wall"] + RNG.uniform(-tp, tp))
        cv.paste("B", *stones[kb], lb, db, cb, sc["wall"] + RNG.uniform(-tp, tp))
        flat = {k: m.copy() for k, m in cv.masks}
        cv.paste_marker(marker, joint - n * 22 + u * RNG.uniform(-10, 10), RNG.uniform(0, 360))
        photo, masks = cv.finish()
        name = "%s_layer.jpg" % sc["name"]
        cv2.imwrite(str(inputs / name), photo, [cv2.IMWRITE_JPEG_QUALITY, 90])
        zone = slide_zone(flat["A"], flat["B"], cv.ppc, sc["wall"])
        rec = {"photo": name, "frame_cm": fw, "px_per_cm": cv.ppc, "tilt_deg": sc["tilt"],
               "wall_deg": sc["wall"], "ground": sc["ground"],
               "stones": {k: {"source": s, "made_cm": [l, d], "true_cm": list(sides_cm(flat[k], cv.ppc))}
                          for k, (s, l, d) in (("A", sc["a"]), ("B", sc["b"]))},
               "zone": zone, "candidates": []}
        for k, m in masks.items():
            cv2.imwrite(str(truth / ("%s_layer_%s.png" % (sc["name"], k))), m)

        for i, (why, L, D) in enumerate(candidate_sizes(zone), 1):
            key = cand_pool.pop(0)
            cand_pool.append(key)
            cc = Canvas(ground(sc["ground"]), CANDIDATE_FRAME, RNG.choice([0, 0, 5]))
            cfw, cfh = CANDIDATE_FRAME, CANDIDATE_FRAME * H / W
            centre = np.array([cfw * RNG.uniform(0.42, 0.58), cfh * RNG.uniform(0.35, 0.5)])
            ang = RNG.uniform(-25, 25)
            cc.paste("C", *stones[key], L, D, centre, ang)
            flat_c = cc.masks[0][1].copy()
            cc.paste_marker(marker, centre + np.array([RNG.uniform(-12, 12), cfh * 0.33]), RNG.uniform(0, 360))
            photo, masks = cc.finish()
            cname = "%s_cand%d.jpg" % (sc["name"], i)
            cv2.imwrite(str(inputs / cname), photo, [cv2.IMWRITE_JPEG_QUALITY, 90])
            for k, m in masks.items():
                cv2.imwrite(str(truth / ("%s_cand%d_%s.png" % (sc["name"], i, k))), m)
            ta, tb = sides_cm(flat_c, cc.ppc)
            taps[cname] = tap_point(masks["C"])
            rec["candidates"].append({"photo": cname, "why": why, "source": key, "made_cm": [L, D],
                                      "true_cm": [ta, tb], "px_per_cm": cc.ppc, "tilt_deg": float(cc.tilt),
                                      "expected": expected_fit(ta, tb, zone["length_cm"], zone["depth_range_cm"])})
        all_truth[sc["name"]] = rec

    (inputs / "taps.json").write_text(json.dumps(taps, indent=1))
    (inputs / "layers.json").write_text(json.dumps(
        {sc["name"]: {"layer": "%s_layer.jpg" % sc["name"],
                      "candidates": ["%s_cand%d.jpg" % (sc["name"], i) for i in range(1, 5)]} for sc in cfg["scenes"]},
        indent=1))
    t = json.dumps(all_truth, indent=1)
    (truth / "truth.json").write_text(t)
    (truth / "truth.sha256").write_text(hashlib.sha256(t.encode()).hexdigest() + "\n")
    print("inputs ->", inputs, "| sealed truth ->", truth)
    for s, r in all_truth.items():
        z = r["zone"]
        print("%s: %.1f px/cm  A %s  B %s  zone L %.1f-%.1f D %.1f-%.1f  | %s" % (
            s, r["px_per_cm"], fmt(r["stones"]["A"]["true_cm"]), fmt(r["stones"]["B"]["true_cm"]),
            *z["length_cm"], *z["depth_range_cm"],
            ", ".join("%s %s=%s" % (c["photo"][-9:-4], fmt(c["true_cm"]), c["expected"]) for c in r["candidates"])))


def fmt(v):
    return "%.1fx%.1f" % tuple(v)


if __name__ == "__main__":
    main()
