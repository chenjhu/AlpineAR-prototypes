"""Live stone outline. The stone is the target; the white paper under it is
only a clean background, so the room behind does not confuse the detector.

Every frame (downscaled to work_width for speed):

1. clean zone: the largest bright, low-saturation region is the paper. Its
   outer outline, holes filled, is where a stone can be. Any shape works:
   bent paper, a corner out of the frame, a hand in front.
2. stone score: Lab distance of every pixel to the paper colour. Colour
   counts fully, lightness half, so the stone's soft shadow scores low.
3. threshold: picked per frame with Otsu inside the zone, so a pale beige
   stone and a dark grey one both work without touching a slider.
4. refine: each candidate is cleaned with GrabCut (stone vs paper/shadow
   colour model) for a tight edge. Candidates that touch the paper outline
   are fingers and are dropped.
5. smoothing: the stone mask is blended with the previous frames.
6. optional scale: when the paper shows as a clean quadrilateral with all
   four corners in view, the outline is mapped onto the known paper size and
   labelled in cm2 / mm.

History: archive/contour-detection/stone_contour.py needed a plain image
border. The first version of this file needed the paper as a flat rectangle
and used a fixed tolerance, which missed pale stones.
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

PAPER_SIZES_MM = {"a4": (297, 210), "a5": (210, 148), "a3": (420, 297),
                  "letter": (279, 216)}
WINDOW = "Stone on paper"


@dataclass
class Params:
    work_width: int = 640
    sat_max: int = 60              # paper = saturation below this ...
    white_min: int = 0             # ... and brightness above this; 0 = Otsu
    threshold: float = 0           # stone score cut-off; 0 = Otsu per frame
    min_threshold: float = 10      # auto threshold never goes below this
    lightness_weight: float = 0.5  # < 1: shadows (darker, same colour) count less
    min_area_frac: float = 0.002   # of the frame
    max_stones: int = 6
    refine: bool = True            # GrabCut edge refinement
    smoothing: float = 0.5         # 0 = this frame only, 0.9 = steady but laggy


@dataclass
class Stone:
    contour: np.ndarray            # (N, 1, 2) int32, camera image pixels
    area_px: float
    area_cm2: float | None = None  # only with paper scale
    length_mm: float | None = None
    width_mm: float | None = None


@dataclass
class Result:
    paper: np.ndarray | None       # outer outline of the paper, camera px
    stones: list[Stone] = field(default_factory=list)
    corners: np.ndarray | None = None  # (4, 2) when the scale is available
    threshold: float = 0.0
    mask: np.ndarray | None = None     # stone mask, work resolution
    score: np.ndarray | None = None    # stone score, work resolution
    scale: float = 1.0                 # work / camera resolution


def ellipse(size: int) -> np.ndarray:
    size = max(3, int(size)) | 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


# --- step 1: the paper as a clean zone --------------------------------------

def paper_likeness(outline: np.ndarray, shape) -> float:
    """0..1: how much a region looks like one sheet of paper.

    Rectangular (area close to its best-fit quadrilateral) and mostly inside
    the frame. A bright wall merged with the paper is ragged and runs along
    the image border, so it scores low.
    """
    h, w = shape[:2]
    area = cv2.contourArea(outline)
    hull = cv2.convexHull(outline)
    quad = cv2.approxPolyDP(hull, 0.03 * cv2.arcLength(hull, True), True)
    if len(quad) != 4:
        quad = cv2.boxPoints(cv2.minAreaRect(hull)).reshape(-1, 1, 2)
    fit = min(area / max(cv2.contourArea(quad), 1), 1.0)
    pts = outline.reshape(-1, 2)
    on_border = np.mean((pts[:, 0] <= 1) | (pts[:, 1] <= 1)
                        | (pts[:, 0] >= w - 2) | (pts[:, 1] >= h - 2))
    size = min(1.0, area / (0.15 * w * h))   # tiny white patches score low
    return fit * (1 - on_border) * size


def find_paper(img: np.ndarray, p: Params):
    """Return (outline contour, filled zone mask, white mask) or Nones.

    White = bright and low saturation. Off-white walls are only slightly more
    saturated than paper, so several saturation limits are tried and the
    region that looks most like a sheet wins.
    """
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    s, v = hsv[..., 1], hsv[..., 2]
    white_min = p.white_min
    if white_min <= 0:
        candidates = v[s <= p.sat_max].reshape(-1, 1)
        if candidates.size < 100:
            return None, None, None
        white_min, _ = cv2.threshold(candidates, 0, 255,
                                     cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        white_min = max(white_min, 100)    # never call a dark scene "white"
    bright = v >= white_min

    best, best_score = None, 0.0
    k = ellipse(w / 130)
    for sat_max in sorted({p.sat_max, 40, 28, 20, 14}, reverse=True):
        if sat_max > p.sat_max:
            continue
        white = ((s <= sat_max) & bright).astype(np.uint8) * 255
        white = cv2.morphologyEx(white, cv2.MORPH_OPEN, k)
        contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        outline = max(contours, key=cv2.contourArea)
        if cv2.contourArea(outline) < 0.05 * w * h:
            continue
        score = paper_likeness(outline, img.shape)
        if score > best_score + 0.02:      # ties go to the looser limit
            best, best_score = (outline, white), score
    if best is None:
        return None, None, None
    outline, white = best
    zone = np.zeros((h, w), np.uint8)
    cv2.drawContours(zone, [outline], -1, 255, -1)
    return outline, zone, white


def order_corners(pts: np.ndarray) -> np.ndarray:
    """Sort 4 points clockwise, starting with the one nearest the top-left."""
    pts = np.asarray(pts, np.float32).reshape(4, 2)
    c = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    pts = pts[np.argsort(angles)]          # clockwise in image coordinates
    start = int(np.argmin(pts.sum(axis=1)))
    return np.roll(pts, -start, axis=0)


def paper_corners(outline: np.ndarray, shape) -> np.ndarray | None:
    """Four corners if the paper is a clean quadrilateral fully in view."""
    h, w = shape[:2]
    hull = cv2.convexHull(outline)
    peri = cv2.arcLength(hull, True)
    for eps in (0.02, 0.03):
        quad = cv2.approxPolyDP(hull, eps * peri, True)
        if len(quad) == 4:
            break
    else:
        return None
    pts = quad.reshape(4, 2)
    m = max(4, int(0.015 * min(h, w)))
    if (pts.min() <= m or np.any(pts[:, 0] >= w - m)
            or np.any(pts[:, 1] >= h - m)):
        return None                        # a corner is cut off by the frame
    ratio = cv2.contourArea(quad) / max(cv2.contourArea(outline), 1)
    if not 0.93 <= ratio <= 1.07:
        return None                        # bent, folded or covered
    return order_corners(pts)


def mm_homography(corners: np.ndarray, paper_mm) -> np.ndarray:
    """Camera px -> paper mm. The longer image side gets the paper's long side."""
    tl, tr, br, bl = corners
    top = np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)
    side = np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)
    long_mm, short_mm = max(paper_mm), min(paper_mm)
    w_mm, h_mm = (long_mm, short_mm) if top >= side else (short_mm, long_mm)
    dst = np.float32([[0, 0], [w_mm, 0], [w_mm, h_mm], [0, h_mm]])
    return cv2.getPerspectiveTransform(corners.astype(np.float32), dst)


