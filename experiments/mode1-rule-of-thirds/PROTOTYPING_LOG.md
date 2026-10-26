# Mode 1 prototyping log

How the rule-of-thirds prototype evolved, one iteration per section:
problem -> cause -> change -> result. Images are in [`presentation/`](presentation/),
prefixed with the iteration number (`it07c_...` = iteration 7, image c).
Each section ends with a one-line **Say it** for the slides.
Photo names: `stone1` = `../photos/01_L0_AB.jpeg`, `stone1-1` = `../photos/03_L1_D.jpeg`
(renamed for the layer-by-layer sequence in iteration 9).

| # | iteration | data | outcome |
|---|---|---|---|
| 1 | Pipeline design: detect -> thirds -> overlay | synthetic | works, but drawn in side view (wrong) |
| 2 | Contact shadow leaking into a stone | synthetic | fixed |
| 3 | Seeding: touching stones and a third stone | synthetic | fixed |
| 4 | Over-splitting one stone into pieces | synthetic video | fixed (rule later retuned in 7) |
| 5 | Live video demo | synthetic video | built, then **dropped** (not needed) |
| 6 | **Side view -> top view** | synthetic | box now lies on the stones |
| 7 | **First real photo** | `stone1.jpeg` | 3 fixes: merge rule, drawing scale, box angle |
| 8 | **Real placement check** | `stone1` + `stone1-1` | alignment works; auto detection fails on same-colour stones -> tap fallback, depth needed |
| 9 | **Layer by layer** (team idea, built) | `01`-`05` photo sequence, 6 stones, 3 layers | whole sequence runs; every new stone checked against the right pair; F borderline |

---

## 1. Pipeline design

- **Goal:** prove that Mode 1 works on a normal phone image: find the two base
  stones, compute the rule-of-thirds zones, draw the box for the next stone.
- **Choice:** classic computer vision (OpenCV) instead of a trained model,
  because we have no labelled stone images. Pipeline: Canny edges -> "stone =
  different from the ground colour" mask -> watershed to split the stones ->
  thirds along the wall -> overlay in the visual language of our sketch (blue
  hatched = must cover, white = allowed).
- **Rule:** must zone `[L1 - wL/3, R0 + wR/3]`, allowed zone `[L0 + wL/3, R1 - wR/3]`.
- **Testing:** synthetic scenes plus unit tests, so every later change can be
  checked automatically.
- **Mistake:** v1 drew the scene in **side view** (box stacked above the stones
  like an elevation). Corrected in iteration 6. No image kept.
- **Say it:** "We started with a lightweight, training-free pipeline we could test on generated scenes."

## 2. Contact shadow leaked into a stone (synthetic)

- **Problem:** the left stone's outline included a strip of ground shadow
  under both stones, so its length (and all thirds) were wrong.
- **Cause:** watershed grows regions into the uncertain band around the
  stone mask, including the shadow.
- **Change:** keep only pixels the mask calls "stone"; clean-up kernel scaled
  to the image size.
- **Result:** zones within ~4% of the true values (must 167 px vs 174 true).

## 3. Seeding: touching stones and a third stone (synthetic)

- **Problem A:** with a stone placed on top, the detector stopped at 2 stones
  and merged the top stone into a base stone.
- **Problem B:** two stones touching flush were detected as one.
- **Causes:** a fixed "stop at 2" rule; a morphological opening that
  re-bridged the 3 px edge cut between the stones; the two stones stayed
  connected through the ground shadow under the joint.
- **Change:** try several seeding strategies (distance-transform thresholds,
  with and without cutting along Canny edges) and keep the one that separates
  the most stones; removed the bridging opening.
- **Result:** all 5 synthetic scenes correct.

## 4. Over-splitting (synthetic video)

- **Problem:** "most stones" sometimes cut one stone in two (2-4 stones per
  frame instead of 2).
- **Tried:** keep a split only if it lies on a Canny edge. **Failed:** Canny's
  global threshold misses the joint between two touching stones.
- **Change:** keep a split only if the gradient along it is >= 10x the gradient
  inside the stones. Measured: real joints 26-36x, false cuts 1-8x.
- **Result:** exactly 2 stones in all 90 frames, 18 ms per frame.
- **Later:** the 10x threshold turned out to be tuned to smooth fake stones (see 7).

## 5. Live video demo (dropped)

- Built webcam/video processing with temporal smoothing. Dropped by team
  decision: the scenario video is done by hand. Removed from the code.

## 6. Side view -> top view

- **Feedback (team):** the phone (later: a rig over the wall) shoots
  **straight down**, so the proposed stone must lie **on top of** the two base
  stones, not above them in an elevation.
