# Contour detection prototype

Single-stone 2D contour and bounding-box experiment using OpenCV. Independent Python test; no Unity, Rhino, LiDAR, or GeoViewerAR integration.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python stone_contour.py
```

Place one stone on a matte, uniformly colored background; keep the image edges free of the stone. The green line is the contour, the blue rectangle is the 2D bounding box, and the mask window shows foreground pixels. Adjust Tolerance; press Q or Esc to quit. Area is in pixels squared, not physical area.

**Status:** Camera access failed in one macOS test with an AVFoundation warning. Live camera behavior has not yet been validated. This test selects the largest foreground region and does not handle multiple touching stones or cluttered backgrounds.
