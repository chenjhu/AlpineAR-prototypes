"""The printed COMPAS XR marker (QR "Tracker_10") as a ruler on the ground.

A QR code of known size lying flat in the photo gives the scale: four of
its points with known cm positions give an affine map photo pixels -> cm
on the ground (least squares over the four). No camera height needed. See
MESSAGES.md, "The scale".

Affine, not a full homography (real-scale test, 2026-11-24): the marker is
12 cm, the stones 30-60 cm away from it. A homography fitted to the four
corners extrapolates their pixel errors (1-2 px) into the stones: median
7.7 %, up to 40 % wrong sizes. The affine map: median 1.9 %, at most 6.6 %,
with the camera tipped up to 6 degrees. What it leaves out is the change of
scale across a tilted photo, a few % for a phone held roughly level.

Print layout of Tracker_10, measured with a ruler: the black QR square is
12.0 cm, the red line 14.8 cm. Where the lines start was measured on a
photo (the QR rectified to 12 cm): red and green meet 1.1 cm left of and
below the QR's bottom-left corner.

Frame (the course's `qr_frames`): origin where red meets green, x along the
red line, y along the green line. In the QR's own upright view that is the
bottom-left corner, x to the right, y up.

    python qr_marker.py photo.jpg [--qr-id 10]   # prints what it found, writes photo.qr.jpg
"""
import re
from dataclasses import dataclass

import cv2
import numpy as np

QR_CM = 12.0        # the black QR square, ruler: gives the scale
FRAME_CM = 14.8     # the red line, ruler: the paper (cut on the crop marks) is this square
ORIGIN_CM = 1.1     # red/green corner -> QR's bottom-left corner, along x and y (photo)

# OpenCV gives the QR corners in the QR's own order: top-left, top-right,
# bottom-right, bottom-left (it reads the finder squares, so this holds
# however the photo is turned). Their place in the frame, in cm:
_lo, _hi = ORIGIN_CM, ORIGIN_CM + QR_CM
QR_CORNERS_CM = np.float32([[_lo, _hi], [_hi, _hi], [_hi, _lo], [_lo, _lo]])
FRAME_CORNERS_CM = np.float32([[0, 0], [FRAME_CM, 0], [FRAME_CM, FRAME_CM], [0, FRAME_CM]])


@dataclass
class Marker:
    qr_id: int
    corners_px: np.ndarray       # (4, 2) QR corners: top-left, top-right, bottom-right, bottom-left
    to_cm_h: np.ndarray          # 3x3 (affine) photo px -> cm in the frame: for measuring
    paper_h: np.ndarray | None = None   # 3x3 homography: exact at the marker, for the paper itself

    def to_cm(self, pts):
        pts = np.asarray(pts, np.float64).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(pts, self.to_cm_h).reshape(-1, 2)

    def to_px(self, pts):
        pts = np.asarray(pts, np.float64).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(pts, np.linalg.inv(self.to_cm_h)).reshape(-1, 2)

    def paper_px(self, pts):
        """cm in the frame -> photo pixels, for points on the marker's paper:
        the homography, which goes exactly through the QR's corners and
        follows the photo's tilt there. (The affine map is the better one for
        stones far from the marker, but on a big, close, tilted marker it
        misses the paper's corners by several pixels, and the unpainted rest
        of the paper was taken for stones: phone photos 2026-11-24.)"""
        if self.paper_h is None:
            return self.to_px(pts)
        pts = np.asarray(pts, np.float64).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(pts, np.linalg.inv(self.paper_h)).reshape(-1, 2)

    def frame_px(self):
        """The 14.8 cm square in photo pixels: origin, end of red, opposite, end of green."""
        return self.paper_px(FRAME_CORNERS_CM)

    def px_per_cm(self):
        """Photo pixels per cm at the marker (for messages only: the scale
        changes across a tilted photo)."""
        f = self.frame_px()
        return float(np.mean(np.linalg.norm(f - np.roll(f, 1, axis=0), axis=1))) / FRAME_CM

    def square_mask(self, shape, margin_cm=1.0):
        """The printed square (+ margin: the crop marks) as a mask (255) of a
        photo of this shape. An uncut sheet reaches beyond it; see replies.detect()."""
        m = margin_cm
        mask = np.zeros(shape[:2], np.uint8)
        pts = self.paper_px([[-m, -m], [FRAME_CM + m, -m], [FRAME_CM + m, FRAME_CM + m], [-m, FRAME_CM + m]])
        cv2.fillPoly(mask, [np.int32(np.round(pts))], 255)
        return mask


