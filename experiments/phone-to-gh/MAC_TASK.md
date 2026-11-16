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

## How to work

Same rules as before: small steps, `MESSAGES.md` is the contract (change it
first, then tell the user), explanations to the user in simple Chinese,
commit only when the user asks.
