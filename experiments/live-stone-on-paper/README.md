# Live stone outline on a hand-held sheet of paper

Hold a white sheet of paper with one or more stones on it in front of the
laptop camera. The prototype finds the paper, flattens it to a top view and
draws the outline of every stone live, with its area in **cm²** and its size
in **mm** (the known paper size gives the scale).

It replaces [`archive/contour-detection/stone_contour.py`](../../archive/contour-detection/stone_contour.py),
which only worked when the whole image border was plain background and could
only measure in pixels.

| step | what happens |
|---|---|
| 1 paper | largest bright, low-saturation region -> convex hull -> 4 corners (a thumb on the edge only dents the hull) |
| 2 rectify | perspective warp to a flat A4 at 2 px/mm, so tilting the paper does not change the measurement |
| 3 stones | Lab colour distance to the paper colour (lightness weighted down so soft shadows count less); blobs that reach the paper edge are fingers and are dropped |
| 4 smoothing | corners and mask are blended with the previous frames, so the outline is steady but still follows the stone |
| 5 display | outlines mapped back into the camera image (left) + rectified paper with rotated boxes (right) |

## Setup (macOS)

From this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python stone_on_paper.py
```

Allow camera access when macOS asks (System Settings -> Privacy & Security ->
Camera, for Terminal / VS Code). Useful options:

| option | |
|---|---|
| `--camera 1` | another camera (e.g. iPhone Continuity Camera) |
| `--mirror` | flip the image like a mirror, easier when holding the paper towards yourself |
| `--paper a5` | other paper size: `a3`, `a4` (default), `a5`, `letter` or `WxH` in mm, e.g. `200x150` |
| `--record demo.mp4` | save the annotated view as a video (for the slides) |
| `--video demo.mp4` | replay a recording instead of the live camera |
| `--image photo.jpg --save out.png` | one photo in, annotated image out |

Keys: **Q/Esc** quit, **M** show the mask (what counts as stone / paper),
**Space** pause, **S** snapshot to `output/`, **R** reset tracking.

Sliders: **Tolerance** - move right if paper texture or shadows show up as
stone, left if parts of the stone are missing. **Paper white** - 0 picks the
paper brightness automatically; set a value if the paper is not found in dim
light. **Smoothing** - 0 follows every frame, 9 is very steady but lags.

## Tips and limits

- Use plain white, matte paper; hold it flat and keep all four corners in view
  (one covered corner is usually fine).
- Avoid a white wall or white shirt directly behind the paper: the largest
  white region is taken as the paper.
- Hold the paper at its edges. A stone that touches the paper edge, or touches
  a finger, is treated as hand and dropped.
- Stones that touch each other are one outline (no watershed split here; see
  `mode1-rule-of-thirds/stone_detect.py` for that).
- Very light / white stones have little contrast with the paper; lower the
  Tolerance or use coloured paper (the detector models the paper colour, it
  only needs to be uniform and brighter than the room for step 1).
- 2D only: the area is the stone's outline seen from the camera, not its 3D
  surface. Accuracy depends on the paper lying flat.

## Test without a camera

```bash
python -m pytest tests
```

The tests build a synthetic frame (tilted A4 in a cluttered room, a thumb on
the edge, stones of known size) and check the paper corners, stone count and
area (within 12 %).
