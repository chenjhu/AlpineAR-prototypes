"""Photo -> stones.json: the stone outlines that Grasshopper reads.

Detection is Mode 1's (../../mode1-rule-of-thirds/stone_detect.py), unchanged.
This file only writes its contours to disk, in a form Grasshopper can draw:

    python photo_to_json.py ../../photos/01_L0_AB.jpeg --ref-cm 45
    python photo_to_json.py photo.jpg --ref-cm 45 --out ../demo/stones.json

--ref-cm is the real length of the BIGGEST stone (the long side of its
outline) and turns pixels into cm. Without it everything stays in pixels.

Coordinates: origin at the photo's bottom-left corner, x to the right, y up
(the photo's y points down, Rhino's points up). Python's own area and centre
go in the file too, so Grasshopper can check it rebuilt the same shapes.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mode1-rule-of-thirds"))
from stone_detect import DetectParams, detect_stones  # noqa: E402

SIMPLIFY_PX = 1.5   # drop outline points closer than this to the line (full-res px)


def stones_to_dict(stones, image_size, px_per_unit, unit, source):
    w, h = image_size
    k = 1.0 / px_per_unit

    def xy(x, y):
        return [round(x * k, 2), round((h - y) * k, 2)]

    out = []
    for i, s in enumerate(stones):
        c = cv2.approxPolyDP(s.contour, SIMPLIFY_PX, True)
        out.append({
            "id": i,
            "area": round(cv2.contourArea(c) * k * k, 2),   # of the points written below
            "centroid": xy(*s.centroid),
            "contour": [xy(float(x), float(y)) for x, y in c.reshape(-1, 2)],
        })
    return {"source": source, "unit": unit, "px_per_unit": round(px_per_unit, 4),
            "image_size_px": [w, h], "stones": out}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path)
    parser.add_argument("--ref-cm", type=float, help="real length of the biggest stone in cm")
    parser.add_argument("--stones", type=int, default=2, help="how many stones are in the photo")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "demo" / "stones.json")
    args = parser.parse_args()

    image = cv2.imread(str(args.image))
    if image is None:
        sys.exit(f"cannot read {args.image} (HEIC? export as JPEG)")
    stones = detect_stones(image, DetectParams(stones=args.stones)).stones
    if not stones:
        sys.exit("no stones found")

    px_per_unit, unit = 1.0, "px"
    if args.ref_cm:
        px_per_unit, unit = max(stones[0].min_rect[1]) / args.ref_cm, "cm"

    h, w = image.shape[:2]
    data = stones_to_dict(stones, (w, h), px_per_unit, unit, args.image.name)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=1))
    print(f"{len(stones)} stones from {args.image.name} -> {args.out}")
    for s in data["stones"]:
        print(f"  stone {s['id']}: area {s['area']:.1f} {unit}2, {len(s['contour'])} points")


if __name__ == "__main__":
    main()
