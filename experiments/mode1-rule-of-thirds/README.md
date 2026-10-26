# Mode 1 - Big Rock Mode: rule of thirds prototype

> "Place a joint on a rock and a rock on a joint" (p.22) - 1/3 on the joint,
> 1/3 on the left rock, 1/3 on the right rock.

A 2D computer-vision prototype for the midterm. The phone looks **straight
down** on the wall (top view). The prototype detects the two base stones,
computes the rule-of-thirds zone, and shows where the next stone goes on top
of them and how big it must be. It is separate from the course AR app
(Grasshopper -> phone). The output JSON is a first step toward sending the
box to that app later.

| step | file | what it does |
|---|---|---|
| 1 edge / stone detection | `stone_detect.py` | Canny edges, ground-colour model, distance-transform + watershed to split stones that touch; before/after change detection for a placed stone |
| 2 virtual box | `rule_of_thirds.py` | thirds of each stone along the wall -> blue *must* zone, white *allowed* zone, suggested stone length and depth, placement check |
| overlay | `overlay.py` | top-view AR overlay in the visual language of the sketch + step panels |
| demo | `demo_image.py` | photo(s) -> slide-ready step grid, overlay image, JSON |
| test data | `make_synthetic.py`, `tests/` | fake top-view scenes and 15 unit tests |
| history | [`PROTOTYPING_LOG.md`](PROTOTYPING_LOG.md), [`presentation/`](presentation/) | every iteration (problem -> fix -> result) and its before/after images, for the slides |

## Setup

Python 3.10+; only OpenCV and NumPy are needed. Windows (PowerShell), from
this folder:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`

## Run it on the fake scenes first

```powershell
python make_synthetic.py
python -m pytest tests
python demo_image.py samples/scene_two_stones.png samples/scene_rotated.png --ref-cm 45
python demo_image.py samples/scene_two_stones.png --after samples/scene_after_good.png
python demo_image.py samples/scene_two_stones.png --after samples/scene_after_bad.png
```

Each photo gives `output/<name>_steps.png` (input, Canny edges, difference
from ground, stone mask, watershed split, stones + boxes, thirds, AR overlay,
and placement check if `--after`), `output/<name>_ar.png` and
`output/<name>.json`.

## Testing with real stones

**Set-up (what the detector assumes)**

1. Put two stones side by side, like two stones of one course, with a small
   gap or touching. Start on **plain, contrasting ground**: grey concrete, a
   large sheet of paper or cardboard. Grass or gravel comes later.
2. Hold the phone **straight down** (top view), about 1-1.5 m above the
   stones. Steadiest: phone on a shelf edge, ladder or tripod.
3. The stones should fill about 1/3 of the frame and **must not touch the
   picture edge**. The detector learns the ground colour from the border.
4. Use soft light (overcast, shade, indoors) and no flash. Hard sun shadows
   look like part of the stone.
5. Photos must be **JPEG**. OpenCV cannot read HEIC: on iPhone set
   Settings -> Camera -> Formats -> *Most Compatible*, or export as JPEG.
6. Measure **stone 1's length along the wall** with a tape. Stone 1 is the
   left one, or the top one if the wall runs up-down in the photo. This
   number is `--ref-cm`.

**Run**

```powershell
python demo_image.py photos\IMG_0001.jpg photos\IMG_0002.jpg --ref-cm 42
```

**What to look at** (`output/*_steps.png`)

| panel | good looks like | if not |
|---|---|---|
| 3 difference from ground | stones bright, ground dark | ground too similar -> use plainer ground |
| 4 stone mask | two white stone shapes, clean edges | ground also white -> `--ground-thresh 120` (higher = stricter); stone has holes or is missing -> lower it, e.g. `80` |
| 5 watershed split | one colour per stone | stones merged or one stone split in two -> `--click` and click each stone once (Enter to finish) |
| 8 AR overlay | box across the joint, on both stones | check the cm values against your tape |

**Accuracy check.** Measure each stone's length and compare it with the
JSON: the must/allowed zones are thirds of those lengths. Then take a
**before** photo, lay a third stone across the joint, take an **after** photo
(the phone may move or turn; the after photo is aligned to the before photo
automatically) and run:

```powershell
python demo_image.py before.jpg --after after.jpg --mark-ends --ref-cm 42
```

`--mark-ends` opens the aligned after photo with the zones: click a few points
around the new stone's outline (2+), and the green/red verdict updates after
every click. Then Enter (z = undo). Without it the new stone is detected
automatically, which only works if it differs in colour from the stones below
(see PROTOTYPING_LOG, iteration 8). The result is green (OK) or red, with how
much of stone 1 / stone 2 it covers. Try one good and one bad placement.

**Suggested test matrix** (2-3 photos each): plain ground -> real ground;
gap -> touching; wall horizontal -> diagonal in the picture; similar vs.
different stone colours. Note which cases need `--click`; that is honest
material for the presentation.

## How the virtual box is computed

Wall coordinates instead of image axes: `u` runs along the wall,
perpendicular to the joint where the two outlines meet (falls back to the
centre-to-centre line if the stones are far apart). `n` runs across it
(depth). The wall can run in any direction in the photo.

For stone 1 `[L0, L1]` (length `wL`) and stone 2 `[R0, R1]` (length `wR`):

```
must zone    (blue hatched) = [L1 - wL/3 , R0 + wR/3]   new stone must cover this
allowed zone (white)        = [L0 + wL/3 , R1 - wR/3]   and must stay inside this
next stone length           = |must| ... |allowed|
next stone depth            = depth both stones share near the joint
```

The "allowed" limit keeps the outer thirds free for the neighbouring stones of
the same course. A placed stone is OK when it covers 1/3 to 2/3 of each base
stone. From above it hides the joint, so it is found as the change between a
before and an after photo (brightness-only changes, i.e. its shadow, count
less).

## How the stones are found

1. Bilateral smoothing, then **Canny edges**.
2. Ground colour = median colour of the image border; pixels far from it
   (Lab distance, Otsu threshold) are "stone".
3. One seed per stone from the distance transform, then **watershed** grows the
   seeds until neighbouring stones meet at the joint. Several seed thresholds
   are tried, with and without the Canny edges cut out of the mask. The one
   that separates the most stones is kept.
4. Over-splitting is undone: the weakest split lines are merged until two
   stones are left. A real joint is a sharp, dark line (the shadow in the gap
   between stones); a cut through one stone, e.g. along its texture or a
   crack, is weaker. Tuned on the first real photo (`../photos/stone1.jpeg`).
5. `--click` replaces step 3 with your seeds.

## Known limits / next iterations

- Tested on synthetic scenes and one real before/after pair (two touching
  stones on a white table). More real photos are the next test (protocol above).
- Automatic detection of a placed stone fails when it has the same colour as
  the stones below. Use `--mark-ends` for now; depth (LiDAR) would solve it,
  since the new stone is higher.
- Heights are not visible from above. Levelling between stones needs depth
  data (iPhone LiDAR).
- Scale comes from one measured stone (`--ref-cm`). A printed ArUco marker
  or the phone's AR plane detection would give scale automatically and
  correct for a phone that is not perfectly level.
- Natural next step: replace the classic segmentation with a promptable
  model (e.g. SAM) seeded by a tap, and send the JSON box to the course app.
