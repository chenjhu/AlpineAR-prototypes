# Messages between the phone (Unity) and Grasshopper

The one file both sides follow. If you change a topic or a field, change it
here first, then in Unity and in Grasshopper.

- Broker: `broker.hivemq.com`, port `1883` (public, no login, the course broker).
  Anyone who knows the topic can read it: send nothing private.
- Payload: plain JSON (UTF-8 text). Unity needs no COMPAS library to send it.
- Do not use a field called `dtype`: COMPAS would try to turn the message into a COMPAS object.

## The scale: QR marker Tracker_10 in the photo

Since 2026-11-18 the scale comes from the printed COMPAS XR marker
**Tracker_10** (QR text `ID_10`) lying flat in the photo, next to the
stones. Grasshopper finds it in the photo, so the phone sends nothing new.

- Print layout (ruler): **black QR square 12.0 cm**, red line 14.8 cm.
  Red and green meet 1.1 cm left of and below the QR's bottom-left corner
  (measured on a photo).
- Coordinates in cm, the course's `qr_frames` frame: origin where red meets
  green, x along red, y along green (z up, out of the paper). The stones'
  cm outlines are in this frame.
- Best: **cut the paper along the crop marks**. Grasshopper paints the
  printed square over and ignores anything touching it (the rest of an
  uncut sheet), so **stones must not touch the paper** (nor the photo's
  edge). The paper must lie flat.
- The stones' tops are higher than the paper and look a little bigger
  (camera 1 m above, stones 10 cm high: about 10 %). Best: lay the paper at
  the height of the stone tops.
- No marker in the photo: everything works as before (pixels, scale from
  `ref_cm`), and the cm fields below are `null`.

## 1. Photo of the layer: phone → Grasshopper

Topic: `alpinear/proto1/photo`
When: the person taps "Tap when in position" (flow steps 1–2).

```json
{
  "photo": "<JPEG, base64>",
  "ref_cm": 45,
  "ts": 1763200000.0
}
```

| field | type | what |
|---|---|---|
| `photo` | string | the top-view photo, JPEG, base64-encoded. Long side about 1280 px is plenty (detection works at 640 px); a full 4032 px photo also works, it is only slower to send |
| `ref_cm` | number | the real length (long side) of the biggest stone in the photo, in cm. Only used when there is no QR marker in the photo (then it gives the scale) |
| `ts` | number | time of the photo, seconds since 1970 (Unix time) |

Status: tested end to end on 2026-11-16 (phone → Grasshopper curves, PASS).
Grasshopper side built and tested with `python/fake_phone.py`.
Unity side built (`unity/PhotoSender.cs`) and tested from a Pixel 8 with
`python/listen_photo.py`: `OK`, 1280 x 720 photo, ~100 kB.

## 2. Outlines of the stones: Grasshopper → phone

Topic: `alpinear/proto1/outlines`
When: right after Grasshopper detected the stones in photo message 1 (flow step 4).

```json
{
  "photo_ts": 1763297262.123,
  "image_size": [1280, 720],
  "qr": {"id": 10, "frame": [[180, 610], [330, 600], [335, 455], [185, 460]]},
  "stones": [
    {"id": 0, "outline": [[412, 118], [455, 101], [520, 99]],
     "outline_cm": [[31.2, 40.5], [35.0, 41.8], [40.1, 41.6]]},
    {"id": 1, "outline": [[437, 470], [470, 421], [560, 402]],
     "outline_cm": [[33.0, 12.1], [35.8, 16.0], [43.1, 17.4]]}
  ],
  "ts": 1763297265.4
}
```