def paint_ground(img, mask, ring_px=15):
    """The photo with `mask` painted in the colour of the ground right around
    it (median of a ring outside the mask), so the detection does not see it."""
    around = cv2.dilate(mask, np.ones((2 * ring_px + 1,) * 2, np.uint8))
    around[mask > 0] = 0
    out = img.copy()
    if around.any():
        out[mask > 0] = np.median(img[around > 0], axis=0).astype(np.uint8)
    return out


def _bottom_right(gray, c):
    """OpenCV only estimates the corner without a finder square (bottom-right),
    about 5 % off on the test photo. Better: the corner of the convex hull of
    the dark squares, if the hull's other three corners agree with OpenCV's."""
    centre = c.mean(axis=0)
    mask = np.zeros(gray.shape, np.uint8)
    cv2.fillPoly(mask, [np.int32(np.round(centre + (c - centre) * 1.06))], 255)
    thresh, _ = cv2.threshold(gray[mask > 0], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dark = np.uint8((gray < thresh) & (mask > 0)) * 255
    pts = cv2.findNonZero(dark)
    if pts is None:
        return c[2]
    hull = cv2.convexHull(pts)
    quad = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True).reshape(-1, 2)
    if len(quad) != 4:
        return c[2]
    side = np.linalg.norm(c[0] - c[1])
    for i in (0, 1, 3):  # the three corners OpenCV gets right from the finder squares
        if np.linalg.norm(quad - c[i], axis=1).min() > 0.03 * side:
            return c[2]
    return quad[np.argmin(np.linalg.norm(quad - c[2], axis=1))].astype(np.float32)


# OpenCV's QR detector misses a sharp, fully visible marker in some photos and
# finds it in the same photo a little smaller or bigger (phone photos, 2026-11-18:
# 4 of 9 candidate photos "no QR marker"). So: try a few sizes.
TRY_SCALES = (1.0, 0.75, 1.5, 0.5, 1.25)


def _find_qr(img, qr_id):
    """QR corners (4, 2) in `img`'s pixels, or None."""
    detector = cv2.QRCodeDetector()
    h, w = img.shape[:2]
    for s in TRY_SCALES:
        scaled = img if s == 1.0 else cv2.resize(
            img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        text, pts, _ = detector.detectAndDecode(scaled)
        found = re.search(r"(\d+)\s*$", text or "")
        if pts is not None and found and int(found.group(1)) == int(qr_id):
            return pts.reshape(4, 2).astype(np.float32) / s
    return None


def find_marker(img, qr_id=10):
    """The marker with this id in a BGR photo, or None. QR text is e.g. 'ID_10'."""
    c = _find_qr(img, qr_id)
    if c is None:
        return None
    c[2] = _bottom_right(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), c)
    return Marker(int(qr_id), c, affine_to_cm(c), cv2.getPerspectiveTransform(c, QR_CORNERS_CM))


def affine_to_cm(corners_px):
    """3x3 matrix of the least-squares affine map: the QR's corners in the
    photo -> QR_CORNERS_CM."""
    src = np.hstack([np.float64(corners_px), np.ones((4, 1))])
    m, *_ = np.linalg.lstsq(src, np.float64(QR_CORNERS_CM), rcond=None)   # (3, 2)
    return np.vstack([m.T, [0.0, 0.0, 1.0]])


def draw(img, marker):
    """The frame (red = x, green = y) and the QR corners, to check by eye."""
    img = img.copy()
    f = np.int32(np.round(marker.frame_px()))
    cv2.polylines(img, [f.reshape(-1, 1, 2)], True, (255, 255, 255), 2)
    cv2.line(img, tuple(f[0]), tuple(f[1]), (0, 0, 255), 4)
    cv2.line(img, tuple(f[0]), tuple(f[3]), (0, 160, 0), 4)
    for x, y in np.int32(np.round(marker.corners_px)):
        cv2.circle(img, (int(x), int(y)), 8, (255, 0, 255), 2)
    return img


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("photo", type=Path)
    ap.add_argument("--qr-id", type=int, default=10)
    a = ap.parse_args()
    image = cv2.imread(str(a.photo))
    mk = find_marker(image, a.qr_id)
    if mk is None:
        raise SystemExit("no QR %d in %s" % (a.qr_id, a.photo))
    print("QR %d: corners %s, %.1f px/cm at the marker" % (
        mk.qr_id, np.round(mk.corners_px).astype(int).tolist(), mk.px_per_cm()))
    out = a.photo.with_suffix(".qr.jpg")
    cv2.imwrite(str(out), draw(image, mk))
    print("drawn ->", out)
