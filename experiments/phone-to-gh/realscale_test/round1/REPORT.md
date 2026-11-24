# Real-scale test, round 1 (2026-11-24) — see ../README.md for rounds 2 and 3

How does the system behave with **real dry-stone-wall stones** (30–70 cm), photographed
from where a person holds the phone (1–1.6 m up)? So far it was only tried with
pebbles of a few cm on a table.

## How the test was isolated

| step | script | reads | writes |
|---|---|---|---|
| 1 world | `step1_make_world.py` | CC0 photos of stones and grounds (`world/sources/`, see `world/SOURCES.md`) | `inputs/` (photos + where a person taps), `sealed_truth/` (true masks, sizes, zone, expected result, sha256) |
| 2 system, blind | `step2_run_blind.py` | **only `inputs/`** | `outputs/replies.json` |
| 3 compare | `step3_compare.py` | `outputs/` + `sealed_truth/` (hash checked) | screenshots, `outputs/results.json` |

- Step 1 imports nothing of the system. The true zone is the slides' formula written out again
  (`slide_zone`), not `rule_of_thirds.py`.
- Step 2 is the real system: the photos go over MQTT (broker.hivemq.com) to the Grasshopper
  that is listening (`demo/phone_to_gh.gh` in Rhino 8), exactly as the phone sends them.
- The system's files were hashed before and after step 2: unchanged (`outputs/system.sha256`).
  Nothing was tuned on these photos.

The world: 4 wall photos (two stones + the marker) and 4 candidate photos per wall (one
stone + the marker), 1280 x 960 px like the phone.

| scene | ground | photo width on the ground | px/cm | camera tilt |
|---|---|---|---|---|
| s1 | grey gravel | 110 cm | 11.6 | 0° |
| s2 | brown dirt | 150 cm | 8.5 | 8° |
| s3 | yellow soil | 190 cm | 6.7 | 0° |
| s4 | light sand | 150 cm | 8.5 | 4° |

The candidates per wall are picked against the true zone: one that fits, one just inside
the depth range, one too deep, one too long.

## Results

**Wall photos (outlines and zone)**

| scene | outlines | overlap with true A / B | length true → system (cm) | depth true → system (cm) |
|---|---|---|---|---|
| s1 gravel | 6 (pebbles counted as stones) | 6 % / 6 % | 18.0–54.1 → 5.6–16.9 | 23.5–28.8 → 14.5–17.7 |
| s2 dirt | 2 | 64 % / 70 % | 19.5–58.5 → 14.1–42.4 | 23.9–29.3 → 34.5–42.2 |
| s3 soil | 2 | 89 % / 70 % | 19.4–58.3 → none (marker lost) | 23.7–29.0 → none |
| s4 sand | 3 (a dark ground patch) | 36 % / 7 % | 19.2–57.7 → error | 21.5–26.2 → error |

**Candidate stones (tap → fit check): 0 of 16 measured correctly**

- 6 of 16: **no reply at all**. The check crashed (bug 1 below); the phone shows "No answer from Grasshopper".
- 6 of 16: "no stone at the tap".
- 4 of 16: a small piece of the stone was measured (e.g. 6.1 x 3.7 cm for a 38.9 x 24.4 cm stone).

## What it shows

1. **Bug: the fit check crashes** when the tap finds no stone but the layer has a zone
   (`replies.fit_message` calls `fit_result` with no length → `TypeError`). Nothing is sent
   back, and the phone waits 15 s.
2. **The tap search is sized for pebbles.** It starts with a 24 x 24 cm square around the tap
   (`TAP_START_CM = 12`). A real stone (36–67 cm) fills the whole square, so there is no
   ground left to learn from, and it finds "no stone". It only grows the square when a stone
   was found and touches the edge.
3. **The wall detection depends on the ground's contrast.**
   - On dirt and soil the outlines are fair (64–89 %).
   - On grey gravel next to grey stones the stones are lost and the pebbles counted (s1).
   - On light sand next to light stones the stones are missed and a dark patch is taken as a stone (s4).
   - In s4 the zone then fails with "zero-size array to reduction operation minimum" (bug 2:
     `compute_zone` with stones far apart / offset).
4. **The marker at 190 cm.** At 6.7 px/cm the QR is about 80 px. It was found in the photo,
   but not after the phone's JPEG re-encoding, so s3 has no cm. At 150 cm (8.5 px/cm) it
   was found every time.
5. **Where the outlines are fair (s2), the zone is still off.** The joint is estimated from
   partial outlines, so the zone comes out turned about 45°. Depth: 34–42 instead of 24–29 cm.
   Length: 14–42 instead of 20–59 cm.

## Limits of this world (not the system's fault)

- The stone photos are museum specimens seen from the side, not from above; some show a darker side face.
- Each specimen had a number sticker. It was painted over (inpainted), which leaves a dark blotch.
  In s2 cand2 the tap landed on such a blotch.
- No shadows (left out on purpose), perfectly flat ground, no grass over the stones.

## Next (not done)

- Fix bugs 1 and 2.
- Make the tap search and the detection's sizes scale-aware: start from a real stone size,
  and grow the square when it is all stone.
- Then run a **new world** (new seed, stones not used in round 1), so the fixed system again
  has not seen the test stones.
