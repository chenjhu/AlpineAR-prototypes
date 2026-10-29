"""Live stone outline on a hand-held sheet of white paper.

Successor of archive/contour-detection/stone_contour.py. That script assumed
the whole image border was plain background, which breaks as soon as the
paper is held in a hand in front of a room. Here every frame goes through:

1. find the paper: the largest bright, low-saturation region; its convex hull
   is simplified to four corners (fingers on an edge only dent the hull),
2. rectify: warp the paper to a flat top view of known size (A4 by default),
   so one pixel is a fixed fraction of a millimetre,
3. find the stones: every pixel that differs from the paper colour (Lab
   distance, lightness weighted down so the stone's own soft shadow counts
   less) is foreground; blobs touching the paper edge are the hand and are
   dropped,
4. smooth over time: corners and mask are blended with the previous frame,
   so the outline follows the stone without flickering,
5. map each outline back into the camera image and label it in cm / mm.

Classic OpenCV only - no training data, runs on any laptop webcam.
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
class Stone:
    contour: np.ndarray        # (N, 1, 2) int32, rectified paper pixels
    contour_frame: np.ndarray  # (N, 1, 2) int32, camera image pixels
    area_cm2: float
    length_mm: float           # long side of the rotated bounding box
    width_mm: float


@dataclass
class Result:
    paper: np.ndarray | None             # (4, 2) float32 corners tl, tr, br, bl
    stones: list[Stone] = field(default_factory=list)
    paper_view: np.ndarray | None = None  # rectified BGR paper
    mask: np.ndarray | None = None        # rectified stone mask (uint8 0/255)
    white_mask: np.ndarray | None = None  # camera-res "is paper" mask


# --- step 1: paper ---------------------------------------------------------

def order_corners(pts: np.ndarray) -> np.ndarray:
    """Sort 4 points clockwise, starting with the one nearest the top-left."""
    pts = np.asarray(pts, np.float32).reshape(4, 2)
    c = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    pts = pts[np.argsort(angles)]          # clockwise in image coordinates
    start = int(np.argmin(pts.sum(axis=1)))
    return np.roll(pts, -start, axis=0)


def find_paper(frame: np.ndarray, white_min: int = 0, sat_max: int = 70,
               min_area_frac: float = 0.05):
    """Return the paper corners (4, 2) or None, and the white mask.

    white_min = 0 picks the brightness threshold automatically (Otsu over the
    low-saturation pixels).
    """
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    s, v = hsv[..., 1], hsv[..., 2]
    grey = s <= sat_max
    if white_min <= 0:
        candidates = v[grey].reshape(-1, 1)
        if candidates.size < 100:
            return None, np.zeros((h, w), np.uint8)
        white_min, _ = cv2.threshold(candidates, 0, 255,
                                     cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        white_min = max(white_min, 100)    # never call a dark scene "white"
    mask = (grey & (v >= white_min)).astype(np.uint8) * 255

    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, w // 160) | 1,) * 2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, mask
    paper = max(contours, key=cv2.contourArea)
    if cv2.contourArea(paper) < min_area_frac * w * h:
        return None, mask

    hull = cv2.convexHull(paper)
    peri = cv2.arcLength(hull, True)
    quad = None
    for eps in (0.02, 0.03, 0.05, 0.08):
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4:
            quad = approx
            break
    if quad is None:                       # e.g. a corner bent or covered
        quad = cv2.boxPoints(cv2.minAreaRect(hull))
    return order_corners(quad), mask


def paper_geometry(corners: np.ndarray, paper_mm: tuple[float, float],
                   px_per_mm: float):
    """Rectified size and homographies for these corners.

    The paper's long side is matched to the longer side seen in the image, so
    the rectified view keeps the paper's orientation (portrait/landscape).
    """
    tl, tr, br, bl = corners
    top = np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)
    side = np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)
    long_mm, short_mm = max(paper_mm), min(paper_mm)
    w_mm, h_mm = (long_mm, short_mm) if top >= side else (short_mm, long_mm)
    size = (int(round(w_mm * px_per_mm)), int(round(h_mm * px_per_mm)))
    dst = np.float32([[0, 0], [size[0] - 1, 0],
                      [size[0] - 1, size[1] - 1], [0, size[1] - 1]])
    to_paper = cv2.getPerspectiveTransform(corners.astype(np.float32), dst)
    return size, to_paper, np.linalg.inv(to_paper)


# --- step 2: stones on the paper ------------------------------------------

def stone_mask(paper_view: np.ndarray, tolerance: float,
               lightness_weight: float = 0.5, inset_frac: float = 0.025):
    """Foreground mask (float 0..1) of everything that is not paper colour."""
    h, w = paper_view.shape[:2]
    lab = cv2.cvtColor(cv2.GaussianBlur(paper_view, (5, 5), 0),
                       cv2.COLOR_BGR2LAB).astype(np.float32)
    inset = max(3, int(inset_frac * min(h, w)))

    # Paper colour from a ring just inside the edge: mostly bare paper even
    # when a large stone sits in the middle.
    ring = np.zeros((h, w), bool)
    ring[inset:-inset, inset:-inset] = True
    ring[3 * inset:-3 * inset, 3 * inset:-3 * inset] = False
    paper_lab = np.median(lab[ring], axis=0)

    delta = lab - paper_lab
    delta[..., 0] *= lightness_weight
    fg = (np.sqrt(np.sum(delta * delta, axis=2)) > tolerance).astype(np.uint8)
    fg[:inset], fg[-inset:], fg[:, :inset], fg[:, -inset:] = 0, 0, 0, 0

    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, w // 100) | 1,) * 2)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, k)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k, iterations=2)
    return fg.astype(np.float32), inset


def extract_stones(mask: np.ndarray, inset: int, px_per_mm: float,
                   to_frame: np.ndarray, min_area_frac: float = 0.003,
                   max_stones: int = 8) -> list[Stone]:
    h, w = mask.shape[:2]
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_NONE)
    stones = []
    edge = inset + 2
    for c in sorted(contours, key=cv2.contourArea, reverse=True):
        area = cv2.contourArea(c)
        if area < min_area_frac * w * h or len(stones) >= max_stones:
            break
        x, y, bw, bh = cv2.boundingRect(c)
        if x <= edge or y <= edge or x + bw >= w - edge or y + bh >= h - edge:
            continue                       # reaches the paper edge -> a finger
        c = cv2.approxPolyDP(c, 1.0, True)
        (_, _), (rw, rh), _ = cv2.minAreaRect(c)
        frame_c = cv2.perspectiveTransform(c.astype(np.float32), to_frame)
        stones.append(Stone(
            contour=c,
            contour_frame=np.round(frame_c).astype(np.int32),
            area_cm2=area / px_per_mm ** 2 / 100.0,
            length_mm=max(rw, rh) / px_per_mm,
            width_mm=min(rw, rh) / px_per_mm))
    return stones


# --- step 3: tracking over frames -----------------------------------------

class StoneOnPaper:
    """Keeps the smoothed paper corners and stone mask between frames."""

    def __init__(self, paper_mm=PAPER_SIZES_MM["a4"], px_per_mm=2.0):
        self.paper_mm = paper_mm
        self.px_per_mm = px_per_mm
        self.corners = None
        self.mask = None
        self.missing = 0

    def reset(self):
        self.corners, self.mask, self.missing = None, None, 0

    def update(self, frame: np.ndarray, tolerance: float = 40,
               white_min: int = 0, smoothing: float = 0.5) -> Result:
        """smoothing 0 = use this frame only, 0.9 = very steady but laggy."""
        corners, white = find_paper(frame, white_min)
        if corners is None:
            # Ride out a few dropped frames (motion blur) before giving up.
            self.missing += 1
            if self.corners is None or self.missing > 5:
                self.reset()
                return Result(paper=None, white_mask=white)
            corners = self.corners
        else:
            self.missing = 0

        if self.corners is not None:
            jump = np.max(np.linalg.norm(corners - self.corners, axis=1))
            diag = np.linalg.norm(frame.shape[:2])
            if jump < 0.1 * diag:
                corners = smoothing * self.corners + (1 - smoothing) * corners
            else:                          # paper moved fast or was swapped
                self.mask = None
        self.corners = corners.astype(np.float32)

        size, to_paper, to_frame = paper_geometry(self.corners, self.paper_mm,
                                                  self.px_per_mm)
        view = cv2.warpPerspective(frame, to_paper, size)
        fg, inset = stone_mask(view, tolerance)
        if self.mask is None or self.mask.shape != fg.shape:
            self.mask = fg
        else:
            self.mask = smoothing * self.mask + (1 - smoothing) * fg
        mask = (self.mask > 0.5).astype(np.uint8) * 255

        stones = extract_stones(mask, inset, self.px_per_mm, to_frame)
        return Result(paper=self.corners, stones=stones, paper_view=view,
                      mask=mask, white_mask=white)


# --- drawing ---------------------------------------------------------------

GREEN, BLUE, YELLOW, WHITE, RED = ((0, 220, 0), (255, 120, 0), (0, 220, 255),
                                   (255, 255, 255), (60, 60, 255))


def put_label(img, text, org, color, scale=0.55):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4,
                cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1,
                cv2.LINE_AA)


def fit_panel(img: np.ndarray | None, size: int) -> np.ndarray:
    """Letterbox img into a size x size panel, so the window never resizes."""
    panel = np.full((size, size, 3), 40, np.uint8)
    if img is None:
        return panel
    scale = size / max(img.shape[:2])
    w, h = int(img.shape[1] * scale), int(img.shape[0] * scale)
    x, y = (size - w) // 2, (size - h) // 2
    panel[y:y + h, x:x + w] = cv2.resize(img, (w, h))
    return panel


def draw(frame: np.ndarray, res: Result, show_mask: bool = False) -> np.ndarray:
    """Camera view with outlines on the left, rectified paper on the right."""
    out = frame.copy()
    h = out.shape[0]
    if res.paper is None:
        put_label(out, "No paper found - hold the white sheet fully in view",
                  (10, 30), RED, 0.6)
        side = None
        if show_mask and res.white_mask is not None:
            side = cv2.cvtColor(res.white_mask, cv2.COLOR_GRAY2BGR)
        return np.hstack([out, fit_panel(side, h)])

    cv2.polylines(out, [np.round(res.paper).astype(np.int32)], True, YELLOW, 2,
                  cv2.LINE_AA)
    view = res.paper_view.copy()
    if show_mask:
        tint = view.copy()
        tint[res.mask > 0] = RED
        view = cv2.addWeighted(view, 0.5, tint, 0.5, 0)

    for i, s in enumerate(res.stones, 1):
        cv2.drawContours(out, [s.contour_frame], -1, GREEN, 2, cv2.LINE_AA)
        cv2.drawContours(view, [s.contour], -1, GREEN, 2, cv2.LINE_AA)
        box = cv2.boxPoints(cv2.minAreaRect(s.contour)).astype(np.int32)
        cv2.drawContours(view, [box], -1, BLUE, 1, cv2.LINE_AA)
        text = f"#{i} {s.area_cm2:.1f} cm2  {s.length_mm:.0f}x{s.width_mm:.0f} mm"
        x, y = s.contour_frame.reshape(-1, 2).min(axis=0)
        put_label(out, text, (int(x), max(int(y) - 8, 20)), GREEN)
        vx, vy = s.contour.reshape(-1, 2).min(axis=0)
        put_label(view, f"#{i}", (int(vx), max(int(vy) - 6, 16)), GREEN)

    put_label(out, f"stones: {len(res.stones)}", (10, 30), WHITE, 0.6)
    return np.hstack([out, fit_panel(view, h)])


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
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group()
    src.add_argument("--camera", type=int, default=0, help="camera index (default 0)")
    src.add_argument("--video", help="run on a recorded video instead of the camera")
    src.add_argument("--image", help="run on one photo")
    p.add_argument("--paper", default="a4",
                   help="a4 | a5 | a3 | letter | WxH in mm (default a4)")
    p.add_argument("--mirror", action="store_true",
                   help="flip the camera image like a mirror")
    p.add_argument("--record", help="save the annotated view to this .mp4")
    p.add_argument("--save", help="with --image: write the annotated image and exit")
    p.add_argument("--tolerance", type=int, default=40,
                   help="start value of the Tolerance slider")
    args = p.parse_args()

    tracker = StoneOnPaper(parse_paper(args.paper))
    cap, still = open_source(args)

    if still is not None and args.save:
        res = tracker.update(still, args.tolerance, smoothing=0)
        cv2.imwrite(args.save, draw(still, res))
        for i, s in enumerate(res.stones, 1):
            print(f"#{i}: {s.area_cm2:.1f} cm2, {s.length_mm:.0f} x {s.width_mm:.0f} mm")
        print("paper:", "found" if res.paper is not None else "NOT found")
        return

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.createTrackbar("Tolerance", WINDOW, args.tolerance, 120, lambda _: None)
    cv2.createTrackbar("Paper white (0=auto)", WINDOW, 0, 255, lambda _: None)
    cv2.createTrackbar("Smoothing", WINDOW, 5, 9, lambda _: None)

    writer = None
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

            res = tracker.update(
                frame,
                tolerance=max(1, cv2.getTrackbarPos("Tolerance", WINDOW)),
                white_min=cv2.getTrackbarPos("Paper white (0=auto)", WINDOW),
                smoothing=cv2.getTrackbarPos("Smoothing", WINDOW) / 10)
            canvas = draw(frame, res, show_mask)
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
        if writer is not None:
            writer.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