| field | type | what |
|---|---|---|
| `photo_ts` | number | the `ts` of the photo these outlines belong to (copied from message 1). The phone ignores outlines whose `photo_ts` is not its last photo (compare with a tolerance of 0.001) |
| `image_size` | [int, int] | width, height of that photo in pixels |
| `stones` | list | one entry per stone, largest first; empty list = nothing found |
| `qr` | object or null | added 2026-11-18. The marker found in the photo: `id` (10) and `frame` = the corners of its 14.8 cm square in photo pixels (origin, end of the red line, opposite corner, end of the green line). `null` = no marker, no cm in this message |
| `stones[].id` | int | 0, 1, ... (the same numbers as in Grasshopper's `info` Panel) |
| `stones[].outline` | list of [int, int] | the closed outline as pixel points **in that photo**: origin top-left, x to the right, y **down** (as in the JPEG). The last point connects back to the first |
| `stones[].outline_cm` | list of [number, number] or null | added 2026-11-18. The same points in cm, in the marker's frame (see "The scale" above). `null` without a marker |
| `ts` | number | time sent (so two equal replies are never identical: the course `MqttManager` skips a message equal to the previous one) |

Why pixels in the photo and not the COMPAS geometry of the course pipeline:
the phone has been taken away by then, so step 5 shows the outlines **on
the photo it took**, on the screen (2D), not placed in AR. Pixels can be
drawn straight onto that photo; no Payload Prep (which skips curves), no
protobuf, no world coordinates.

Status: Tested end to end on 2026-11-16 (Pixel 8 ↔ Grasshopper on the Mac, two runs, PASS). Grasshopper sends it (`grasshopper/reply_to_phone.py`; the
message is made by `python/replies.py`, the same code `python/fake_gh.py`
uses), under a second after the photo arrives. Unity receives it
(`unity/OutlineReview.cs`) and draws the outlines over the live camera view.

## 3. Answer "Are these the stones?": phone → Grasshopper

Topic: `alpinear/proto1/answer`
When: the person taps Yes or No (flow step 5).

```json
{"photo_ts": 1763297262.123, "ok": true, "ts": 1763297270.0}
```

| field | type | what |
|---|---|---|
| `photo_ts` | number | which photo / outlines the answer is about |
| `ok` | bool | `true` = the outlines are right (Grasshopper goes on to step 6); `false` = wrong, the phone goes back to step 1 and takes a new photo |
| `ts` | number | time of the tap |

Status: Yes tested end to end on 2026-11-16; No (`ok: false`) tested from
`python/fake_phone.py --answer no` only. Unity sends it
(`unity/OutlineReview.cs`), QoS 1; Grasshopper receives it
(`grasshopper/reply_to_phone.py`, `info` Panel).

## 4. Zone for the next stone: Grasshopper → phone

Topic: `alpinear/proto1/zone`
When: after an answer (message 3) with `ok: true` (flow step 6). The rule
of thirds from Mode 1 (`../mode1-rule-of-thirds/rule_of_thirds.py`) on the
two largest stones of that photo.

```json
{
  "photo_ts": 1763297262.123,
  "image_size": [1280, 720],
  "max": [[300, 150], [900, 150], [900, 520], [300, 520]],
  "min": [[480, 150], [720, 150], [720, 520], [480, 520]],
  "max_cm": [[20.0, 30.1], [45.2, 30.1], [45.2, 44.0], [20.0, 44.0]],
  "min_cm": [[27.6, 30.1], [37.5, 30.1], [37.5, 44.0], [27.6, 44.0]],
  "length_cm": [9.9, 25.2],
  "depth_cm": 13.9,
  "note": "",
  "ts": 1763297271.2
}
```

| field | type | what |
|---|---|---|
| `photo_ts` | number | the photo the zone belongs to (as in message 2) |
| `image_size` | [int, int] | width, height of that photo in pixels |
| `max` | list of [int, int] | the **allowed** zone (Mode 1's white box): the next stone must stay inside it. Closed outline, pixels of that photo, origin top-left, y down (as in message 2) |
| `min` | list of [int, int] | the **must** zone (Mode 1's blue box): the next stone must cover at least this |
| `max_cm`, `min_cm` | list of [number, number] or null | added 2026-11-18. The same two boxes in cm, in the marker's frame. `null` without a marker |
| `length_cm` | [number, number] or null | added 2026-11-18. How long the next stone must be, along the wall, in cm: [shortest, longest] = the width of `min` and of `max`. Step 9 checks the candidate stone against this |
| `depth_cm` | number or null | added 2026-11-18. How deep (across the wall) the zone is, in cm |
| `note` | string | empty when there is a zone; otherwise why not (e.g. `need two base stones, found 1`), and `max` / `min` are empty |
| `ts` | number | time sent |

Pixels, like message 2, because the phone draws the zone over the same
view as the outlines (2D). With a marker in the photo the rule of thirds is
computed in cm (a true top view, the photo's tilt taken out), and the pixel
boxes are those cm boxes drawn back into the photo.

Status: Tested end to end on 2026-11-16 (Pixel 8 ↔ Grasshopper on the Mac, two runs, PASS). Grasshopper computes it with the photo's
detection and sends it right after the Yes (`grasshopper/reply_to_phone.py`,
made by `python/replies.py`); the same numbers as `fake_gh.py`. Unity draws
it (`unity/OutlineReview.cs`).

## 5. Candidate stone: phone → Grasshopper

Topic: `alpinear/proto1/candidate`
When: at the stone stock, the person holds the phone over one candidate
stone and taps (flow step 8). Added 2026-11-18.

```json
{"photo": "<JPEG, base64>", "layer_ts": 1763297262.123, "ts": 1763297400.0}
```

| field | type | what |
|---|---|---|
| `photo` | string | top view of **one** candidate stone with the QR marker (Tracker_10) lying flat next to it, JPEG base64, as in message 1 |
| `layer_ts` | number | the `photo_ts` of the layer whose zone (message 4) the stone is for: the phone's last layer photo answered Yes |
| `ts` | number | time of this photo |

The photo: the candidate in the **middle** of the picture (if more stones
are in it, Grasshopper takes the one nearest the middle), the marker next
to it but not touching it, nothing cut by the picture's edge counts. No
`ref_cm`: without the marker there is no fit check.

## 6. Fit check: Grasshopper → phone

Topic: `alpinear/proto1/fit`
When: right after message 5 (flow steps 9-10). Added 2026-11-18.

```json
{
  "photo_ts": 1763297400.0,
  "layer_ts": 1763297262.123,
  "result": "fits",
  "length_cm": 4.3,
  "width_cm": 3.3,
  "need_cm": [2.8, 5.0],
  "image_size": [1280, 720],
  "outline": [[612, 300], [700, 296], [705, 420]],
  "note": "",
  "ts": 1763297401.1
}
```

| field | type | what |
|---|---|---|
| `photo_ts` | number | the `ts` of the candidate photo (message 5), unchanged |
| `layer_ts` | number | copied from message 5 |
| `result` | string | `fits`: long enough to cover the joint and short enough to stay in the zone. `too_short`, `too_long`: try another stone. `unknown`: no check possible, `note` says why (no marker in the photo, no stone found, no zone for `layer_ts`) |
| `length_cm` | number or null | the candidate's length in cm (long side of its outline seen from above) |
| `width_cm` | number or null | its width in cm (short side), for information |
| `need_cm` | [number, number] or null | the zone's `length_cm` from message 4: [shortest, longest] |
| `image_size` | [int, int] | width, height of the candidate photo |
| `outline` | list of [int, int] | the candidate's outline in that photo's pixels (as in message 2), empty if none |
| `note` | string | empty, or why `result` is `unknown`, or e.g. `3 stones in the photo, took the one in the middle` |
| `ts` | number | time sent |

The check is only the **length along the wall**: the stone's long side
must lie between the zone's two lengths (it is laid with its long side
along the wall). Depth and height are not checked yet. Lengths from a
photo come out a little long for tall stones (`README.md`), so a
candidate just over the longest length may still fit.

The phone shows the result with a sound: one for `fits`, another for
`too_short` / `too_long` (flow step 10). Then the person tries the next
stone (message 5 again) or, after placing a fitting one, starts the next
layer photo (flow step 11, "New stone?" = message 1 again).
