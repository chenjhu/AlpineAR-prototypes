# Test pictures (backup)

The pictures from our tests, kept in git so they are not lost. Most of them come from folders
git ignores (`demo/inbox/`, `python/*.jpg`, the real-scale test's per-wall screens).

To add what is new after a test session (from `experiments/phone-to-gh`):

    python/.venv/Scripts/python.exe test_visuals/collect.py

It only adds; it never deletes or changes what is here. Each day also gets a `sheet.jpg`: all
of the day's pictures at a glance, in time order. Start there.

| folder | what | from |
|---|---|---|
| `phone/<date>/` | **real phone photos** (Pixel 8, Unity app) as they reached Grasshopper, with the replies Grasshopper sent (`.outlines.json`, `.zone.json`, `.fit.json`). `overlays/`: the photo with the reply drawn on it | `demo/inbox/` |
| `fake_gh/<date>/` | the first phone tests, answered by `python/fake_gh.py --save`. `photos/`: as received (`layer_` = wall, `candidate_` = new stone). `overlays/`: the answer drawn on them (`check_` = outlines, `zone_` = zone, `fit_` = fit check), 800 px wide | `python/*.jpg` |
| `realscale/roundN/` | the real-scale test, per wall: `screens_sN` = the phone's screens, `truth_sN` = the truth next to the answer | `realscale_test/roundN/outputs/` |

Colours in the overlays: red = a stone the system found (the number is its id), marker frame
x red / y green, white = how far the new stone may reach, blue = what it must cover. A new
stone's outline is green when the answer is "fits". The grey bar on top says what the system
answered. The overlays show what the phone got **at that time**, from the code of that day, not
what today's code would say.

Only 16:9 photos are taken from the inbox (the Pixel 8). The 4:3 photos there are the real-scale
test's own photos, sent by `step2_run_blind.py`; they are in `realscale_test/round*/inputs/`.

## Worth a look

**16 Nov** (`fake_gh/2026-11-16`)
- `received_20261116_121557`: the first photo that went from the phone to the PC over MQTT.
- Computer mice as stand-in stones; the first zones (`zone_...162817`, `...163734`).

**18 Nov evening** (`fake_gh/2026-11-18`, 20:28 to 20:46): the QR marker and the fit check
- The marker's own pattern taken for a stone (`check_20261118_203544`, `fit_...204149`).
- The fit check on pebbles, mice and a wallet: `too_short`, `too_long`, `fits`.

**18 Nov night** (23:35 to 23:59): on the concrete floor
- The floor's texture taken for stones (`check_20261118_234917`, `...235027`).
- The concrete blocks put on white paper.

**19 Nov** (`fake_gh/2026-11-19`): white sheet on the floor, blocks with a phone as the new stone
- Taps that found a shadow instead (`fit_20261119_000223`, `...000345`).

**23 Nov** (`phone/2026-11-23`): the Unity app end to end on the Pixel 8.

**24 Nov** (`phone/2026-11-24`)
- 09:03 to 09:05: pebbles beside the marker paper. Two of these fail:
  - `photo_...090406`: so close that the marker was not found, and the QR's squares were taken
    for stones.
  - `cand_...090541`: a photo of the desk, with no stone in it.
- 14:26 to 14:29: the faults found that afternoon.
  - `photo_...142709`: the marker paper was not painted over fully, and its edge was taken for a
    stone. Fixed at 14:29 (commit 73c5273).
  - `photo_...142615`, `...142630`: an uncut A4 marker sheet fills half the photo up to its edge.
    The ground is learned from the photo's edge, so this still fails. Cut the marker on its crop
    marks.
- The last ones, 14:28 to 14:30: `photo_...142859`, `photo_...143000` and the new stones
  `cand_...143012` (`too_shallow`), `cand_...143020` (`fits`). These work.

**Real-scale test** (`realscale/`, see `../realscale_test/README.md`)
- round 1: textured grounds, 0 of 16 right.
- round 2: white ground, 7 of 16.
- round 3: the standard test, 11 of 16.
- Round 3's `truth_s*.png` are kept in `realscale_test/round3/outputs/`, not here.
- The round-3 screens here are from the run of 24 Nov 14:30. Later runs overwrite the
  originals but not these copies.
