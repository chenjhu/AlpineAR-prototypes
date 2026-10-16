"""A minimal live 2D stone-contour prototype for a plain background."""

import argparse

import cv2
import numpy as np


def detect_stone(frame, tolerance=45, min_area_ratio=0.005):
    """Return the largest foreground contour, bounding box, and binary mask.

    The outer image border is assumed to show only the plain background.
    All measurements here are in image pixels, not real-world units.
    """
    height, width = frame.shape[:2]
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)

    margin = max(4, min(height, width) // 40)
    border = np.concatenate(
        (
            lab[:margin, :, :].reshape(-1, 3),
            lab[-margin:, :, :].reshape(-1, 3),
            lab[:, :margin, :].reshape(-1, 3),
            lab[:, -margin:, :].reshape(-1, 3),
        ),
        axis=0,
    )
    background = np.median(border, axis=0).astype(np.float32)

    delta = lab.astype(np.float32) - background
    distance = np.sqrt(np.sum(delta * delta, axis=2))
    mask = (distance > tolerance).astype(np.uint8) * 255

    # Remove small specks and fill small holes within the stone.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None, None, mask

    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < min_area_ratio * width * height:
        return None, None, mask

    return contour, cv2.boundingRect(contour), mask


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default: 0)")
    args = parser.parse_args()

    if hasattr(cv2, "CAP_AVFOUNDATION"):
        camera = cv2.VideoCapture(args.camera, cv2.CAP_AVFOUNDATION)
    else:
        camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        raise SystemExit(
            "Could not open camera. Check macOS camera permission, "
            "or try --camera 1."
        )

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cv2.namedWindow("Stone contour")
    cv2.createTrackbar("Tolerance", "Stone contour", 45, 120, lambda _: None)

    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                print("Camera frame unavailable.")
                break

            tolerance = max(1, cv2.getTrackbarPos("Tolerance", "Stone contour"))
            contour, box, mask = detect_stone(frame, tolerance)

            if contour is not None:
                x, y, width, height = box
                cv2.drawContours(frame, [contour], -1, (0, 255, 0), 2)
                cv2.rectangle(
                    frame, (x, y), (x + width, y + height), (255, 0, 0), 2
                )
                cv2.putText(
                    frame,
                    f"Area: {cv2.contourArea(contour):.0f} px^2",
                    (x, max(y - 8, 24)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2,
                )

            cv2.putText(
                frame,
                "Q / Esc: quit  |  green: contour  blue: bounding box",
                (10, frame.shape[0] - 12),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
            )
            cv2.imshow("Stone contour", frame)
            cv2.imshow("Foreground mask", mask)

            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
