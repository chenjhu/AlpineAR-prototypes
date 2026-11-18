# Handoff: back to the Mac (read this first)

For a Claude session on the Mac (Rhino / Grasshopper). The Unity side of
flow steps 1-2 was built on the Windows PC; this file is what that session
knew that matters for the Mac. [`UNITY_TASK.md`](UNITY_TASK.md) is the
other direction.

## Where things stand

| step | Unity (phone) | Grasshopper (Mac) | status |
|---|---|---|---|
| 1-2 | button, photo, vibrate, send photo | | **done**, tested with `python/listen_photo.py` |
| 3 | | receive photo, detect stones -> curves | done, tested with `fake_phone.py` only |
| 1-3 | phone -> MQTT -> Grasshopper | | **your task now: test end to end** |
| 4-11 | | | later (see `UNITY_TASK.md`) |

The message format did not change: [`MESSAGES.md`](MESSAGES.md), message 1.

## Your task: the end-to-end test

Nothing has to be built. Only the phone and the Mac are needed; the
Windows PC is not (the app is already installed on the phone).

1. `git pull` on branch `pipeline-phone-to-gh`.
2. Rhino 8 -> Grasshopper -> open `demo/phone_to_gh.gh`, `listen` on, the
   `info` Panel says `connected`. Set the `stones` Panel to the number of
   stones that will be in the photo.
3. Optional, to see the raw message too: `python/listen_photo.py` in a
   terminal on the Mac (needs only paho-mqtt).
4. On the phone (Pixel 8, Android, on Wi-Fi): open the app **GeoViewerAR1**,
   hold it still above a layer of stones, tap **"Tap when in position"**.
   The phone vibrates when the photo is sent.
5. After a few seconds the photo lands in `demo/inbox/` and the outlines
   appear as curves, as with `fake_phone.py`.

Done when: a tap on the phone gives closed curves in Grasshopper, one per
stone. Report what happened, including the photo from `demo/inbox/` and
anything that differs from the `fake_phone.py` runs.

## What the phone sends (differs from the test photos)

- **1280 x 720, landscape** (the camera sensor's orientation; held upright,
  the picture is turned 90 degrees). About 100 kB, JPEG quality 85. The
  test photos in `experiments/photos/` are phone photos with a different size and
  aspect, so detection may behave differently: this is the main thing the
  test checks.
- `ref_cm` is a constant **45** (set in the Unity Inspector). Placeholder,
  as before.
- `ts` is Unix time in seconds, with milliseconds.
- The image is the AR camera image, downscaled by nearest neighbour (no
  smoothing). If the outlines look ragged, that may be why.

## What the Windows session found about the Unity side

Useful for flow steps 4-7 (Grasshopper -> phone), not needed for this test.

- The course scene's `MqttManager` (compas-net-unity) is set to
  **ProtoBuf**. Whatever Grasshopper sends to the phone with the course
  Publisher should use the `protobuf` codec, which matches.
- The app subscribes to **one** topic, set at runtime from the app's UI or
  a QR code (`GeoViewerHub.SetSubscribeTopic`), and draws every geometry
  message it receives. Changing that topic clears all other subscriptions.
- So since round 2 the `alpinear/proto1/*` messages (plain JSON) go over
  a **second MQTT connection** that `unity/PhotoSender.cs` opens itself
  (same M2Mqtt library). The course `MqttManager` is not touched any more
  and never sees these topics. (Round 1 switched `MqttManager` to JSON for
  one message; that is gone.)
- `MqttManager.autoConnect` is off: the course connection starts when the
  user presses connect. PhotoSender's own connection starts with the app.
- The Unity project is a copy of the course project at
  `F:\ETH\AlpineArchitecture` on the PC (Unity 6000.0.79f1), not in this repo.
  The app is called GeoViewerAR1 (package `com.aha.GeoViewerAR1`) so it
  can sit next to the course app on the phone.
- The PC's USB cable did not carry data, so the app was installed by
  copying the APK over Google Drive. Each Unity change means a rebuild and
  a reinstall that way, so batch Unity changes.

## Update 2026-11-16: test passed, next Mac step

The end-to-end test above **passed** (see `README.md`). Then messages 2
and 3 were defined in `MESSAGES.md`, and `python/fake_gh.py` sends
message 2 / prints message 3, so Unity can do steps 4–5 alone
(`UNITY_TASK.md`, round 2).

