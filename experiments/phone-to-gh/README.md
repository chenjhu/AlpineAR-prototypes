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
| 6 | Unity sends the photo | a publisher in the Unity app, following `MESSAGES.md` | next (Windows) |

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

- **Detection is on the edge for some photos.** `01_L0_AB` gives 2 stones at
  full size but 3 at 1280 px / JPEG 85: the left stone splits along a crack.
  Only 1 of 20 size/quality combinations does this, so it is not the size
  or the compression; the detection itself sits on a threshold there.
  Two other photos (`02_L0_C`, `05_L2_F`) also change count between full
  size and 1280 px. This is why flow step 5 ("Are these the stones?") is
  needed, and it is a task for the detection step, not for this transport.
- Because the scale is taken from "the biggest stone" (`ref_cm`), a split
  stone changes every area. Another reason to replace `ref_cm` with the
  camera height (or a marker).
- `stones` (how many stones are expected) is a Panel in Grasshopper, not
  in the message: the phone does not know it.
- Grasshopper on macOS: opening a second .gh from a script while another
  has unsaved changes pops up a save dialog that blocks Rhino. So
  `build_gh_file.py` only saves the file; open it yourself.

## Files

| file | what |
|---|---|
| `MESSAGES.md` | topics and JSON fields, phone ↔ Grasshopper. Change this first |
| `python/fake_phone.py` | sends one photo like the phone will |
| `grasshopper/receive_photo.py` | GH: subscribe, save photo → `photo_path`, `ref_cm`, `info` |
| `grasshopper/detect_photo.py` | GH: photo → `photo_*.json` via the Mode 1 detection |
| `grasshopper/build_gh_file.py` | builds `demo/phone_to_gh.gh` from the three scripts |
| `grasshopper/test_in_rhino.py` | after sending a photo: reads the open .gh, checks curves and areas → `output/rhino_result.txt` |

## Not done / limits

- The public broker: anyone who knows the topic can read the photos.
- One photo at a time; nothing is sent back to the phone yet (flow step 4–5).
- If the connection drops, switch `listen` off and on.
