# Handoff: the Unity side (read this first)

For a Claude session on the Windows PC where the Unity project lives. The
Grasshopper side was built on a Mac in another session; this file is
everything that session knew that matters for Unity. Read it all before
touching the Unity project.

## The project in five lines

AlpineAR (ETH course *AlpineARchitecture*): building a dry stone wall with
a phone as the helper. The phone (Unity, COMPAS XR) photographs the layer
that is already built; Grasshopper on a laptop finds the stones in the
photo and works out where the next stone goes (rule of thirds: a stone
must cover the joint below it); the phone then helps the person pick a
fitting stone from the stone stock. Phone and laptop talk over MQTT.

## The basic prototype, as the person uses it

1. A layer of stones is already there. The person holds the phone still
   above it; a button **"Tap when in position"** appears.
2. Tap → the phone takes a photo and **vibrates** when the phone can be
   taken away.
3. Grasshopper detects the stone outlines in the photo.
4. The outlines are sent back to the phone.
5. The phone shows them and asks **"Are these the stones?"** (Yes / No;
   No = take the photo again).
6. Grasshopper computes the zone for the next stone: two contours, the
   **max** (largest allowed) and the **min** (must at least cover).
7. The phone shows both contours with a **sound**. From here the screen
   stays still (no AR tracking).
8. The person walks to the stone stock and holds the phone over a
   candidate stone, at the same height as in step 1, and taps.
9. Grasshopper checks: is the stone between the min and max contour?
10. Fits → **sound**. Does not fit → try the next stone.
11. Button **"New stone?"** → next round, back to 1.

## Who does what

Unity does what the person **touches, sees, hears** (buttons, camera,
vibration, sound, showing contours). Grasshopper does **the geometry**
(detect stones, rule of thirds, fit check). Everything between them goes
over MQTT. The chart: [`../rhino-contour-to-gh/presentation/flow_gh_unity_split.png`](../rhino-contour-to-gh/presentation/flow_gh_unity_split.png)
(solid box = built, dashed = to build, red arrow = phone → GH).

| step | Unity | Grasshopper | status |
|---|---|---|---|
| 1–2 | button, photo, vibrate, send photo | | **done**, tested end to end (2026-11-16) |
| 3 | | receive photo, detect stones → curves | **done**, tested end to end |
| 4–5 | **receive outlines, show them on the photo, ask Yes/No, send answer** | send outlines, receive answer | **your task now** (GH side: `python/fake_gh.py` stands in) |
| 6–7 | show zone + sound | rule of thirds (exists in Python, Mode 1) | later |
| 8–10 | tap-photo of candidate, sound | fit check | later |
| 11 | button | next round | later |

## Your task now (round 2): A, then B

Both go into **one** Unity build (each build = rebuild + reinstall via
Google Drive). Read [`MAC_TASK.md`](MAC_TASK.md) section "What the Windows
session found" first: that is what your last session learned about the
course scene (one subscribed topic, `MqttManager` on ProtoBuf, ...).

### A. Two fixes to `PhotoSender.cs` (found in the end-to-end test)

1. **Vibrate only when the photo really arrived.** Now it vibrates right
   after handing the message to `MqttManager`. In the test the phone's MQTT
   connection had dropped (the app was in the background a while), the app
   still thought it was connected, vibrated, and the photo was lost; the
   user had to restart the app. Publish with QoS 1 and vibrate on the
   broker's acknowledgement (PUBACK); if none comes within a few seconds,
   show "Not sent, tap again" and do not vibrate.
2. **Reconnect when the connection is dead.** Re-establish the connection
   before a send when it may be stale (e.g. the app came back to the
   foreground), not only when `IsConnected` is false.

### B. Flow steps 4–5: show the outlines, ask "Are these the stones?"

Message formats: [`MESSAGES.md`](MESSAGES.md), messages 2 and 3.

1. After sending a photo, wait for **message 2** on `alpinear/proto1/outlines`
   (plain JSON). Keep the photo you sent (the JPEG / texture) and its `ts`;
   ignore outlines whose `photo_ts` is not that `ts` (tolerance 0.001).
   This topic is in addition to the course topic the app already
   subscribes to, and it is JSON, not ProtoBuf.
2. Show **the photo you took, full screen, with the outlines drawn on it**
   (2D on the screen, not placed in AR: the phone has been taken away by
   now). Outline points are pixels of that photo, origin **top-left**, y
   **down**; a Unity texture has its origin bottom-left, so flip y. The
   photo is landscape 1280 × 720; rotate it to fit the screen if needed.