# --- steps 2-4: stones in the zone -----------------------------------------

def stone_score(img: np.ndarray, white: np.ndarray, zone_in: np.ndarray,
                lightness_weight: float) -> np.ndarray:
    lab = cv2.cvtColor(cv2.GaussianBlur(img, (5, 5), 0),
                       cv2.COLOR_BGR2LAB).astype(np.float32)
    ref_px = lab[(white > 0) & (zone_in > 0)]
    ref = np.median(ref_px if len(ref_px) else lab[zone_in > 0], axis=0)
    d = lab - ref
    d[..., 0] *= lightness_weight
    return np.sqrt(np.sum(d * d, axis=2))


def pick_threshold(score: np.ndarray, zone_in: np.ndarray, p: Params) -> float:
    if p.threshold > 0:
        return float(p.threshold)
    vals = np.clip(score[zone_in > 0], 0, 255).astype(np.uint8).reshape(-1, 1)
    t, _ = cv2.threshold(vals, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return max(float(t), p.min_threshold)


def refine_grabcut(img: np.ndarray, blob: np.ndarray, k: np.ndarray):
    """Tighten one candidate blob with GrabCut inside its padded bounding box."""
    h, w = blob.shape
    x, y, bw, bh = cv2.boundingRect(blob)
    m = int(0.3 * max(bw, bh)) + 8
    x0, y0, x1, y1 = max(0, x - m), max(0, y - m), min(w, x + bw + m), min(h, y + bh + m)
    b = blob[y0:y1, x0:x1]
    gc = np.full(b.shape, cv2.GC_BGD, np.uint8)
    gc[cv2.dilate(b, k, iterations=3) > 0] = cv2.GC_PR_BGD
    gc[b > 0] = cv2.GC_PR_FGD
    gc[cv2.erode(b, k, iterations=2) > 0] = cv2.GC_FGD
    try:
        cv2.grabCut(img[y0:y1, x0:x1], gc, None, np.zeros((1, 65)),
                    np.zeros((1, 65)), 3, cv2.GC_INIT_WITH_MASK)
    except cv2.error:                      # degenerate ROI: keep the raw blob
        return blob
    out = np.zeros_like(blob)
    out[y0:y1, x0:x1] = np.isin(gc, (cv2.GC_FGD, cv2.GC_PR_FGD)) * 255
    return out


def find_stones(img, zone, white, p: Params):
    """Stone mask (uint8 0/255), score map and threshold, work resolution."""
    h, w = img.shape[:2]
    # The image border counts as paper edge too: a blob running out of the
    # frame is a hand or the room, not a whole stone.
    framed = zone.copy()
    framed[[0, -1], :] = 0
    framed[:, [0, -1]] = 0
    zone_in = cv2.erode(framed, ellipse(w / 70))
    edge = cv2.subtract(zone, cv2.erode(framed, ellipse(w / 40)))
    score = stone_score(img, white, zone_in, p.lightness_weight)
    t = pick_threshold(score, zone_in, p)

    k = ellipse(w / 130)
    cand = ((score > t) & (zone_in > 0)).astype(np.uint8) * 255
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, k)
    cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE, k, iterations=2)

    contours, _ = cv2.findContours(cand, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    mask = np.zeros((h, w), np.uint8)
    kept = 0
    for c in sorted(contours, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(c) < p.min_area_frac * w * h or kept >= p.max_stones:
            break
        blob = np.zeros((h, w), np.uint8)
        cv2.drawContours(blob, [c], -1, 255, -1)
        if np.any(blob & edge):
            continue                       # reaches the paper outline -> finger
        if p.refine:
            blob = refine_grabcut(img, blob, k) & zone
        mask |= blob
        kept += 1
    return mask, score, t


# --- step 5-6: tracking and measuring --------------------------------------

def measure(contour: np.ndarray, to_mm: np.ndarray):
    pts = cv2.perspectiveTransform(contour.astype(np.float32), to_mm)
    (_, _), (rw, rh), _ = cv2.minAreaRect(pts)
    return cv2.contourArea(pts) / 100.0, max(rw, rh), min(rw, rh)


class StoneTracker:
    """Keeps the smoothed stone mask and paper corners between frames."""

    def __init__(self, paper_mm=PAPER_SIZES_MM["a4"], params: Params | None = None):
        self.paper_mm = paper_mm
        self.p = params or Params()
        self.reset()

    def reset(self):
        self.mask = None
        self.zone = None
        self.corners = None
        self.missing = 0

    def update(self, frame: np.ndarray) -> Result:
        p = self.p
        scale = min(1.0, p.work_width / frame.shape[1])
        img = cv2.resize(frame, None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_AREA) if scale < 1 else frame

        outline, zone, white = find_paper(img, p)
        if outline is None:
            self.missing += 1
            if self.missing > 5:           # ride out a few blurred frames
                self.reset()
            return Result(paper=None, scale=scale)
        self.missing = 0

        fg, score, t = find_stones(img, zone, white, p)

        # Smooth the stone mask, unless the paper jumped (IoU of the zones).
        if self.mask is not None and self.mask.shape == fg.shape:
            inter = np.count_nonzero(zone & self.zone)
            union = np.count_nonzero(zone | self.zone)
            if inter / max(union, 1) > 0.6:
                fg = p.smoothing * self.mask + (1 - p.smoothing) * fg
        self.mask, self.zone = fg.astype(np.float32), zone
        mask = (self.mask > 127).astype(np.uint8) * 255

        corners = paper_corners(outline, img.shape)
        if corners is not None:
            corners = corners / scale
            if self.corners is not None:
                jump = np.max(np.linalg.norm(corners - self.corners, axis=1))
                if jump < 0.05 * np.linalg.norm(frame.shape[:2]):
                    corners = p.smoothing * self.corners + (1 - p.smoothing) * corners
        self.corners = corners
        to_mm = mm_homography(corners, self.paper_mm) if corners is not None else None

        stones = []
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_NONE)
        h, w = mask.shape
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:p.max_stones]:
            if cv2.contourArea(c) < p.min_area_frac * w * h:
                break
            c = cv2.approxPolyDP(c, 1.0, True).astype(np.float32) / scale
            c = np.round(c).astype(np.int32)
            stone = Stone(contour=c, area_px=cv2.contourArea(c))
            if to_mm is not None:
                stone.area_cm2, stone.length_mm, stone.width_mm = measure(c, to_mm)
            stones.append(stone)

        return Result(paper=np.round(outline / scale).astype(np.int32),
                      stones=stones, corners=corners, threshold=t, mask=mask,
                      score=score, scale=scale)


