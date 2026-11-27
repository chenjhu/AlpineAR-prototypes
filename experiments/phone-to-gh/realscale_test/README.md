# Real-scale test (2026-11-24)

How the system behaves with **real dry-stone-wall stones** (30–65 cm), photographed from
where a person holds the phone (photo 110–150 cm wide on the ground). Before, it was only
tried with pebbles of a few cm on a table.

## Method: three steps, kept apart

| step | script | reads | writes |
|---|---|---|---|
| 1 world | `step1_make_world.py --round R` | CC0 stone photos (`world/sources/`, see `world/SOURCES.md`) | `R/inputs/` (the photos + where a person taps), `R/sealed_truth/` (true masks and sizes, the true zone, the expected answer, sha256) |
| 2 system, blind | `step2_run_blind.py --round R` | **only `R/inputs/`** | `R/outputs/replies.json` |
| 3 compare | `step3_compare.py --round R` | `R/outputs/` + `R/sealed_truth/` (hash checked) | `R/outputs/screens_*.png` (the phone's screens), `truth_*.png`, `results.json` |

- **Step 1 imports nothing of the system.** The true zone is the slides' formula, written
  out again (`slide_zone`).
- **Step 2 is the real system:** Grasshopper in Rhino 8 (`demo/phone_to_gh.gh`) over MQTT,
  sent exactly as the phone sends it. The system's files are hashed before and after the run.
- **Each round uses stones the system had not seen before.** The stones are rock specimens
  (GeoDIL, Wikimedia Commons), cut from their plain backgrounds.
- **Per wall photo:** two stones and the marker. Per wall, 4 candidate photos: one that fits,
  one just inside the depth range ("edge"), one too deep, one too long.

## Results

| round | world | wall outlines (overlap with the true stones) | zone vs true | candidates right |
|---|---|---|---|---|
| 1 | textured grounds (gravel, dirt, soil, sand), stones as they come | 6–89 %, gravel and sand fail | 1 of 4 usable | **0 / 16** |
| 2 | white ground, near-square blocks of similar size in line, gap 0.3–0.6 cm | 97–99 % (a pale grey stone: 9 %) | 3 of 4 within ~2 cm | **7 / 16** |
| 3 | as round 2, new stones, white ground as uneven as real paper | **97–99 %** in all 4 | **all 4 within 0.3–1.2 cm** | **11 / 16** |

The fixes between the rounds came from rounds 1 and 2 and from the real paper photos in
`photos/`, never from round 3. Round 3 was run once, after them.

The 5 misses in round 3:
- **3 "edge" stones, 0.6–2 cm from a limit.** The measurement is off by about 1–1.5 cm
  (~3 %), and the zone's limits by about as much. With a depth window of ±10 % (about
  ±3 cm) a stone that close to a limit can go either way.
- **2 x the pale lavender stone, only partly found** (overlap 69–73 %): measured 51 cm
  instead of 63 cm.

Also seen, a fault of the test world: in two candidate photos the stone touches the marker
paper. The paper is painted over as ground, which cuts a notch out of the stone. Keep the
stone off the paper.

## After placing (added 2026-11-24)

Each wall also gets 4 photos taken **after** the stone that fitted (candidate 1)
was laid on top of the two base stones (`<scene>_placed1-4.jpg`, made by step 1
with a random source of their own, so the photos above stayed byte for byte
the same):

| photo | how the stone lies | right answer |
|---|---|---|
| placed1 "good" | in the middle of the must zone, faces in line | ok |
| placed2 "along" | shifted along the wall so 4 cm of the must zone is uncovered | move, back along the wall |
| placed3 "out" | sticking 7 cm out of the wall's face | move, back into the wall |
| placed4 "turned" | in the middle, turned by 5° | ok |