- **Changes:**
  - Second axis is now the wall **depth** (across the wall) instead of height.
    The box spans the depth both stones share near the joint.
  - Height and levelling hints removed: not visible from above (needs depth data).
  - Wall can run in any direction in the photo (tested 0, 35, 90, 150 deg).
  - **Placement check needs two photos:** from above, the new stone hides the
    joint, so it is found as the *change* between a before and an after photo.
    Brightness-only changes (its shadow) count less.
  - Depth measured only near the joint: measuring whole stones let a slightly
    tilted axis inflate the depth (114 instead of 70 px in a test).
- **Images:** `it06a`-`it06e` (steps, AR overlay, diagonal wall, good and bad placement).
- **Say it:** "Our first version thought in elevation; the real workflow is a top-down camera, so the box has to lie on the stones."

## 7. First real photo (`stone1` = `01_L0_AB`, two touching stones on a white table)

Three problems, three fixes:

**7a. Only one stone found** (`it07a`)
- **Cause:** the 10x merge rule from iteration 4 was tuned on smooth fake
  stones. Real stone texture is rough, so the real joint scored only 5.7x
  and was merged away. The dark crevice between the stones also counted as
  "stone", so the mask had no notch.
- **Measured on the photo:** real joint is darker by 22 (grey levels) with a
  5.7x gradient. Cuts inside a stone: -5..19 darker, 1.5-3.8x gradient.
- **Change:** joint score = sharpness x darkness (a joint is a sharp *and*
  dark line: the shadow in the gap). Merge the weakest split repeatedly
  until 2 stones remain.
- **Say it:** "Real stones broke our assumptions: we redefined a joint as a sharp, dark line, measured on the real photo."

**7b. Overlay invisible** (`it07b`)
- **Cause:** line widths and text were sized for 960 px images; phone photos
  are 4032 px.
- **Change:** all drawing scales with image width.

**7c. Box tilted ~10 deg** (`it07c` -> `it07e`)
- **Cause:** wall direction came from the line between the two stone centres;
  the irregular left stone pulls its centre down.
- **Change:** wall direction = **perpendicular to the joint**: fit a line
  through where the two outlines run close together. Centre line only as a
  fallback when the stones are far apart.
- **Say it:** "The joint itself tells us the wall direction, not the stone centres."

- **Result:** `it07d` (all steps), `it07e` (final overlay).

## 8. Placement check on real photos (`stone1` before, `stone1-1` = `03_L1_D` after)

**8a. The phone moved and turned 90 deg between the shots** (`it08a`)
- My before/after comparison assumed a fixed phone.
- **Change:** align the after photo to the before photo: SIFT features on
  the stone texture + RANSAC homography. The new stone's features have no
  partner and drop out as outliers.
- **Result:** base stones line up in the 50/50 blend. A handheld phone works.
- **Say it:** "Registration lets the craftsperson hold the phone freely between shots."

**8b. Automatic detection of the new stone failed** (`it08b`, `it08c`)
- **Colour change:** the new stone is the same rock and colour as the stones
  below, so only the joint shadow changed. Result: a thin wrong region and a
  confidently wrong verdict ("covers 15% of stone 2").
- **Texture correlation:** tried; fine stone grain does not survive resampling,
  so unchanged stones also looked "different". Dropped.
- **Segmenting the after photo into 3 stones:** the new stone merged with a
  base stone, even with tap seeds.
- **Conclusion:** 2D colour alone cannot reliably tell same-colour stones
  apart. What *does* distinguish the new stone is that it is **higher**: a
  depth signal (iPhone LiDAR), as Fabio suggested.

**8c. Interim solution** (`it08d`)
- Guard: if the change region is less than half a base stone, give no verdict
  and ask for `--mark-ends`.
- `--mark-ends`: tap the two ends of the new stone along the wall. The rule of
  thirds only needs that span.
- **Result:** "rule of thirds OK, covers 48% of stone 1, 31% of stone 2"
  (ends marked by estimate).
- **Say it:** "In 2D we reached the limit: two taps work today; LiDAR depth is the next step to make it automatic."

**8d. First real user test of the taps (by Chenjie)**
- **Problem 1:** after Enter the window stayed open, so it looked frozen. The
  run had actually finished. macOS OpenCV only closes a window after a few
  more event ticks. Fixed.
- **Problem 2:** the result was "covers 0% of stone 2". The user tapped the
  top and bottom ends of the new stone, i.e. *across* the wall, while the
  check needs its extent *along* the wall. The instruction "click both
  ends" was ambiguous.