**Next on the Mac:** the real Grasshopper side of steps 4–5, same output
as `fake_gh.py`:
- a component after "detect" that publishes message 2 from the detection
  JSON (`photo_*.json` holds cm with y up; message 2 wants pixels of the
  photo with y down: `x_px = x * px_per_unit`, `y_px = h - y * px_per_unit`,
  as `fake_gh.py` / `presentation/e2e_phone_photo_20261116.jpg` do);
- a receiver for message 3 (`ok` true → go on to step 6; false → wait for
  a new photo). Same `compas_eve` pattern as `receive_photo.py`, with the
  re-subscribe on reconnect.
Then: Windows' round-2 build against the real Grasshopper instead of
`fake_gh.py`.

## Update 2026-11-16: Unity round 2 done (steps 4–5)

Built on Windows and tested from the Pixel 8 against `python/fake_gh.py`
(`--stones 2`, two computer mice): photo → vibrate → 2 outlines on the
screen → Yes → `fake_gh.py` printed `answer: ok=True`, 3 runs, each a few
seconds from tap to outlines. Messages 2 and 3 as in `MESSAGES.md`,
nothing changed. **No** (`ok: false`) is built but has not been sent from
the phone yet.

What the phone does now (`unity/PhotoSender.cs`, `unity/OutlineReview.cs`):
- **Vibrates only on the broker's receipt** (QoS 1, PUBACK within 6 s);
  otherwise "Not sent, tap again". After the app was in the background it
  connects anew (the stale connection of the end-to-end test).
