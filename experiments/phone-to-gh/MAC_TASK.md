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
- The phone sends message 1 as plain JSON by switching that `MqttManager`
  to JSON for one message and back (`unity/PhotoSender.cs`); one MQTT
  connection, no second library.
- The app subscribes to **one** topic, set at runtime from the app's UI or
  a QR code (`GeoViewerHub.SetSubscribeTopic`), and draws every geometry
  message it receives. Receiving `alpinear/proto1/outlines` (message 2) on
  top of the course topic needs a small change on the Unity side.
- `MqttManager.autoConnect` is off: the app connects when the user presses
  connect, or on the first photo tap.
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

## How to work

Same rules as before: small steps, `MESSAGES.md` is the contract (change it
first, then tell the user), explanations to the user in simple Chinese,
commit only when the user asks.
