"""The second mode, "next to a laid stone", on made-up real-scale photos
(2026-11-27). Uses step 1's painting (the round 3 stone cut-outs, a white
ground like paper, the marker) and runs the system as Grasshopper does
(replies.py with the Mode 1 venv), one folder per scene:

  placed_..._0.jpg  + .placement.json   D laid on A and B, as its placement check left it
  photo_....jpg     the layer photo in the second mode (A, B, C and D)
  cand_....jpg      the stone E at the stone stock (the fit check)
  placed_..._N.jpg  E laid next to D: good / a gap to D / pushed out of the face

The truth is measured on the flat ground plane, the rule written out again:
E touches D, covers the rest of B and 1/4 .. 3/4 of C. Also the same layer
photo with no placement check in its folder (D from the photo alone).

    python mode2_test.py            -> mode2/<scene>/..., mode2/results.json, mode2/sheet_<scene>.jpg
"""
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "python"))
import step1_make_world as w  # noqa: E402
from qr_marker import find_marker  # noqa: E402

PY = HERE.parents[1] / "mode1-rule-of-thirds" / ".venv" / "Scripts" / "python.exe"
REPLIES = HERE.parent / "python" / "replies.py"
OUT = HERE / "mode2"
CUT = HERE / "world" / "cutouts_round3"

# wall angle, photo width on the ground (cm); stones (cut-out, length, depth): A, B, C base, D laid, E new
SCENES = [
    dict(name="m1", wall=0, frame=150, A=("75", 35, 30), B=("71", 34, 29), C=("66", 37, 31),
         D=("84", 34, 31), E=("76", None, None), d_shift=-1.0),
    dict(name="m2", wall=-6, frame=130, A=("61", 31, 28), B=("85", 33, 29), C=("81", 31, 28),
         D=("70", 32, 28), E=("69", None, None), d_shift=2.0),
    dict(name="m3", wall=90, frame=130, A=("73", 23, 21), B=("63", 25, 22), C=("77", 25, 22),
         D=("74", 24, 22), E=("83", None, None), d_shift=0.0, shift=4),   # the wall runs up / down the photo
]
GAP = 0.4
PLACE = [("good", 0.2, 0.0, "ok"), ("gap", 4.0, 0.0, "move"), ("out", 0.2, -7.0, "move")]


def stone(key):
    png = cv2.imread(str(CUT / ("%s.png" % key)), cv2.IMREAD_UNCHANGED)
    return png[..., :3], png[..., 3]


def blank(ppc, ground):
    cv = w.Canvas.__new__(w.Canvas)
    cv.ppc, cv.masks, cv.img, cv.tilt = ppc, [], ground.copy(), 0.0
    return cv


def camera(rng):
    rot, scale = rng.uniform(-6, 6), rng.uniform(0.94, 1.06)
    cam = np.vstack([cv2.getRotationMatrix2D((w.W / 2, w.H / 2), rot, scale), [0, 0, 1]])
    cam[:2, 2] += rng.uniform(-0.04, 0.04, 2) * [w.W, w.H]
    return cam


def lay(cv, key, L, D, centre, ang, rng, nadir, stones):
    """A stone on top (D or E): seen a little bigger (nearer the camera), with a soft shadow."""
    k = rng.uniform(1.03, 1.06)
    seen = nadir + (centre - nadir) * k
    sh = blank(cv.ppc, np.zeros_like(cv.img))
    a = rng.uniform(0, 2 * math.pi)
    sh.paste("S", *stones[key], L * k, D * k, seen + 1.5 * np.array([math.cos(a), math.sin(a)]), ang)
    s = cv2.GaussianBlur(sh.masks[0][1].astype(np.float32) / 255, (0, 0), cv.ppc)
    cv.img *= (1 - 0.3 * s)[..., None]
    cv.paste(key, *stones[key], L * k, D * k, seen, ang)


def footprint(ppc, key, L, D, centre, ang, stones):
    f = blank(ppc, np.zeros((w.H, w.W, 3), np.float32))
    f.paste(key, *stones[key], L, D, centre, ang)
    return f.masks[0][1]


