"""Layer-by-layer build session (log iteration 9): replay photos of a wall
being built and run Mode 1 step by step, the way the app would.

    python build_session.py ../photos/01_L0_AB.jpeg ../photos/02_L0_C.jpeg \
        ../photos/03_L1_D_2.jpeg ../photos/04_L1_E.jpeg ../photos/05_L2_F.jpeg

Each photo shows the wall right after one step, and its name says what the
step was: NN_L<layer>_<stones>, e.g. 02_L0_C = stone C added to layer 0.
This stands in for the app's "step done" button, where the user confirms
which layer the new stone belongs to.

Per step:
1. align the photo to the previous one (the phone may move or zoom). Locked
   stones are kept in the first photo's coordinates and mapped into the
   current one.
2. find the new stone:
   - layer 0, on the ground: automatically, as the stone that overlaps no
     locked stone;
   - higher layers: from clicks around its outline (it has the same colour
     as the stones below, see log 8). Clicks are saved to the marks file,
     so a rerun replays them; --remark asks again.
3. check it against the rule of thirds of the pair of stones below it, then
   lock it.
4. draw the zones for every joint that still needs a stone on top.

Writes output/session/<step>.jpg, overview.jpg and session.json.
"""
import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

import overlay
from demo_image import close_window, read
from rule_of_thirds import PlacementCheck, ThirdsResult, check_placement, compute_thirds
from stone_detect import DetectParams, Stone, detect_stones, find_homography, stone_from_points

LAYER_COLORS = [(80, 200, 255), (255, 170, 60), (140, 230, 120), (200, 120, 255)]
STEP_NAME = re.compile(r"^\d+_L(\d+)_([A-Za-z]+)")
VIEW_WIDTH = 1200
SAVE_WIDTH = 1920


@dataclass
class Locked:
    name: str
    layer: int
    outline: np.ndarray                  # (N, 2) in the first photo's pixels
    on: tuple[str, str] | None = None    # the pair of stones it bridges
    check: dict | None = None            # rule-of-thirds result when placed


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("images", type=Path, nargs="+", help="photos in build order")
    parser.add_argument("--marks", type=Path, default=Path("session_marks.json"),
                        help="saved outline clicks per photo and stone")
    parser.add_argument("--remark", action="store_true", help="ignore saved clicks, click again")
    parser.add_argument("--no-gui", action="store_true",
                        help="never open a window (fails if a click is needed)")
    parser.add_argument("--out-dir", type=Path, default=Path("output/session"))
    return parser.parse_args()


def step_info(path: Path) -> tuple[int, list[str]]:
    m = STEP_NAME.match(path.stem)
    if not m:
        raise ValueError(f"{path.name}: name it NN_L<layer>_<stones>, e.g. 02_L0_C")
    return int(m.group(1)), list(m.group(2))


def warp(H: np.ndarray, pts) -> np.ndarray:
    return cv2.perspectiveTransform(np.asarray(pts, np.float32).reshape(-1, 1, 2), H).reshape(-1, 2)


def wall_axis(stones: list[Stone]) -> np.ndarray:
    """Direction of the wall in the photo, left -> right: the line through
    the layer-0 stone centres."""
    c = np.array([s.centroid for s in stones], np.float32)
    if len(c) < 2:
        return np.array([1.0, 0.0], np.float32)
    u = np.linalg.svd(c - c.mean(axis=0))[2][0]
    return u if u[0] >= 0 else -u


def layer_pairs(stones: dict[str, Stone], locked: dict[str, Locked], u) -> list[tuple]:
    """Neighbouring stones of the same layer, left -> right along the wall.
    Each pair has a joint that needs one stone in the layer above."""
    pairs = []
    for layer in sorted({rec.layer for rec in locked.values()}):
        names = sorted((n for n, rec in locked.items() if rec.layer == layer),
                       key=lambda n: float(np.dot(stones[n].centroid, u)))
        pairs += [(layer, a, b) for a, b in zip(names, names[1:])]
    return pairs


def joint_point(r: ThirdsResult) -> np.ndarray:
    return r.to_image(r.joint, (r.depth.lo + r.depth.hi) / 2)


