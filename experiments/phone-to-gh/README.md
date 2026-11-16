# Phone → Grasshopper: a photo over MQTT

Steps 1–3 of the basic prototype
([chart](../rhino-contour-to-gh/presentation/flow_gh_unity_split.png)),
the Grasshopper side only:

> **A photo sent over MQTT arrives in Grasshopper, is saved, the stones are
> detected, and their outlines appear as curves, with no button pressed.**

The course pipeline only goes GH → phone. This is the missing other
direction. The phone is replaced by `python/fake_phone.py`, which sends
exactly what the Unity app will send, so the Unity side only has to follow
[`MESSAGES.md`](MESSAGES.md).

```
fake_phone.py ──MQTT──> [receive photo] ─> [detect] ─> [receive contours] ─> curves
 (later: Unity)          inbox/photo_*.jpg   photo_*.json    (from rhino-contour-to-gh)
```

## The step broken down

| # | what | technique | status |
|---|---|---|---|
| 1 | Message format both sides follow | [`MESSAGES.md`](MESSAGES.md): plain JSON, photo as base64 JPEG, `ref_cm`, `ts` | done |
| 2 | Pretend phone | `python/fake_phone.py`: resize to 1280 px, JPEG, paho-mqtt (no COMPAS, like Unity) | done |
| 3 | Grasshopper listens | `grasshopper/receive_photo.py`: `compas_eve` Subscriber, same venv as the course Publisher; the MQTT thread saves the photo and asks GH to re-run | done |
| 4 | Detect the stones | `grasshopper/detect_photo.py`: runs the existing `photo_to_json.py` with the Mode 1 venv (GH's Python has no OpenCV) | done |
| 5 | Outlines → curves | `receive_contours.py` from `../rhino-contour-to-gh`, unchanged except: empty input → "no file yet" | done |
| 6 | Unity sends the photo | `unity/PhotoSender.cs` in the course Unity project: AR camera image (no UI), JPEG 1280 px, sent as plain JSON over the scene's `MqttManager` | done, tested with `listen_photo.py` (end-to-end with GH not yet) |

Tested in Rhino 8 + Grasshopper (macOS) on the public broker: two photos
sent with `fake_phone.py` both arrived, Grasshopper re-ran on its own and
gave closed curves with the same area as Python (`output/rhino_result.txt`, PASS).
Each photo takes a few seconds from sending to curves.

## Try it

1. Rhino 8 → Grasshopper → *File → Open* `demo/phone_to_gh.gh`.
   The `listen` toggle is on; the first `info` Panel says `connected`.
2. In a terminal (first time: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`):

   ```bash
   cd python
   .venv/bin/python fake_phone.py ../../photos/01_L0_AB.jpeg --ref-cm 45
   ```
3. After a few seconds the three Panels fill and the outlines appear in the
   Rhino viewport (zoom extents). Send another photo: it updates by itself.

Needs the Mode 1 venv (`../mode1-rule-of-thirds/.venv`) for the detection.
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
- Because the scale is taken from "the biggest stone" (`ref_cm`), a wrong
  outline changes every area. Another reason to replace `ref_cm` with the
  camera height (or a marker).
- Grasshopper on macOS: opening a second .gh from a script while another
  has unsaved changes pops up a save dialog that blocks Rhino. So
  `build_gh_file.py` only saves the file; open it yourself.

## Files

| file | what |
|---|---|
| `MESSAGES.md` | topics and JSON fields, phone ↔ Grasshopper. Change this first |
| `UNITY_TASK.md` | handoff for the Unity side (a Claude session on the Windows PC): project, flow, split, where files live, the task for steps 1–2, how to test |
| `COURSE_PIPELINE.md` | the course tutorial's Grasshopper → Unity pipeline, summarised in text (the tutorial itself stays in OneDrive) |
| `python/fake_phone.py` | sends one photo like the phone will |
| `python/listen_photo.py` | checks what the phone sends against `MESSAGES.md` and saves the photo; needs only paho-mqtt, runs on Windows |
| `unity/PhotoSender.cs` | copy of the Unity script (flow steps 1-2); the Unity project itself stays outside this repo |
| `grasshopper/receive_photo.py` | GH: subscribe, save photo → `photo_path`, `ref_cm`, `info` |
| `grasshopper/detect_photo.py` | GH: photo → `photo_*.json` via the Mode 1 detection |
| `grasshopper/build_gh_file.py` | builds `demo/phone_to_gh.gh` from the three scripts |
| `grasshopper/test_in_rhino.py` | after sending a photo: reads the open .gh, checks curves and areas → `output/rhino_result.txt` |

## Not done / limits

- The public broker: anyone who knows the topic can read the photos.
- One photo at a time; nothing is sent back to the phone yet (flow step 4–5).
- If the connection drops, switch `listen` off and on.