def run(*args):
    r = subprocess.run([str(PY), str(REPLIES), *map(str, args)], capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise RuntimeError(r.stderr[-1500:])
    return r.stdout.strip()


def scene(sc, rng, stones, marker):
    folder = OUT / sc["name"]
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    ppc = w.W / sc["frame"]
    fw, fh = sc["frame"], sc["frame"] * w.H / w.W
    u = np.array([math.cos(math.radians(sc["wall"])), math.sin(math.radians(sc["wall"]))])
    n = np.array([-u[1], u[0]])
    nadir = np.array([fw / 2, fh / 2])
    (ka, la, da), (kb, lb, db), (kc, lc, dc), (kd, ld, dd) = sc["A"], sc["B"], sc["C"], sc["D"]
    # the course: B's middle near the photo's middle, faces in line (n = 0)
    face = nadir - n * 12
    cb = face + n * db / 2 + u * sc.get("shift", -6)
    ca = cb - u * (lb / 2 + GAP + la / 2)
    cc = cb + u * (lb / 2 + GAP + lc / 2)
    j_ab = cb - u * (lb / 2 + GAP / 2)
    cd = j_ab + u * sc["d_shift"] + n * 0 + (face - j_ab) @ n * n + n * dd / 2   # on the A|B joint, in the face
    angs = {k: sc["wall"] + rng.uniform(-1.5, 1.5) for k in "ABCD"}
    ground = w.Canvas(None, sc["frame"], 0).img
    mk_centre = face + n * (max(da, db, dc, dd) + 14) + u * rng.uniform(-8, 8)   # clear of the stones
    mk_ang = rng.uniform(0, 360)

    def base(cv):
        for k, (key, L, D), c in (("A", sc["A"], ca), ("B", sc["B"], cb), ("C", sc["C"], cc)):
            cv.paste(k, *stones[key], L, D, c, angs[k])

    flat = {k: footprint(ppc, key, L, D, c, angs[k], stones)
            for k, (key, L, D), c in (("A", sc["A"], ca), ("B", sc["B"], cb), ("C", sc["C"], cc), ("D", sc["D"], cd))}
    t = {k: w.plane_cm(m, ppc) @ u for k, m in flat.items()}
    nn = {k: w.plane_cm(m, ppc) @ n for k, m in flat.items()}
    J = 0.5 * (t["B"].max() + t["C"].min())
    start = float(t["D"].max())
    y = float(t["C"].max() - J)
    r_b = J - start
    truth = {"J": J, "start": start, "r_B": r_b, "L_C": y,
             "length_cm": [r_b + y / 4, r_b + 3 * y / 4],
             "depth_cm": 0.5 * (float(np.ptp(nn["B"][t["B"] >= start])) + w.sides_cm(flat["C"], ppc)[1])}

    def shot(extra, rng_cam):
        cv = blank(ppc, ground)
        base(cv)
        lay(cv, kd, ld, dd, cd, angs["D"], rng, nadir, stones)
        if extra:
            extra(cv)
        cv.paste_marker(marker, mk_centre, mk_ang)
        return cv.finish(rng=rng, camera=camera(rng_cam))

    # 1. D's placement check, as the system left it (outline from the true mask, cm via the marker)
    img0, m0 = shot(None, rng)
    p0 = folder / "placed_20261127_120000.jpg"
    cv2.imwrite(str(p0), img0, [cv2.IMWRITE_JPEG_QUALITY, 90])
    cnt = max(cv2.findContours(m0[kd], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)
    out0 = cv2.approxPolyDP(cnt, 2.0, True).reshape(-1, 2)
    mk0 = find_marker(img0, 10)
    (folder / "placed_20261127_120000.placement.json").write_text(json.dumps(
        {"result": "ok", "outline": out0.tolist(), "outline_cm": mk0.to_cm(out0).round(1).tolist()}))
    # 2. the layer photo, phone held a little differently
    img1, _ = shot(None, rng)
    p1 = folder / "photo_20261127_120100.jpg"
    cv2.imwrite(str(p1), img1, [cv2.IMWRITE_JPEG_QUALITY, 90])
    log = {"layer": run(p1, "--ts", 1.0, "--stones", 2, "--ref-cm", 45, "--mode", "next_to")}
    zone = json.loads((folder / "photo_20261127_120100.zone.json").read_text())
    res = {"truth": truth, "zone": zone, "log": log}
    wall = zone.get("wall_cm")
    if wall:
        # lengths only: the system's frame is the marker's, the truth's the ground plane's
        res["err"] = {"r_B": wall["x"] - r_b, "L_C": wall["y"] - y,
                      "length_lo": zone["length_cm"][0] - truth["length_cm"][0],
                      "length_hi": zone["length_cm"][1] - truth["length_cm"][1],
                      "depth": 0.5 * sum(zone["depth_range_cm"]) - truth["depth_cm"]}
    # 3. the same photo with no placement check next to it: D from the photo alone
    alone = folder / "alone"
    alone.mkdir()
    shutil.copy(p1, alone / p1.name)
    log_alone = run(alone / p1.name, "--ts", 1.0, "--stones", 2, "--ref-cm", 45, "--mode", "next_to")
    za = json.loads((alone / "photo_20261127_120100.zone.json").read_text())
    res["alone"] = {"log": log_alone, "note": za["note"],
                    "r_B": za["wall_cm"]["x"] if za.get("wall_cm") else None}
    if not wall:
        return res, folder, img1, zone, []
    # 4. E: as long as the middle of its range, as deep as wanted
    ke = sc["E"][0]
    le, de = 0.5 * sum(truth["length_cm"]), truth["depth_cm"]
    cc_ = w.Canvas(None, w.CANDIDATE_FRAME, 0)
    cfw, cfh = w.CANDIDATE_FRAME, w.CANDIDATE_FRAME * w.H / w.W
    cc_.paste("E", *stones[ke], le, de, np.array([cfw * 0.5, cfh * 0.42]), rng.uniform(-20, 20))
    cc_.paste_marker(marker, np.array([cfw * 0.5 + 8, cfh * 0.78]), rng.uniform(0, 360))
    cimg, _ = cc_.finish(rng=rng)
    pc = folder / "cand_20261127_120200.jpg"
    cv2.imwrite(str(pc), cimg, [cv2.IMWRITE_JPEG_QUALITY, 90])
    log["cand"] = run(pc, "--ts", 2.0, "--layer-ts", 1.0, "--zone", folder / "photo_20261127_120100.zone.json")
    res["fit"] = json.loads((folder / "cand_20261127_120200.fit.json").read_text())["result"]
    # 5. E laid next to D
    placed = []
    for i, (why, gap, across, expect) in enumerate(PLACE, 1):
        ce = (start + gap + le / 2) * u + ((face @ n) + de / 2 + across) * n
        ang_e = sc["wall"] + rng.uniform(-2, 2)
        fe = footprint(ppc, ke, le, de, ce, ang_e, stones)
        te = w.plane_cm(fe, ppc) @ u
        img2, _ = shot(lambda cv: lay(cv, ke, le, de, ce, ang_e, rng, nadir, stones), rng)
        p2 = folder / ("placed_20261127_1203%02d.jpg" % i)
        cv2.imwrite(str(p2), img2, [cv2.IMWRITE_JPEG_QUALITY, 90])
        run(p2, "--ts", 3.0 + i, "--placed", "--layer-ts", 1.0, "--zone", folder / "photo_20261127_120100.zone.json",
            "--cand", pc)
        pm = json.loads((folder / (p2.stem + ".placement.json")).read_text())
        placed.append({"photo": p2.name, "why": why, "expected": expect, "got": pm["result"],
                       "true_gap_to_D": float(te.min() - start),
                       "true_cover_C": float((te.max() - J) / y),
                       "move_along": pm["move_along_cm"], "move_across": pm["move_across_cm"],
                       "note": pm["note"][:120], "msg": pm, "img": img2})
    res["placed"] = [{k: v for k, v in p.items() if k not in ("msg", "img")} for p in placed]
    return res, folder, img1, zone, placed


def draw_sheet(name, img1, zone, placed, outlines):
    tiles = []
    a = img1.copy()
    for s in outlines.get("stones", []):
        cv2.polylines(a, [np.int32(s["outline"]).reshape(-1, 1, 2)], True, (0, 0, 255), 3)
    for key, col in (("max", (255, 255, 255)), ("min", (255, 120, 0))):
        if zone.get(key):
            cv2.polylines(a, [np.int32(zone[key]).reshape(-1, 1, 2)], True, col, 3)
    cv2.putText(a, "layer: L %s cm" % zone.get("length_cm"), (20, 50), 0, 1.4, (0, 0, 0), 3)
    tiles.append(a)
    for p in placed:
        b = p["img"].copy()
        m = p["msg"]
        for key, col in (("max", (255, 255, 255)), ("min", (255, 120, 0))):
            if m.get(key):
                cv2.polylines(b, [np.int32(m[key]).reshape(-1, 1, 2)], True, col, 2)
        if m.get("outline"):
            cv2.polylines(b, [np.int32(m["outline"]).reshape(-1, 1, 2)], True,
                          (0, 200, 0) if m["result"] == "ok" else (0, 200, 255), 3)
        if m.get("arrow"):
            cv2.arrowedLine(b, tuple(m["arrow"][0]), tuple(m["arrow"][1]), (0, 200, 255), 4, tipLength=0.25)
        cv2.putText(b, "%s: want %s, got %s" % (p["why"], p["expected"], p["got"]), (20, 50), 0, 1.4, (0, 0, 0), 3)
        tiles.append(b)
    small = [cv2.resize(t, (640, 480)) for t in tiles]
    while len(small) % 2:
        small.append(np.full_like(small[0], 255))
    rows = [np.hstack(small[i:i + 2]) for i in range(0, len(small), 2)]
    cv2.imwrite(str(OUT / ("sheet_%s.jpg" % name)), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])


def main():
    w.RNG = np.random.default_rng(20261127)
    w.PAPER.update({"grain": 10.0, "blotch": 5.0})
    rng = np.random.default_rng(20261128)
    marker = cv2.imread(str(HERE / "world" / "marker_tracker10.png"))
    keys = {sc[k][0] for sc in SCENES for k in "ABCDE"}
    stones = {k: stone(k) for k in keys}
    OUT.mkdir(exist_ok=True)
    allres = {}
    for sc in SCENES:
        res, folder, img1, zone, placed = scene(sc, rng, stones, marker)
        outlines = json.loads((folder / "photo_20261127_120100.outlines.json").read_text())
        draw_sheet(sc["name"], img1, zone, placed, outlines)
        allres[sc["name"]] = res
        t = res["truth"]
        print("%s: truth r_B %.1f L_C %.1f -> length %.1f-%.1f | zone %s note '%s'" % (
            sc["name"], t["r_B"], t["L_C"], *t["length_cm"], zone.get("length_cm"), zone.get("note")))
        if "err" in res:
            print("    error cm: " + ", ".join("%s %+.1f" % kv for kv in res["err"].items()))
        print("    laid: %s" % zone.get("laid"))
        print("    alone: r_B %s, %s" % (res["alone"]["r_B"], res["alone"]["note"] or "ok"))
        if "fit" in res:
            print("    candidate: %s" % res["fit"])
        for p in res.get("placed", []):
            print("    %-5s want %-4s got %-10s (gap to D %.1f, covers C %.2f, move %s/%s) %s" % (
                p["why"], p["expected"], p["got"], p["true_gap_to_D"], p["true_cover_C"],
                p["move_along"], p["move_across"], p["note"][:70]))
    (OUT / "results.json").write_text(json.dumps(allres, indent=1, default=float))


if __name__ == "__main__":
    main()