- **Change:** tap any points around the new stone's outline (2+); only their
  extent along the wall is used, and the overlay plus the green/red verdict
  redraw after every tap, so the user sees what is measured.
- **Result (simulated taps around the outline):** "rule of thirds OK, 47% / 30%".
- **Say it:** "The first user test showed our instruction was ambiguous, so we made the feedback live instead of explaining it better."

## 9. Layer by layer: order and locking (team idea, then built)

- **Idea:** build the wall step by step and let the app remember what is
  confirmed:
  1. Two base stones are placed. The app shows OK and the zone for the next stone.
  2. The user confirms "step done". The app **locks** these stones (outline,
     position, layer 0) and keeps them as background.
  3. The user places the new stone and confirms again. Green/red feedback;
     the stone is locked as layer 1.
  4. More layer-0 stones -> more layer-1 positions. Once a layer is complete,
     the next layer only compares against the two stones below it.
- **What it solves without depth:**
  - Covered stones never have to be re-detected; their outlines are stored.
  - Each confirm is a natural "before" snapshot for the next step.
  - The search is narrowed to the expected zone and stone size.
  - For the next layer's thirds only the new stone's span along the wall
    (+ depth) is needed, and the confirm tap can capture exactly that.
- **What it does not solve on its own:** "locked" pixels still look like the
  new stone, because it is the same rock. So the new stone's outline still
  needs a signal: (a) the user's taps (merged into the confirm step, no
  extra effort), or (b) an automatic test still to try: edges that are new
  in the after photo plus old edges (e.g. the joint) that disappeared under
  the new stone, searched only inside the expected zone.
- **Say it:** "Instead of sensing depth, the app remembers the build order: every confirmed stone is locked, so each step only asks 'what is new, and is it in the zone?'"

**9b. Built: `build_session.py`** (`it09a`-`it09c`)
- **Test sequence:** 5 photos, one per step, named after the step
  (`NN_L<layer>_<stones>`; the name stands in for the app's "step done"
  button where the user confirms the layer):

  ```
  Layer 2:          [  F  ]              05_L2_F
  Layer 1:      [  E  ][  D  ]           04_L1_E, 03_L1_D_2
  Layer 0:   [  C  ][  A  ][  B  ]       02_L0_C, 01_L0_AB
  ```
- **How it works per step:** align to the previous photo -> map all locked
  stones into the new photo -> find the new stone -> pick the open joint
  below it that is closest -> rule-of-thirds check -> lock it (outline +
  layer + which pair it bridges) -> show the zones that are still open.
- **New layer-0 stones are found automatically** (C in step 2): they lie on
  the table, so they differ in colour; the new one is the stone that
  overlaps no locked stone. Higher layers use outline clicks, stored in
  `session_marks.json` so the session replays without clicking.
- **Alignment holds over the whole sequence** although the phone zoomed in
  and out a lot between shots (scale 0.66-1.61): 178-266 matched features
  per step, and stones stay sharp in the before/after blends.
- **Results** (outlines of D, E, F estimated by Claude from gridded photos,
  so +-a few %):
  - D on A|B: OK, covers 52% of A / 31% of B
  - E on C|A: OK, 51% of C / 38% of A
  - F on E|D: OK but **borderline**, 35% of E / 36% of D. Chenjie expected F to
    fail because it is a small stone: it is narrow along the wall and just
    reaches the inner third of each stone below. The limit is 1/3 minus a
    3% tolerance (~30%), so the estimated outline decides it.
- **Readability fix:** showing used and next zones together was unreadable.
  Each step now shows only the zone the new stone was checked against (or,
  for a ground stone, the zones it opened); the overview shows the finished
  wall coloured by layer.
- **Rule insight visible in the images:** the zones over C|A and A|B overlap
  on A's middle third. D's allowed zone ends where E's must zone begins, so
  stones placed by the rule fit next to each other.
- **Limits:** outlines from clicks are approximate; small alignment errors
  accumulate over the chain (locked outlines drift a little by step 5);
  stones are assumed not to move once locked.
- **Say it:** "Six stones, three layers, five photos: the app tracks what is built and checks every new stone against the two it bridges, with no depth sensor."

---

## Next

- More real photos: gap vs touching, diagonal wall, real ground (protocol in README).
- Real `--ref-cm` measurements, to compare the cm values with a tape.
- Redo the D/E/F outlines with real clicks (`--remark`) to settle F.
- Try the edge-based test (b) to replace the clicks for upper layers.
- Depth (LiDAR) only if the lightweight route is not enough.