As a real second photo: the phone held a little differently (turned up to 6°,
5 % nearer or further, moved, a different tilt), the new stone 3-8 % bigger
(nearer the camera) with a soft shadow, other light. The truth: the same rule
written out again in step 1 (`slide_placement`); a case within 1.5 cm of the
limit counts as right either way (the measurement's error). A `move` is right
only if the arrow points within 45° of the true way.

Developed on round 2 (12 of 12 where the layer photo had a marker), then run
once on round 3:

| round | placements right | new stone found (overlap with the true one) | arrow off |
|---|---|---|---|
| 3 | **16 of 16** | 81-94 % | 0-10° |

The 4 "good" stones of round 3 lie within 0.3-1.2 cm of the limit across the
wall (they are a little deeper than the wall they sit on); the system says ok,
which counts as right.

The candidate check is unchanged by this: **11 of 16** as before.

## What was changed in the system (after rounds 1 and 2)

1. **Fit check crashed** when the tap found no stone and the layer had a zone: no reply,
   the phone timed out (`replies.fit_message`).
2. **Zone crashed** ("zero-size array") when a stone did not reach into the must zone
   (`rule_of_thirds.compute_zone`).
3. **Tap search sized for pebbles.** It started with a 24 x 24 cm square; a 40 cm stone
   filled it. Now the square grows while its edge is not ground (`replies.detect_tapped`).
   On 44 taps on the real pebble photos the result is unchanged.
4. **Marker scale.** A full perspective map from the 4 corners of a 12 cm QR extrapolated
   the corners' pixel errors into stones 30–40 cm away: sizes off by median 7.7 %, up to
   40 %. Now a least-squares affine map: median 1.9 %, at most 6.6 %, with 6° of camera tilt
   (`qr_marker.affine_to_cm`).
5. **Plain ground (white paper).** When the ground is plain, the stone is whatever is
   clearly not the ground's colour (a smooth light model fitted to the photo's border), and
   rough (so soft shadows on paper do not count). Pale and two-tone stones are then found
   whole, and a tap takes the whole stone (`stone_detect.plain_ground_distance`,
   `replies.is_plain`). On the 6 real paper photos in `photos/` the outlines match the old
   ones and leave out more of the shadow. On busy grounds nothing changes.

## Limits of the test world

- The stones are museum specimens photographed from the side, not from above.
- Their number stickers are painted over (inpainting), which leaves dark blotches.
- No shadows (left out on purpose). Only one stone colour family per photo is pale.
- A photo 190 cm wide (6.7 px/cm) loses the marker after the phone's JPEG (round 1).
  Hold the phone so the photo is at most about 150 cm wide.

## The standard test (from 2026-11-24)

Round 3 is the baseline: run it after every change (Grasshopper listening in Rhino):

    ../python/.venv/Scripts/python.exe step2_run_blind.py --round round3
    ../python/.venv/Scripts/python.exe step3_compare.py --round round3

Compare with: candidates 11 of 16, placements 16 of 16. Until the .gh is rebuilt with
the placement check, run `python/fake_gh.py --placed-only` next to Grasshopper so the
placement photos get an answer.

## The second mode, next to a laid stone (2026-11-27)

`mode2_test.py` builds three scenes from the round 3 cut-outs: base stones
A, B, C, a stone D laid on A and B (with its placement check, as the system
leaves it), the layer photo in the second mode, a candidate E and E laid
next to D (good, a 4 cm gap to D, pushed 7 cm out of the face). It runs
`replies.py` as Grasshopper does; results in `mode2/results.json` and
`mode2/sheet_<scene>.jpg`.

First run: the zone's lengths within 1.4 cm of the truth (D looks a little
bigger from above, so r_B comes out up to 1.1 cm short); 8 of 9 placements
right. The miss (m1 "good") is the depth rule shared with mode 1: E looked
31.5 cm deep against a 28.1 cm wall band and was sent 1.9 cm across. One
candidate (m3) came out `too_deep` at 4 % over, the same rule. Finding D
from the photo alone was tried and gave r_B 20.8 cm for 15.4, so it was
taken out: without a placement check the zone says so.
