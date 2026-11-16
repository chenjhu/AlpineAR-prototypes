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
| 1–2 | button, photo, vibrate, **send photo** | | **your task now** |
| 3 | | receive photo, detect stones → curves | built, tested with a fake phone |
| 4–5 | show outlines, Yes/No | curves → points, send; receive answer | later |
| 6–7 | show zone + sound | rule of thirds (exists in Python, Mode 1) | later |
| 8–10 | tap-photo of candidate, sound | fit check | later |
| 11 | button | next round | later |

## Your task: steps 1–2, nothing more

In the existing course Unity project (COMPAS XR):

1. A button "Tap when in position".
2. On tap: take a photo from the **camera feed** (not a screenshot: no
   buttons or overlays drawn on it), straight down onto the stones.
3. Encode it as JPEG, long side about 1280 px, then base64.
4. Publish one message exactly as in [`MESSAGES.md`](MESSAGES.md), message 1:
   topic `alpinear/proto1/photo`, plain JSON `{"photo": ..., "ref_cm": ..., "ts": ...}`,
   broker `broker.hivemq.com:1883`.
   `ref_cm` = real long side of the biggest stone in cm; for now a number
   field on screen or a constant 45 is fine (it is a placeholder).
5. Vibrate once the message is sent.

Not now: receiving anything, sounds, the Yes/No question, the stock
check. Those come one by one, later.

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
- **Look first.** The course Unity project already talks MQTT (the course
  Grasshopper Publisher sends geometry to it; it mentions an `MqttManager`
  and a `GeometryVisualizer`). Find how it connects and reuse that
  connection instead of adding a second MQTT library. Tell the user what
  you found before writing code.
- **Small and step by step.** The professor's feedback after the midterm:
  make it technically work, break it into steps, no "final product" full of
  code that is not needed. One small script for this task is the goal.
- **The message format is a contract.** Do not change topics or fields on
  your own. If something has to change, edit `MESSAGES.md` first and tell
  the user, because the Grasshopper side on the Mac reads the same file.
- The user prefers explanations in simple Chinese.

## How to test (no Mac needed)

On the Windows PC, in `experiments/phone-to-gh/python/`:

```
pip install paho-mqtt
python listen_photo.py
```

It prints `OK` and saves `received_<time>.jpg` for every correct message,
or `WRONG: <what is wrong>`. Done when: a tap on the phone gives `OK`, the
saved photo is a clean top view of the stones (no UI on it), and the phone
vibrated.

End-to-end (with the Mac): open `demo/phone_to_gh.gh` in Grasshopper with
`listen` on; the photo from the phone should turn into stone curves there,
exactly like with `python/fake_phone.py`. See [`README.md`](README.md).

## Next Unity batch (found in the end-to-end test, 2026-11-16)

Steps 1–2 are done and work end to end. Two fixes for `PhotoSender.cs`,
to build together with the next Unity change (each change = rebuild +
reinstall via Google Drive):

1. **Vibrate only when the photo really arrived.** Now it vibrates right
   after handing the message to `MqttManager`. In the test the phone's MQTT
   connection had dropped (app was in the background a while), the app
   still thought it was connected, vibrated, and the photo was lost.
   Publish with QoS 1 and vibrate on the broker's acknowledgement, or show
   "not sent" after a timeout.
2. **Reconnect when the connection is dead.** Check / re-establish the
   connection before each send (e.g. when the app comes back to the
   foreground), not only when `IsConnected` is false.

Also good to know: the user restarted the app to get it working again.

## Ask the user if unclear

- Android or iPhone? (An iPhone build needs a Mac with Xcode.)
- Where is the Unity project, which Unity version, and does it build to
  the phone already (e.g. the course tutorial scene)?

## When done, report

What you changed (files), how you tested it (the `listen_photo.py`
output), and anything that does not match `MESSAGES.md`. Commit only when
the user asks.