- Subscribes to `alpinear/proto1/outlines` from app start; ignores outlines
  whose `photo_ts` is not its last photo; gives up after 15 s ("No answer
  from Grasshopper").
- Draws the outlines **over the live camera view**, where they were in the
  photo (2D, fixed to the screen; the user preferred this to showing the
  photo itself). They match the stones only while the phone stays where it
  took the photo.
- Yes → message 3 `ok: true`, "OK, waiting for the zone…", plus a "New
  photo" button for testing. No → message 3 `ok: false`, back to "Tap when
  in position".
- The photo arrives landscape; on a portrait phone it is turned a quarter
  **counterclockwise** to match the screen.

For the real Grasshopper side: it only has to reply to the photo within
15 s, with `photo_ts` copied from message 1 unchanged.

## Update 2026-11-16: Unity round 3 done (steps 6–7), message 4 defined

**Message 4 is new** (`alpinear/proto1/zone`, see `MESSAGES.md`): after a
Yes, Grasshopper sends the rule-of-thirds zone of that photo: `max` = Mode
1's white *allowed* box, `min` = the blue *must* box, as photo pixels like
message 2, plus `note` when there is no zone. Defined on Windows, so check
it before building the Grasshopper side.

`python/fake_gh.py` now does it: on `ok: true` it runs
`pick_base_pair` + `compute_thirds` from `../mode1-rule-of-thirds/` on the
stones it detected in that photo and sends `r.box(r.allowed)` /
`r.box(r.must)`. Tested on the Pixel 8 (two computer mice): Yes → white
and blue box over the live view + a chime, 2 runs.

The phone (`unity/OutlineReview.cs`) waits for the zone from the moment
Yes is tapped (15 s): `fake_gh.py` answered so fast that the zone arrived
before the broker's receipt for the Yes, and the first build dropped it.

Who computes what: the rule of thirds belongs to Grasshopper. The phone
only draws the two boxes it receives; `fake_gh.py` stands in for
Grasshopper until it does this.

**Next on the Mac** (adds to the list above): the real Grasshopper side
of steps 4–6, same output as `fake_gh.py`:
1. publish message 2 after "detect" (list above);
2. receive message 3 (list above);
3. on `ok: true`: rule of thirds on that photo's stones → publish
   message 4. Like `detect_photo.py`, run the Mode 1 code with the Mode 1
   venv (GH's Python has no OpenCV); the zone is in the same photo pixels
   as the outlines, no scale needed.
Then test the phone against Grasshopper instead of `fake_gh.py` (do not
run both: two replies).

Open on the phone side: the outlines and the zone are fixed to the
screen, so they only match while the phone stays where it took the photo.
The fix (outlines on the ground in AR, and the camera height for the scale)
waits for a printed course QR marker (`QRLocalizer.cs`); the AR plane
height alone did not match a tape measure well, and ARCore often did not
find the surface at all. The marker's coordinates should fix both. (PhotoSender still shows
that live height reading above its button, for checking; it is not sent.)

## Update 2026-11-16: Grasshopper side of steps 4–6 done

Built on the Mac and tested end to end with the Pixel 8 (two computer mice,
Windows' `fake_gh.py` off): photo → outlines on the phone → Yes → zone +
chime, 2 runs. Outlines under a second after the photo arrives, the zone
right after the Yes. No (`ok: false`) was tested with `fake_phone.py`
only (Grasshopper sends nothing, the Panel says so).

How (`demo/phone_to_gh.gh`, rebuilt):
- `python/replies.py` holds the code for messages 2 and 4. Both
  Grasshopper and `fake_gh.py` use it, so they send the same thing
  (checked: identical outlines and zone for the same photo).
- `detect` runs it with the Mode 1 venv: it detects once and writes
  `photo_*.json` (curves), `photo_*.outlines.json` (message 2) and
  `photo_*.zone.json` (message 4) into `demo/inbox/`.
- `receive photo` has a new output `photo_ts` (message 1's `ts`,
  unchanged), which goes into messages 2 and 4.
- New component `reply to phone` (`grasshopper/reply_to_phone.py`): sends
  message 2 once per detection, listens for message 3, sends message 4
  after a Yes. Its own MQTT connection, subscribes again on reconnect.
- `python/fake_phone.py --answer yes|no [--save]` tests all this without
  the phone.

Found: after editing the scripts, the MQTT connection kept in Rhino's
memory still ran the **old** callback (no `photo_ts`), so the phone
ignored the replies. `build_gh_file.py` and `reload_scripts.py` now close
those connections first.

Open: the zone is in photo pixels only (no cm: the scale still waits for
the QR marker / camera height); Rhino shows the stone curves but not the
zone. Next in the flow: steps 8–10 (photo of a candidate stone, fit check,
messages 5–6 in `MESSAGES.md`).

## Update 2026-11-18: the scale from the QR marker Tracker_10

The scale (the "height" problem) is solved on the Mac without the camera
height: the printed COMPAS XR marker **Tracker_10** lies flat in the photo
and works as a ruler on the ground. Nothing changes on the phone.

- `python/qr_marker.py` finds it (OpenCV QR, text `ID_10`) and gives a
  homography photo px → cm in the marker's frame (origin where red meets
  green, x red, y green; the course's `qr_frames`). Print layout: QR square
  12.0 cm, red line 14.8 cm (ruler), origin 1.1 cm outside the QR corner.
- `python/replies.py` covers the marker's paper before the detection,
  writes `photo_*.json` in cm in that frame, and adds `qr`,
  `stones[].outline_cm` to message 2 and `max_cm`, `min_cm`, `length_cm`,
  `depth_cm` to message 4 (rule of thirds computed in cm). Only added
  fields: the phone's current build is unaffected. No marker → as before.
- Grasshopper: new Panel `qr_id` = 10 into `detect`. `fake_gh.py
  --qr-id 10` (default) does the same.
- Tested on a composite photo (the 2026-11-16 mice photo + the paper),
  see `README.md`. **Not yet tested on a real phone photo.**

Rules for the photo: the paper flat and best cut along the crop marks, next
to the stones but not touching them, ideally at the height of the stone
tops (parallax); things cut by the photo's edge are ignored; soft, even
light (the dark gap between touching stones is added to one of them).
First phone photos: see `README.md`, "First phone photos with the marker".

Next: steps 8–10 (messages 5 and 6): candidate photo with the marker next
to the stone, Grasshopper measures its length in cm against `length_cm`.
Later on the phone: QRLocalizer with tracker 10 to put outlines and zone
on the ground in AR, using the cm fields.

## Update 2026-11-18: Grasshopper side of steps 8–10 done

Messages 5 (candidate photo, phone → GH) and 6 (fit check, GH → phone) are
defined in `MESSAGES.md`. `reply to phone` now also listens on
`alpinear/proto1/candidate`: it saves the photo as `demo/inbox/cand_*.jpg`,
runs `python/replies.py` on it with that layer's zone (one stone, the one
nearest the middle; its long side in cm against the zone's `length_cm`)
and sends `fits` / `too_short` / `too_long` / `unknown` with the lengths.
New input `qr_id` on `reply to phone` (the same Panel as `detect`).
`fake_gh.py` answers candidates too; `fake_phone.py --candidate` tests it.
Tested on the Mac with the real Grasshopper: two candidates cut out of a
phone photo, 6.0 cm → `too_long`, 4.3 cm → `fits` (zone 2.8–5.0 cm),
reply 0.3–0.4 s after the photo. The phone side is round 4 in
`UNITY_TASK.md`.

Not checked: depth / width and height of the candidate (only the length);
a real candidate photo from the phone.

## How to work

Same rules as before: small steps, `MESSAGES.md` is the contract (change it
first, then tell the user), explanations to the user in simple Chinese,
commit only when the user asks.
