"""Run Mode 1 (rule of thirds) on top-view photos and save every step as images.

    python demo_image.py samples/scene_two_stones.png
    python demo_image.py photos/*.jpg --ref-cm 40        # stone 1 is 40 cm long
    python demo_image.py photo.jpg --click               # click each stone first
    python demo_image.py before.jpg --after after.jpg    # check a placed stone

Writes to output/: <name>_steps.png (all steps in one grid, for the slides),
<name>_ar.png (final overlay) and <name>.json (the virtual box numbers).
"""
import argparse
import json
import sys
from pathlib import Path

import cv2

import overlay
from rule_of_thirds import check_marked_points, check_placement, compute_thirds, pick_base_pair
from stone_detect import DetectParams, align_to, detect_placed_stone, detect_stones

CLICK_VIEW_WIDTH = 1200   # phone photos are too big for the screen


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("images", type=Path, nargs="+",
                        help="top-view photo(s) of the two base stones")
    parser.add_argument("--after", type=Path,
                        help="photo after placing the next stone (phone may move a bit)")
    parser.add_argument("--mark-ends", action="store_true",
                        help="with --after: click around the new stone's outline instead of "
                             "detecting it (for same-colour stones); the verdict updates live")
    parser.add_argument("--out-dir", type=Path, default=Path("output"))
    parser.add_argument("--ref-cm", type=float,
                        help="real length of stone 1 along the wall in cm (enables cm labels)")
    parser.add_argument("--click", action="store_true",
                        help="click once on each stone before detection (robust mode)")
    parser.add_argument("--ground-thresh", type=float,
                        help="fixed ground/stone threshold 0-255 instead of Otsu")
    parser.add_argument("--show", action="store_true", help="also open a window")
    args = parser.parse_args()
    if args.after and len(args.images) > 1:
        parser.error("--after works with a single 'before' image")
    return args


def read(path: Path):
    image = cv2.imread(str(path))
    if image is None:
        raise FileNotFoundError(f"cannot read image {path} (HEIC? export as JPEG)")
    return image


def click_seeds(image, window="click each stone, Enter = done, z = undo"
                ) -> list[tuple[float, float]]:
    s = min(1.0, CLICK_VIEW_WIDTH / image.shape[1])
    small = cv2.resize(image, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    seeds = []

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN:
            seeds.append((x, y))

    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)
    while True:
        view = small.copy()
        for i, (x, y) in enumerate(seeds):
            cv2.circle(view, (x, y), 8, overlay.STONE_COLORS[i % 4], -1)
        cv2.imshow(window, view)
        key = cv2.waitKey(20) & 0xFF
        if key in (13, 10):
            break
        if key == ord("z") and seeds:
            seeds.pop()
        if key in (27, ord("q")):
            raise RuntimeError("cancelled")
    close_window(window)
    return [(x / s, y / s) for x, y in seeds]


def close_window(window) -> None:
    cv2.destroyWindow(window)
    for _ in range(5):          # macOS only closes it after a few more event ticks
        cv2.waitKey(1)


def mark_new_stone(after, result, px_per_unit, unit):
    """Click points around the new stone's outline; the overlay and the
    verdict update after every click. Enter/space = done, z = undo."""
    s = min(1.0, CLICK_VIEW_WIDTH / after.shape[1])
    window = "click around the NEW stone (2+ points), Enter = done, z = undo"
    points, state = [], {"dirty": True, "view": None, "check": None}

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((x / s, y / s))
            state["dirty"] = True

    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)
    while True:
        if state["dirty"]:
            check = check_marked_points(result, points) if len(points) >= 2 else None
            full = overlay.draw_ar(after, result, check, px_per_unit, unit)
            view = cv2.resize(full, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            for x, y in points:
                cv2.circle(view, (int(x * s), int(y * s)), 6, (0, 255, 255), -1)
            state.update(dirty=False, view=view, check=check)
        cv2.imshow(window, state["view"])
        key = cv2.waitKey(20) & 0xFF
        if key in (13, 10, 3, 32):
            break
        if key == ord("z") and points:
            points.pop()
            state["dirty"] = True
        if key in (27, ord("q")):
            close_window(window)
            raise RuntimeError("cancelled")
    close_window(window)
    if state["check"] is None:
        raise RuntimeError("click at least two points around the new stone")
    return state["check"]


def run_one(path: Path, args) -> None:
    image = read(path)
    seeds = click_seeds(image) if args.click else None
    det = detect_stones(image, DetectParams(ground_thresh=args.ground_thresh), seeds=seeds)
    print(f"{path.name}: detected {len(det.stones)} stone(s)")

    panels = overlay.detection_panels(image, det)
    left, right, _ = pick_base_pair(det.stones)
    result = compute_thirds(left, right)

    px_per_unit, unit = 1.0, "px"
    if args.ref_cm:
        px_per_unit, unit = result.left_span.width / args.ref_cm, "cm"

    thirds_view = overlay.draw_stones(image, [left, right])
    overlay.draw_thirds_lines(thirds_view, result)
    panels["7 thirds of each stone"] = thirds_view
    panels["8 AR overlay"] = overlay.draw_ar(image, result, None, px_per_unit, unit)

    check = None
    if args.after:
        after, valid = align_to(image, read(args.after))   # phone may have moved
        if args.mark_ends:
            check = mark_new_stone(after, result, px_per_unit, unit)
        else:
            placed = detect_placed_stone(image, after, valid=valid)
            # A real stone on top is about as big as the ones below; a much
            # smaller change region means detection failed (e.g. same colour).
            if placed is None or placed.area < 0.5 * min(left.area, right.area):
                print("  after photo: new stone not found reliably "
                      "(same colour as the stones below?) -> rerun with --mark-ends")
            else:
                check = check_placement(result, placed)
        if check is not None:
            panels["9 after (aligned): placement check"] = overlay.draw_ar(
                after, result, check, px_per_unit, unit)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    final = list(panels.values())[-1]
    cv2.imwrite(str(args.out_dir / f"{stem}_steps.png"), overlay.grid(panels, cols=4))
    cv2.imwrite(str(args.out_dir / f"{stem}_ar.png"), final)
    data = result.to_dict(px_per_unit, unit)
    if check is not None:
        data["placement_check"] = {"ok": check.ok, "message": check.message,
                                   "cover_stone_1": round(check.cover_left, 3),
                                   "cover_stone_2": round(check.cover_right, 3)}
    (args.out_dir / f"{stem}.json").write_text(json.dumps(data, indent=2))

    print(f"  next stone: length {data['stone_length_min']}-{data['stone_length_max']} {unit},"
          f" depth ~{data['stone_depth']} {unit}")
    if check is not None:
        print(f"  placed stone: {check.message} "
              f"(covers {check.cover_left:.0%} of stone 1, {check.cover_right:.0%} of stone 2)")
    print(f"  saved {args.out_dir}/{stem}_steps.png, _ar.png, .json")

    if args.show:
        cv2.imshow("rule of thirds (any key to close)", final)
        cv2.waitKey(0)
        close_window("rule of thirds (any key to close)")


def main() -> int:
    args = parse_args()
    failed = 0
    for path in args.images:
        try:
            run_one(path, args)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            print(f"error: {path.name}: {exc}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