# --- drawing ---------------------------------------------------------------

GREEN, YELLOW, WHITE, RED, GREY = ((0, 220, 0), (0, 220, 255), (255, 255, 255),
                                   (60, 60, 255), (170, 170, 170))


def put_label(img, text, org, color, scale=0.55):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4,
                cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1,
                cv2.LINE_AA)


def draw(frame: np.ndarray, res: Result, show_mask: bool = False,
         auto: bool = True) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]
    if res.paper is None:
        put_label(out, "No paper found - hold the stone on a white sheet",
                  (10, 30), RED, 0.6)
        return out

    if show_mask and res.mask is not None:
        big = cv2.resize(res.mask, (w, h), interpolation=cv2.INTER_NEAREST)
        tint = out.copy()
        tint[big > 0] = RED
        out = cv2.addWeighted(out, 0.55, tint, 0.45, 0)
        inset = np.clip(res.score * 4, 0, 255).astype(np.uint8)
        iw = w // 4
        inset = cv2.resize(cv2.cvtColor(inset, cv2.COLOR_GRAY2BGR),
                           (iw, int(inset.shape[0] * iw / inset.shape[1])))
        out[40:40 + inset.shape[0], w - iw - 10:w - 10] = inset
        put_label(out, "stone score", (w - iw - 10, 34), WHITE, 0.45)

    cv2.drawContours(out, [res.paper], -1, YELLOW, 1, cv2.LINE_AA)
    if res.corners is not None:
        for x, y in res.corners:
            cv2.circle(out, (int(x), int(y)), 6, YELLOW, -1, cv2.LINE_AA)

    for i, s in enumerate(res.stones, 1):
        cv2.drawContours(out, [s.contour], -1, GREEN, 2, cv2.LINE_AA)
        if s.area_cm2 is not None:
            text = f"#{i} {s.area_cm2:.1f} cm2  {s.length_mm:.0f}x{s.width_mm:.0f} mm"
        else:
            text = f"#{i}"
        x, y = s.contour.reshape(-1, 2).min(axis=0)
        put_label(out, text, (int(x), max(int(y) - 8, 20)), GREEN)

    mode = "auto" if auto else "manual"
    scale = "cm/mm on" if res.corners is not None else \
        "cm/mm off (show all 4 paper corners)"
    put_label(out, f"stones: {len(res.stones)}   threshold {res.threshold:.0f} "
              f"({mode})   {scale}", (10, 30), WHITE, 0.55)
    return out