3. Two buttons: **"Are these the stones?" Yes / No**.
4. On tap, send **message 3** on `alpinear/proto1/answer`:
   `{"photo_ts": <that ts>, "ok": true|false, "ts": <now>}`.
   - Yes → show "OK, waiting for the zone…" (steps 6–7 come later).
   - No → back to step 1: the "Tap when in position" button again.
5. If no outlines arrive within ~15 s: show "No answer from Grasshopper",
   back to step 1.

Not now: the zone (steps 6–7), sounds, the stone stock. Keep it small: one
or two scripts, no extras.

## Done in round 1 (steps 1–2)

`unity/PhotoSender.cs` (copy of the Unity script): a "Tap when in position"
button takes a photo from the AR camera feed (no UI), JPEG 1280 px,
publishes message 1 as plain JSON over the scene's `MqttManager`, vibrates.
Tested from a Pixel 8 (app GeoViewerAR1) with `listen_photo.py` and end to
end with Grasshopper on the Mac.

## Where files live (Mac ↔ Windows)

- **git is the only channel for code** between the Mac (Rhino /
  Grasshopper) and the Windows PC (Unity). Every file both sides need
  (`MESSAGES.md`, this file, scripts, the `.gh` demos) is in this repo.
- **Nothing of Unity goes into OneDrive.** OneDrive syncing a Unity project
  (thousands of `Library/` files, locked files) breaks it. The same goes
  for this repo on Windows: clone it to a normal local folder (e.g.
  `C:\dev\AlpineAR-prototypes`), **not** the copy OneDrive syncs from the
  Mac, and never run git in that OneDrive copy.
- The Unity project stays outside this repo (it is big and has its own
  `Library/`). When a script of ours works, also copy it into
  `experiments/phone-to-gh/unity/` here, so the Mac side can read it.
- Course material (tutorial `.gh` / `.3dm`, PDFs) stays in OneDrive, not in
  this public repo; [`COURSE_PIPELINE.md`](COURSE_PIPELINE.md) is the text
  summary of the tutorial pipeline.

## How to work

- **Read [`COURSE_PIPELINE.md`](COURSE_PIPELINE.md)**: what the course
  Grasshopper → Unity pipeline sends, and what its scripts say about the
  Unity side (e.g. `MqttManager` skips a message equal to the previous one).
- **Look first.** Check how the scene receives messages today before
  adding the outlines topic; tell the user your plan before writing code.
- **Small and step by step.** The professor's feedback after the midterm:
  make it technically work, break it into steps, no "final product" full of
  code that is not needed.
- **The message format is a contract.** Do not change topics or fields on
  your own. If something has to change, edit `MESSAGES.md` first and tell
  the user, because the Grasshopper side on the Mac reads the same file.
- The user prefers explanations in simple Chinese.

## How to test (no Mac needed)

On the Windows PC, in `experiments/phone-to-gh/python/`:

```
pip install paho-mqtt opencv-python numpy
python fake_gh.py --stones 2 --save
```

`fake_gh.py` stands in for Grasshopper: it receives the phone's photo,
detects the stones (same Mode 1 detection as Grasshopper, from
`../mode1-rule-of-thirds/stone_detect.py` in this repo), sends message 2
back and prints every answer (message 3). With `--save` it writes
`check_<time>.jpg`: the photo with the outlines drawn from message 2, to
compare with what the phone shows. Tested on the Mac: photo → 2 outlines
→ answer, in under a second. `--stones` = how many stones (or stand-ins,
e.g. computer mice) are in the photo.

Done when, with `fake_gh.py` running and only the objects in the frame:
1. tap → the phone vibrates (only if the photo really arrived, fix A1);
2. the phone shows the photo with the outlines on the right places
   (same as `check_<time>.jpg`);
3. Yes / No → `fake_gh.py` prints `answer: ok=True` / `ok=False`;
4. No → the phone is back at "Tap when in position".

`listen_photo.py` (only paho-mqtt) still checks message 1 on its own.
Do not run `fake_gh.py` while Grasshopper on the Mac also sends outlines.

## When done, report

What you changed (files, and copy the scripts into `unity/`), how you
tested it (the `fake_gh.py` output and what the phone showed), and
anything that does not match `MESSAGES.md`. Update `MAC_TASK.md` for the
Mac side. Commit only when the user asks.