def find_ground_stones(img, stones: dict[str, Stone], n_locked_l0: int, n_new: int):
    """New layer-0 stones lie on the ground, so they differ from the table and
    are found automatically: segment all layer-0 stones and keep the ones
    that overlap no locked stone."""
    det = detect_stones(img, DetectParams(stones=n_locked_l0 + n_new))
    taken = np.zeros(img.shape[:2], np.uint8)
    for s in stones.values():
        cv2.drawContours(taken, [s.contour], -1, 1, cv2.FILLED)
    new = []
    for s in det.stones:
        m = np.zeros_like(taken)
        cv2.drawContours(m, [s.contour], -1, 1, cv2.FILLED)
        if (m & taken).sum() < 0.3 * m.sum():
            new.append(s)
    new = sorted(new, key=lambda s: s.area, reverse=True)[:n_new]
    return new if len(new) == n_new else None


def click_outline(view_base, scale, title, judge):
    """Click points around one stone's outline; its outline and the verdict
    are redrawn after every click. Enter/space = done, z = undo."""
    window = f"{title}: click around its outline, Enter = done, z = undo"
    points, state = [], {"dirty": True, "view": None}

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((x / scale, y / scale))
            state["dirty"] = True

    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)
    while True:
        if state["dirty"]:
            view = view_base.copy()
            if len(points) >= 3:
                stone, check = judge(points)
                c = overlay.WHITE if check is None else (overlay.GREEN if check.ok else overlay.RED)
                cv2.drawContours(view, [np.round(stone.contour * scale).astype(np.int32)],
                                 -1, c, 2, cv2.LINE_AA)
                if check is not None:
                    overlay.label(view, check.message, (10, view.shape[0] - 12), c)
            for x, y in points:
                cv2.circle(view, (int(x * scale), int(y * scale)), 5, (0, 255, 255), -1)
            state.update(dirty=False, view=view)
        cv2.imshow(window, state["view"])
        key = cv2.waitKey(20) & 0xFF
        if key in (13, 10, 3, 32) and len(points) >= 3:
            break
        if key == ord("z") and points:
            points.pop()
            state["dirty"] = True
        if key in (27, ord("q")):
            close_window(window)
            raise RuntimeError("cancelled")
    clicked = [[round(x, 1), round(y, 1)] for x, y in points]   # before late events
    close_window(window)
    return clicked


def render(img, stones, locked, zones, new, title) -> np.ndarray:
    """Locked stones coloured by layer, zones still to fill, the new stone
    green/red with its verdict."""
    out = img.copy()
    for r in zones:
        overlay.draw_zone(out, r)
    k = overlay._k(out)
    for name, rec in locked.items():
        s = stones[name]
        c = LAYER_COLORS[rec.layer % len(LAYER_COLORS)]
        cv2.drawContours(out, [s.contour], -1, c, overlay._t(out, 2), cv2.LINE_AA)
        overlay.label(out, f"{name} L{rec.layer}", (s.centroid[0] - 20 * k, s.centroid[1]), c)
    lines = []
    for s, check in new:
        c = overlay.WHITE if check is None else (overlay.GREEN if check.ok else overlay.RED)
        cv2.drawContours(out, [s.contour], -1, c, overlay._t(out, 4), cv2.LINE_AA)
        if check is not None:
            lines.append((check.message + f"  ({check.cover_left:.0%} / {check.cover_right:.0%})", c))
    overlay.label(out, title, (12 * k, 30 * k), scale=0.7)
    for i, (text, c) in enumerate(lines):
        overlay.label(out, text, (12 * k, out.shape[0] - (14 + 26 * i) * k), c)
    return out


def save(path: Path, img) -> None:
    s = min(1.0, SAVE_WIDTH / img.shape[1])
    small = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), small, [cv2.IMWRITE_JPEG_QUALITY, 90])


