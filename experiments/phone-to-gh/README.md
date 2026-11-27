# Phone ↔ Grasshopper over MQTT

Steps 1–7 of the basic prototype
([chart](../rhino-contour-to-gh/presentation/flow_gh_unity_split.png)):

> **A photo sent over MQTT arrives in Grasshopper, the stones are detected
> and appear as curves; their outlines go back to the phone, and after the
> person's Yes the rule-of-thirds zone for the next stone follows.**

The course pipeline only goes GH → phone. This is the missing other
direction. The phone is replaced by `python/fake_phone.py`, which sends
exactly what the Unity app will send, so the Unity side only has to follow
[`MESSAGES.md`](MESSAGES.md).

```
phone ──photo──> [receive photo] ─> [detect] ─> [receive contours] ─> curves in Rhino
(or fake_phone.py) inbox/photo_*.jpg   │ photo_*.json, .outlines.json, .zone.json
      <──outlines── [reply to phone] <─┘
      ──Yes / No──>        │
      <──zone (after Yes)──┘
```

## The step broken down

| # | what | technique | status |
|---|---|---|---|
| 1 | Message format both sides follow | [`MESSAGES.md`](MESSAGES.md): plain JSON, photo as base64 JPEG, `ref_cm`, `ts` | done |
| 2 | Pretend phone | `python/fake_phone.py`: resize to 1280 px, JPEG, paho-mqtt (no COMPAS, like Unity) | done |
| 3 | Grasshopper listens | `grasshopper/receive_photo.py`: `compas_eve` Subscriber, same venv as the course Publisher; the MQTT thread saves the photo and asks GH to re-run | done |
| 4 | Detect the stones | `grasshopper/detect_photo.py`: runs `python/replies.py` (Mode 1 detection + rule of thirds) with the Mode 1 venv (GH's Python has no OpenCV) | done |
| 5 | Outlines → curves | `receive_contours.py` from `../rhino-contour-to-gh`, unchanged except: empty input → "no file yet" | done |
| 6 | Unity sends the photo | `unity/PhotoSender.cs` in the course Unity project: AR camera image (no UI), JPEG 1280 px, plain JSON, vibrates on the broker's receipt | done, **tested end to end** (see below) |
| 7 | Outlines, Yes / No, zone (flow 4–7) | `grasshopper/reply_to_phone.py` sends messages 2 and 4, receives 3; `unity/OutlineReview.cs` draws them over the live camera view | done, **tested end to end** 2026-11-16 (`MAC_TASK.md`) |
| 8 | Scale from the QR marker Tracker_10 | `python/qr_marker.py`: the printed marker in the photo → homography photo px → cm in its frame (x red, y green); its paper is covered before detection; messages 2 and 4 get cm fields (`MESSAGES.md`, "The scale") | done on the Mac, tested on a composite photo; **not yet on a real phone photo** |
| 9 | Candidate stone, fit check (flow 8–10). Since 2026-11-23 the quarter rule, length **and** depth, and the person taps the stone (`tap` in message 5) | messages 5–6: `reply to phone` saves the candidate photo, runs `python/replies.py --layer-ts ... --zone ...` (one stone, length in cm vs the zone's `length_cm`) and sends `fits` / `too_short` / `too_long`; `fake_gh.py`, `fake_phone.py --candidate` do the same | Grasshopper done 2026-11-18, tested with `fake_phone.py` (two stones cut from a phone photo: `too_long` 6.0 cm, `fits` 4.3 cm, zone 2.8–5.0, reply in 0.4 s); Unity: `UNITY_TASK.md` round 4 |

| 10 | After placing: is the new stone in the zone? (added 2026-11-24) | messages 7-8: the wall photographed again; `python/placement.py` lines it up with the layer photo (texture points on the stones, else the marker), takes what changed as the new stone, checks it against the quarter rule along the wall and the wall's face across it, and says how far to move it; `reply to phone` answers, `unity/OutlineReview.cs` shows it (green + jingle, or red + arrow) | real-scale test round 3: 16 of 16 (`realscale_test/README.md`); Grasshopper needs the rebuilt .gh (`grasshopper/build_gh_file.py`, then `open_gh_file.py`); not yet on the phone |
| 11 | The zone in Rhino (added 2026-11-24) | `grasshopper/zone_curves.py`: the allowed zone as a curve, the must zone as a filled surface (blue), the placed stone (green), in the same cm as the stone curves | needs the rebuilt .gh |
| 12 | Start and the two modes (group's mock-up "first & second interface", 2026-11-27) | `unity/PhotoSender.cs`: Start, then "Where does the new stone go?" with two picture cards. "On two stones" = the quarter rule (everything above). "Next to a laid stone" = the group's rule L_E = r_B + a L_C (`rule_of_thirds.compute_zone_next_to`, `replies.py` finds the laid stone from the last placement check, `placement.check` checks E touches it); the photo carries `mode` (`MESSAGES.md` messages 1 and 4). "Next stone" shows the cards again | cards on the phone 2026-11-27; second mode: `realscale_test/mode2_test.py` 3 scenes, zone length within 1.4 cm, 8 of 9 placements right; Grasshopper needs `reload_scripts.py` (receive_photo.py keeps the mode); not yet on the phone |
| 13 | Outlines pinned to the QR marker (added 2026-11-27) | `unity/QRAnchoredOverlay.cs`: Preview and the placement check draw the outlines and the zone in AR on the tracked marker (AR Foundation image QR10), so they stay on the stones while the phone moves; until the marker is tracked, the lines fixed to the screen | built, not yet on the phone |

**End-to-end test, 2026-11-16:** a tap in the app GeoViewerAR1 (Pixel 8)
→ MQTT → Grasshopper on the Mac → 2 closed curves, one per object, areas
GH = Python (PASS). Two computer mice stood in for stones; the outlines
match them closely ([photo with the outlines drawn back](presentation/e2e_phone_photo_20261116.jpg)).
Found on the way:
- the receiver was "connected" but deaf after the Mac's network dropped
  overnight: fixed, it now subscribes again on every reconnect;
- one tap vibrated but nothing arrived: the phone's own MQTT connection
  had dropped and the app vibrates without a delivery confirmation;
  restarting the app fixed it for now (Unity follow-up in `UNITY_TASK.md`);
- everything in the frame is detected: a keyboard at the edge became a
  third "stone". Only the stones may be in the photo.

Tested in Rhino 8 + Grasshopper (macOS) on the public broker: two photos
sent with `fake_phone.py` both arrived, Grasshopper re-ran on its own and
gave closed curves with the same area as Python (`output/rhino_result.txt`, PASS).
Each photo takes a few seconds from sending to curves.

## Running it on another computer (hand-over, 2026-11-27)

What it takes: the phone with the app (built from the course project with
the scripts in `unity/`), the printed QR marker 10 (12 cm black square), the
stones on white paper, and a Windows computer with Rhino 8 running
`demo/phone_to_gh.gh`.

1. Clone this repo and check out `pipeline-phone-to-gh`.
2. The detection's Python, once: in `experiments/mode1-rule-of-thirds/`,
   `py -3.11 -m venv .venv` then `.venv\Scripts\pip install -r requirements.txt`.
   Grasshopper runs `python/replies.py` with exactly this `.venv`.
3. Rhino 8 → Grasshopper → open `experiments/phone-to-gh/demo/phone_to_gh.gh`.
   Its Python components install `compas_eve` etc. themselves the first
   time (`# r:` lines). The `listen` toggle on, the first `info` Panel says
   `connected` (broker.hivemq.com, topics `alpinear/proto1/*`).
4. On the phone: Start → pick "On two stones" or "Next to a laid stone".
   "Next to a laid stone" needs a placement check of the laid stone first
   (On two stones → ... → Check placement → Next stone), in the same
   `demo/inbox/` folder. Photos and replies land in `demo/inbox/` (not in git).

Only one Grasshopper may listen at a time (two would both answer the phone).

## Try it

1. Rhino 8 → Grasshopper → *File → Open* `demo/phone_to_gh.gh`.
   The `listen` toggle is on; the first `info` Panel says `connected`.
2. In a terminal (first time: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`):

   ```bash
   cd python
   .venv/bin/python fake_phone.py ../../photos/01_L0_AB.jpeg --ref-cm 45 --answer yes --save
   ```
3. After a few seconds the Panels fill and the outlines appear in the
   Rhino viewport (zoom extents). `fake_phone.py` prints the outlines and
   the zone that came back and saves `reply_<time>.jpg`. Send another
   photo: it updates by itself.

Needs the Mode 1 venv (`../mode1-rule-of-thirds/.venv`) for the detection.

**On Windows (Rhino 8), since 2026-11-23** the same `.gh` runs too, no Mac
needed: `py -3.11 -m venv .venv` and `.venv\Scripts\pip install -r
requirements.txt` in `../mode1-rule-of-thirds/`, then in Rhino run
`grasshopper/build_gh_file.py` (`_-RunPythonScript`, or `RhinoCode.exe
script ...`) and open `demo/phone_to_gh.gh`. The scripts pick the venv's
`Scripts\python.exe` on Windows and start it without Rhino's `PYTHONPATH` /
`PYTHONHOME` (else: "SRE module mismatch"). Tested with `fake_phone.py`:
outlines in 0.8 s, zone, tapped candidate -> `fits` in 0.6 s.
Photos and their JSON land in `demo/inbox/` (not in git).

After editing a script in `grasshopper/`, rebuild the .gh with
`build_gh_file.py` (see its header), then open it again.

## Found on the way

- **A bug in the Mode 1 detection, fixed.** `01_L0_AB` gave 3 stones at
  1280 px / JPEG 85 (the left stone split along a crack) instead of 2.
  Cause: the step that merges over-split pieces also erased the border to
  a third piece, which then touched nothing and could never be merged;
  whether that happened depended on the merge order, so tiny pixel changes
  flipped it. Fixed in `../mode1-rule-of-thirds/stone_detect.py`
  (`_merge_weak_splits`). Over 20 photo sizes / JPEG qualities: `01_L0_AB`
  20/20 correct (2 stones), `02_L0_C` 19/20 (3 stones; 4032 px at JPEG 85
  gives 2). Mode 1 tests still pass.
- **`stones` must be right.** The detection merges pieces until this many
  stones are left: `01_L0_AB` needs 2, `02_L0_C` needs 3. It is a Panel in
  Grasshopper, not in the message (the phone does not know it). Flow step 5
  ("Are these the stones?") stays needed for the cases that still go wrong.
- Photos of higher layers (`03`–`05`, stones on top of stones) are not for
  this single-photo detection; Mode 1 finds a placed stone from a
  before/after pair.
- Because the scale was taken from "the biggest stone" (`ref_cm`), a wrong
  outline changed every area. Since 2026-11-18 the QR marker in the photo
  gives the scale instead (no camera height needed); `ref_cm` is only the
  fallback when no marker is found.
- **The QR marker, 2026-11-18.** Tracker_10 (QR text `ID_10`): the black
  QR square is 12.0 cm, the red line 14.8 cm (ruler); red and green meet
  1.1 cm outside the QR's bottom-left corner (photo). OpenCV reads it at 720 px and in any rotation, with the
  corners in the QR's own order. Its 4th corner (no finder square) was
  about 5 % off and is now taken from the outline of the dark squares.
  Test: the phone photo of the two mice (2026-11-16) with the cut paper
  pasted in at the big mouse's scale (its 12.5 cm = 390 px), so only the
  small mouse is an independent check: measured 11.6 x 6.7 cm, real
  11.3 x 6.2 (big one 12.6 x 8.7, real 12.5 x 8.4). The paper was not
  taken for a stone, also with 3 cm of uncut paper around the frame. On the user's photo of a folded A4
  sheet the frame's far corner was ~0.9 cm off: the paper must lie flat.
- **First phone photos with the marker, 2026-11-18** (two ~5 cm test rocks
  touching, an uncut A4 sheet, 4 taps): the marker was found every time,
  but the outlines were wrong. Things cut by the photo's edge (laptop,
  keyboard, a knee) were taken as stones, so with `stones` = 2 the two
  real rocks were merged into one; and the rocks were so small in the
  photo (~2 % of it) that the detection's clean-up closed the gap between
  them and a single rock fell under its "too small" limit. Fixed in
  `python/replies.py` (Mode 1 unchanged): anything cut by the photo's edge
  or touching the marker's printed square is painted over in the colour
  of the ground around it and the detection runs again; with the marker
  the detection's sizes are in cm (smallest stone 8 cm², clean-up 0.5 cm).
  A first try painted the whole uncut sheet found by its colour: on a
  light table it leaked over the table up to the stones and bent their
  outlines (paper and table differ by only 14-24 in Lab), so it was
  dropped. Next 3 photos (rocks away from the paper): both rocks found,
  4.4 x 4.0 and 5.5 x 3.0 cm, the same within ~0.2 cm in all three. Still
  wrong: the dark shadow in the narrow gap between the rocks is added to
  one of them; soft shadows matter less. Photos where a rock touches the
  uncut sheet lose that rock. Older photos give exactly the same outlines
  as before, `01_L0_AB` / `02_L0_C` still 2 / 3 stones.
- Grasshopper on macOS: opening a second .gh from a script while another
  has unsaved changes pops up a save dialog that blocks Rhino. So
  `build_gh_file.py` only saves the file; open it yourself.

## Files

| file | what |
|---|---|
| `MESSAGES.md` | topics and JSON fields, phone ↔ Grasshopper. Change this first |
| `UNITY_TASK.md` | handoff for the Unity side (a Claude session on the Windows PC): project, flow, split, where files live, the task for steps 1–2, how to test |
| `MAC_TASK.md` | handoff back to the Mac: what the phone now sends, the end-to-end test, what was learned about the Unity side |
| `COURSE_PIPELINE.md` | the course tutorial's Grasshopper → Unity pipeline, summarised in text (the tutorial itself stays in OneDrive) |
| `python/fake_phone.py` | sends one photo like the phone; `--answer yes\|no` also waits for the outlines, answers and waits for the zone (`--save`: picture of what came back); `--candidate stone.jpg` then the fit check |
| `python/listen_photo.py` | checks what the phone sends against `MESSAGES.md` and saves the photo; needs only paho-mqtt, runs on Windows |
| `python/qr_marker.py` | finds the QR marker (Tracker_10) in a photo: photo px ↔ cm in its frame, covers its paper; `python qr_marker.py photo.jpg` draws what it found |
| `python/replies.py` | the replies to one photo: outlines (message 2) and rule-of-thirds zone (message 4). Run by `detect` in Grasshopper, imported by `fake_gh.py`, so both send the same |
| `python/fake_gh.py` | stands in for Grasshopper in steps 3–6: photo in → detection → outlines out (message 2), prints answers (message 3), after a Yes the rule-of-thirds zone (message 4); runs on Windows |
| `grasshopper/reload_scripts.py` | puts edited scripts into the open `.gh` and saves it (instead of re-opening the file) |
| `unity/PhotoSender.cs` | copy of the Unity script (flow steps 1-2): photo, send, vibrate on the broker's receipt, its own MQTT connection; the Unity project itself stays outside this repo |
| `unity/OutlineReview.cs` | copy of the Unity script (flow steps 4-10 and the check after placing): outlines over the live camera view, Yes / No, the size, the fit check, Show placement (contour + hatch), Check placement (green + jingle, or red + arrow) |
| `grasshopper/receive_photo.py` | GH: subscribe, save photo → `photo_path`, `ref_cm`, `photo_ts`, `info` |
| `grasshopper/detect_photo.py` | GH: photo → `photo_*.json` (curves), `.outlines.json`, `.zone.json` via `python/replies.py` |
| `grasshopper/reply_to_phone.py` | GH: sends the outlines, receives the answer, sends the zone after a Yes; answers candidates (fit) and placed photos (placement) |
| `grasshopper/zone_curves.py` | GH: the zone and the placed stone as curves / a surface in Rhino |
| `grasshopper/open_gh_file.py` | run in Rhino after `build_gh_file.py`: opens the new .gh in place of the open one |
| `python/placement.py` | the check after placing (messages 7-8): line up, what changed, the rule, the move |
| `grasshopper/build_gh_file.py` | builds `demo/phone_to_gh.gh` from the four scripts |
| `grasshopper/test_in_rhino.py` | after sending a photo: reads the open .gh, checks curves and areas → `output/rhino_result.txt` |

## Not done / limits

- The public broker: anyone who knows the topic can read the photos.
- One photo at a time. Rhino shows the stone curves and the zone (in cm, in
  the marker's frame; without the marker no zone in Rhino).
- After placing, the marker must stay where it was for the layer photo.
- With the marker: the paper flat and best cut; no stone touching it;
  stone tops above the paper look a little bigger (parallax, ~10 % for
  10 cm at 1 m), so lay the paper at the height of the stone tops.
- After a network drop (e.g. the Mac slept) the receiver reconnects and
  subscribes again by itself. (Before 2026-11-16 it reconnected without
  re-subscribing: "connected" but no photos.) If in doubt, switch `listen`
  off and on.
- Editing a script while the .gh is open: run `grasshopper/reload_scripts.py`
  instead of rebuilding and re-opening the file.

## Real-scale test (2026-11-24)

`realscale_test/`: the whole system (Grasshopper over MQTT) run blind on photos of real-size
wall stones (30–65 cm), with the true sizes sealed away until after the run. On a white
ground, with stones it had not seen, the wall outlines overlap the true stones by 97–99 %, the
zone is within ~1 cm, and 11 of 16 candidate stones get the right answer. What changed
because of it, and what still fails: `realscale_test/README.md`.

## Test pictures

`test_visuals/` is the backup of the pictures from all the tests: real phone photos with what
Grasshopper answered drawn on them, the first tests with `fake_gh.py`, and the real-scale test's
screens. Add new ones after a session with `test_visuals/collect.py`. What is where, and which
pictures are worth a look: `test_visuals/README.md`.
