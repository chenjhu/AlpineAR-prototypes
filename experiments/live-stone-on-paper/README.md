# Live stone outline (stone on a sheet of white paper)

Hold a stone on a sheet of white paper in front of the laptop camera. The
prototype draws the stone's outline live. The paper is only there as a clean
background: holding a stone in your fingers in front of a room is too busy to
segment, while a stone on white paper is easy.

It replaces [`archive/contour-detection/stone_contour.py`](../../archive/contour-detection/stone_contour.py),
which only worked when the whole image border was plain background.

| step | what happens |
|---|---|
| 1 clean zone | largest bright, low-saturation region = the paper; its outline with holes filled is where a stone can be. Any shape: bent paper, a corner out of view and a hand in front are fine |
| 2 stone score | Lab distance of each pixel to the paper colour; colour counts fully, lightness half, so the stone's soft shadow scores low |
| 3 threshold | picked automatically per frame (Otsu inside the paper), so pale and dark stones both work |
| 4 refine | GrabCut tightens each candidate's edge and separates it from its shadow; blobs touching the paper outline are fingers and are dropped |
| 5 smoothing | the stone mask is blended with the previous frames, so the outline is steady but still follows the stone |
| 6 cm / mm (optional) | only when the paper shows as a clean four-cornered sheet fully in view: the outline is mapped onto the known paper size (yellow corner dots = scale on) |

## Setup (macOS)

From this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python stone_on_paper.py --mirror
```

Allow camera access when macOS asks (System Settings -> Privacy & Security ->
Camera, for Terminal / VS Code; restart the app after allowing it).

| option | |
|---|---|
| `--camera 1` | another camera (e.g. iPhone Continuity Camera) |
| `--mirror` | flip the image like a mirror, easier when holding the paper towards yourself |
| `--paper a5` | paper size for cm/mm: `a3`, `a4` (default), `a5`, `letter` or `WxH` in mm |
| `--no-refine` | skip GrabCut: faster, rougher edge |
| `--record demo.mp4` | save the annotated view as a video (for the slides) |
| `--record-raw raw.mp4` | save the plain camera video, without overlay - replay it with `--video raw.mp4` to tune settings |
| `--video demo.mp4` | replay a recording instead of the live camera |
| `--image photo.jpg --save out.png` | one photo in, annotated image out |

Keys (click the video window first): **Q/Esc** quit, **M** show the mask
(red) and the stone score (inset, bright = un-paper-like), **Space** pause,
**S** snapshot to `output/`, **R** reset tracking. Ctrl+C in the terminal also
stops it.

Sliders: leave them at their defaults first. **Threshold** - 0 is automatic
(the value used is shown at the top); set a number only if auto picks up
shadows (go higher) or misses parts of the stone (go lower). **Paper white** -
0 is automatic; set a value if the paper is not found in dim light.
**Smoothing** - 0 follows every frame, 9 is very steady but lags.

## Tips and limits

- Matte white paper, even light. Keep the stone away from the paper edge: a
  stone that touches the edge, or a finger, is dropped as "hand".
- An off-white wall behind the paper is usually separated (the paper is
  more neutral, and the most sheet-like region wins), but a pure white wall
  or white shirt touching the paper can still merge with it.
- Stones that touch each other give one outline (no watershed split here; see
  `mode1-rule-of-thirds/stone_detect.py` for that).
- A white or very pale grey stone has almost no contrast with white paper.
  Lower the Threshold slider; a dark sheet does not help, because step 1
  looks for a bright sheet.
- The outline is the stone's silhouette seen from the camera, not its contact
  area. The cm/mm values assume a flat sheet and get less accurate the more the
  camera looks at the paper from the side, because the stone sticks up out of
  the paper plane.

## Test without a camera

```bash
python -m pytest tests
```

The tests build synthetic frames (tilted A4 in a cluttered room, a thumb on
the edge, a pale beige stone with colours sampled from a real webcam frame, a
sheet with one corner out of view) and check stone count, cm2 (within
12-15 %) and that the scale switches off when a corner is missing.