def run(args) -> None:
    marks = json.loads(args.marks.read_text()) if args.marks.exists() else {}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    locked: dict[str, Locked] = {}
    H_ref = np.eye(3)        # current photo <- first photo
    prev = None
    log = []

    for i, path in enumerate(args.images):
        img = read(path)
        layer, names = step_info(path)
        if prev is not None:
            H_ref = find_homography(prev, img) @ H_ref
        stones = {n: stone_from_points(warp(H_ref, rec.outline), hull=False)
                  for n, rec in locked.items()}
        u = wall_axis([stones[n] for n, rec in locked.items() if rec.layer == 0])
        n_l0 = sum(rec.layer == 0 for rec in locked.values())
        open_pairs = [p for p in layer_pairs(stones, locked, u)
                      if (p[1], p[2]) not in {rec.on for rec in locked.values()}]

        def judge(points, layer=layer):
            """Rule of thirds for a new stone: against the open pair below
            whose joint is closest to it."""
            stone = stone_from_points(points)
            below = [p for p in open_pairs if p[0] == layer - 1]
            if not below:
                return stone, None, None, None
            results = {p: compute_thirds(stones[p[1]], stones[p[2]]) for p in below}
            p = min(results, key=lambda q: np.linalg.norm(joint_point(results[q]) - stone.centroid))
            return stone, check_placement(results[p], stone), p, results[p]

        # 2. find the new stone(s)
        found = find_ground_stones(img, stones, n_l0, len(names)) if layer == 0 else None
        if found is not None:
            found.sort(key=lambda s: float(np.dot(s.centroid, wall_axis(found + list(stones.values())))))
        else:
            found = []
            step_marks = marks.setdefault(path.stem, {})
            for name in names:
                if name not in step_marks or args.remark:
                    if args.no_gui:
                        raise RuntimeError(f"{path.name}: no saved outline for {name}; "
                                           "run without --no-gui and click it")
                    base = render(img, stones, locked,
                                  [compute_thirds(stones[a], stones[b]) for _, a, b in open_pairs],
                                  [], f"step {i + 1}: outline new stone {name}")
                    s = min(1.0, VIEW_WIDTH / img.shape[1])
                    view = cv2.resize(base, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                    step_marks[name] = click_outline(view, s, f"stone {name}",
                                                     lambda pts: judge(pts)[:2])
                    args.marks.write_text(json.dumps(marks, indent=1))
                found.append(stone_from_points(step_marks[name]))

        # 3. check and lock
        new, used_zones, entry = [], [], {"photo": path.name, "layer": layer, "stones": []}
        H_back = np.linalg.inv(H_ref)
        for name, stone in zip(names, found):
            check, pair, zone = None, None, None
            if layer > 0:
                _, check, pair, zone = judge(stone.contour.reshape(-1, 2), layer)
            rec = Locked(name, layer, warp(H_back, stone.contour.reshape(-1, 2)),
                         on=None if pair is None else (pair[1], pair[2]),
                         check=None if check is None else {
                             "ok": check.ok, "message": check.message,
                             "cover_left": round(check.cover_left, 3),
                             "cover_right": round(check.cover_right, 3)})
            locked[name], stones[name] = rec, stone
            new.append((stone, check))
            if zone is not None:
                used_zones.append(zone)
            entry["stones"].append({"name": name, "on": rec.on, "check": rec.check})
            verdict = "" if check is None else f" on {pair[1]}|{pair[2]}: {check.message} " \
                f"({check.cover_left:.0%} / {check.cover_right:.0%})"
            print(f"step {i + 1} {path.name}: {name} -> layer {layer}{verdict}")
        log.append(entry)

        # 4. zones still to fill, for the next step
        u = wall_axis([stones[n] for n, rec in locked.items() if rec.layer == 0])
        filled = {rec.on for rec in locked.values()}
        todo = [compute_thirds(stones[a], stones[b])
                for _, a, b in layer_pairs(stones, locked, u) if (a, b) not in filled]
        # A placed stone is shown with the zone it was checked against; a new
        # ground stone with the zones it opened. Both at once is unreadable.
        title = f"step {i + 1}: {' '.join(names)} -> layer {layer}"
        save(args.out_dir / f"{path.stem}.jpg",
             render(img, stones, locked, used_zones or todo, new, title))
        if i == len(args.images) - 1:
            save(args.out_dir / "overview.jpg",
                 render(img, stones, locked, todo, [], "wall: stones by layer"))
        prev = img

    (args.out_dir / "session.json").write_text(json.dumps({
        "steps": log,
        "stones": [{"name": r.name, "layer": r.layer, "on": r.on, "check": r.check,
                    "outline_px_first_photo": np.round(r.outline, 1).tolist()}
                   for r in locked.values()],
    }, indent=1))
    print(f"saved {args.out_dir}/ (one image per step, overview.jpg, session.json)")


def main() -> int:
    try:
        run(parse_args())
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