# --- app -------------------------------------------------------------------

def open_source(args):
    if args.image:
        img = cv2.imread(args.image)
        if img is None:
            raise SystemExit(f"Could not read image {args.image}")
        return None, img
    if args.video:
        cap = cv2.VideoCapture(args.video)
    elif hasattr(cv2, "CAP_AVFOUNDATION"):
        cap = cv2.VideoCapture(args.camera, cv2.CAP_AVFOUNDATION)
    else:
        cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise SystemExit("Could not open the camera/video. Check macOS camera "
                         "permission for your terminal / VS Code, or try "
                         "--camera 1.")
    if not args.video:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    return cap, None


def parse_paper(text: str) -> tuple[float, float]:
    if text.lower() in PAPER_SIZES_MM:
        return PAPER_SIZES_MM[text.lower()]
    w, h = text.lower().split("x")
    return float(w), float(h)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--camera", type=int, default=0, help="camera index (default 0)")
    src.add_argument("--video", help="run on a recorded video instead of the camera")
    src.add_argument("--image", help="run on one photo")
    ap.add_argument("--paper", default="a4",
                    help="a4 | a5 | a3 | letter | WxH in mm, for cm/mm (default a4)")
    ap.add_argument("--mirror", action="store_true",
                    help="flip the camera image like a mirror")
    ap.add_argument("--no-refine", action="store_true",
                    help="skip the GrabCut edge refinement (faster, rougher)")
    ap.add_argument("--record", help="save the annotated view to this .mp4")
    ap.add_argument("--record-raw",
                    help="save the plain camera video to this .mp4 (replay with --video)")
    ap.add_argument("--save", help="with --image: write the annotated image and exit")
    args = ap.parse_args()

    params = Params(refine=not args.no_refine)
    tracker = StoneTracker(parse_paper(args.paper), params)
    cap, still = open_source(args)

    if still is not None and args.save:
        params.smoothing = 0
        res = tracker.update(still)
        cv2.imwrite(args.save, draw(still, res, show_mask=False))
        print("paper:", "found" if res.paper is not None else "NOT found",
              f"| threshold {res.threshold:.1f}")
        for i, s in enumerate(res.stones, 1):
            size = (f"{s.area_cm2:.1f} cm2, {s.length_mm:.0f} x {s.width_mm:.0f} mm"
                    if s.area_cm2 is not None else "no scale")
            print(f"#{i}: {s.area_px:.0f} px2, {size}")
        return

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.createTrackbar("Threshold (0=auto)", WINDOW, 0, 80, lambda _: None)
    cv2.createTrackbar("Paper white (0=auto)", WINDOW, 0, 255, lambda _: None)
    cv2.createTrackbar("Smoothing", WINDOW, 5, 9, lambda _: None)

    writer = raw_writer = None
    show_mask = paused = False
    snap_dir = Path(__file__).resolve().parent / "output"
    frame = still
    try:
        while True:
            if not paused and cap is not None:
                ok, frame = cap.read()
                if not ok:
                    if args.video:                     # loop the recording
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    print("Camera frame unavailable.")
                    break
                if args.mirror:
                    frame = cv2.flip(frame, 1)

            if args.record_raw and not paused and cap is not None:
                if raw_writer is None:
                    raw_writer = cv2.VideoWriter(
                        args.record_raw, cv2.VideoWriter_fourcc(*"mp4v"), 20,
                        (frame.shape[1], frame.shape[0]))
                raw_writer.write(frame)

            params.threshold = cv2.getTrackbarPos("Threshold (0=auto)", WINDOW)
            params.white_min = cv2.getTrackbarPos("Paper white (0=auto)", WINDOW)
            params.smoothing = cv2.getTrackbarPos("Smoothing", WINDOW) / 10
            res = tracker.update(frame)
            canvas = draw(frame, res, show_mask, auto=params.threshold == 0)
            put_label(canvas, "Q/Esc quit  M mask  Space pause  S snapshot  R reset",
                      (10, canvas.shape[0] - 12), WHITE, 0.5)
            cv2.imshow(WINDOW, canvas)

            if args.record:
                if writer is None:
                    rec_size = (canvas.shape[1], canvas.shape[0])
                    writer = cv2.VideoWriter(
                        args.record, cv2.VideoWriter_fourcc(*"mp4v"), 20, rec_size)
                writer.write(cv2.resize(canvas, rec_size))

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("m"):
                show_mask = not show_mask
            elif key == ord(" "):
                paused = not paused
            elif key == ord("r"):
                tracker.reset()
            elif key == ord("s"):
                snap_dir.mkdir(exist_ok=True)
                path = snap_dir / time.strftime("snapshot_%Y%m%d_%H%M%S.png")
                cv2.imwrite(str(path), canvas)
                print("saved", path)
    finally:
        if cap is not None:
            cap.release()
        for wr in (writer, raw_writer):
            if wr is not None:
                wr.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
