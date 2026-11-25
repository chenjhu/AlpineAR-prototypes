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
from Mode 1 (`../mode1-rule-of-thirds/rule_of_thirds.py`) on the two
largest stones of that photo. Since 2026-11-23 the **quarter rule**: the new
stone covers 1/4 to 3/4 of each supporting stone, so with B x long and C y
long (each measured from its outer end to one joint line in the middle of
the gap) its length z is `x/4 + y/4 <= z <= 3x/4 + 3y/4`.

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
  "depth_range_cm": [11.9, 14.6],
  "note": "",
  "ts": 1763297271.2
}
```

| field | type | what |
|---|---|---|
| `photo_ts` | number | the photo the zone belongs to (as in message 2) |
| `image_size` | [int, int] | width, height of that photo in pixels |
| `max` | list of [int, int] | the **allowed** zone (E_max, between the red lines of the diagrams: 3/4 of each stone from the joint): the next stone must stay inside it. Closed outline, pixels of that photo, origin top-left, y down (as in message 2) |
| `min` | list of [int, int] | the **must** zone (E_min, the red area: 1/4 of each stone from the joint): the next stone must cover at least this |
| `max_cm`, `min_cm` | list of [number, number] or null | added 2026-11-18. The same two boxes in cm, in the marker's frame. `null` without a marker |
| `length_cm` | [number, number] or null | added 2026-11-18. How long the next stone must be, along the wall, in cm: [shortest, longest] = the width of `min` and of `max`. Step 9 checks the candidate stone against this |
| `depth_cm` | number or null | added 2026-11-18. How deep (across the wall) the drawn boxes are, in cm: the depth both stones share near the joint |
| `depth_range_cm` | [number, number] or null | added 2026-11-23. How deep the next stone must be, in cm: the average depth of the two supporting stones +- 10 % (each stone's depth = the side of its smallest enclosing rectangle that runs across the wall). Step 9 checks the candidate against this too |
| `wall_cm` | object or null | added 2026-11-24. The wall's own frame in cm, for the check after placing (message 8): `origin`, `u` (along the wall), `n` (across it), `joint` (the joint line, along u), `x`, `y` (how far each base stone reaches from the joint), `depth` ([lo, hi] across: where the new stone rests), `fraction` (1/4). A point p lies at `(p - origin) . u` along and `(p - origin) . n` across. `null` without a marker. The phone does not need it |
| `note` | string | empty when there is a zone; otherwise why not (e.g. `need two base stones, found 1`), and `max` / `min` are empty |
| `ts` | number | time sent |

Pixels, like message 2, because the phone draws the zone over the same
view as the outlines (2D). With a marker in the photo the rule is
computed in cm (the marker's affine map, see `python/qr_marker.py`), and the pixel
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
{"photo": "<JPEG, base64>", "layer_ts": 1763297262.123, "tap": [640.0, 360.0], "ts": 1763297400.0}
```

| field | type | what |
|---|---|---|
| `photo` | string | top view of **one** candidate stone with the QR marker (Tracker_10) lying flat next to it, JPEG base64, as in message 1 |
| `layer_ts` | number | the `photo_ts` of the layer whose zone (message 4) the stone is for: the phone's last layer photo answered Yes |
| `tap` | [number, number], optional | added 2026-11-23. Where the person tapped the stone, in pixels **of this photo** (origin top-left, y down, as in message 2). Grasshopper then grows the stone from that point and looks only around it (`detect_tapped` in `python/replies.py`). Strongly recommended: on the 11-18 test photos it found the stone in about 17 of 20 against about 11 of 20 without (shadows by the paper or table edge were taken instead). Without it, the stone nearest the photo's middle |
| `ts` | number | time of this photo |

The photo: the marker next to the candidate but not touching it. With a
`tap`, the tapped stone is measured; without one, the candidate must be in
the **middle** of the picture (if more stones are in it, Grasshopper takes
the one nearest the middle) and nothing cut by the picture's edge counts.
Suggested on the phone: the person taps the stone on the camera view; that
tap takes the photo and gives `tap` (screen point -> camera image pixels). No
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
  "need_depth_cm": [3.0, 3.7],
  "along_cm": 4.3,
  "across_cm": 3.3,
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
| `result` | string | `fits`: length and depth both in range. `too_short`, `too_long` (length), `too_shallow`, `too_deep` (depth, added 2026-11-23): try another stone or shape it. `unknown`: no check possible, `note` says why (no marker in the photo, no stone found, no zone for `layer_ts`) |
| `length_cm` | number or null | the candidate's length in cm (long side of its outline seen from above) |
| `width_cm` | number or null | its short side in cm, checked as the depth |
| `need_cm` | [number, number] or null | the zone's `length_cm` from message 4: [shortest, longest] |
| `need_depth_cm` | [number, number] or null | added 2026-11-23. The zone's `depth_range_cm` from message 4; `null` = an older zone, only the length is checked |
| `along_cm`, `across_cm` | number or null | added 2026-11-23. How to lay it: the side that goes along the wall (z, the length the green box is made for) and the one that goes into it. Usually `length_cm` / `width_cm`; swapped when the stone only fits with its long side into the wall (then `note` says so) |
| `image_size` | [int, int] | width, height of the candidate photo |
| `outline` | list of [int, int] | the candidate's outline in that photo's pixels (as in message 2), empty if none |
| `note` | string | empty, or why `result` is `unknown` (e.g. `no stone at the tap`), or e.g. `3 stones in the photo, took the one in the middle` |
| `ts` | number | time sent |

The check (since 2026-11-23): the long side between the zone's two
lengths **and** the short side in the depth range (laid with its long side
along the wall). A stone that fits the other way round (long side into the
wall) also `fits`. If neither works, `result` names what is wrong the usual
way round, checked in this order: length, then depth. Height is not checked.
Lengths from a photo come out a little long for tall stones (`README.md`),
so a candidate just over a limit may still fit.

The phone shows the result: green outline, jingle and vibration for `fits`;
red outline and "Wrong size. Try another stone or shape it." for anything
else (flow step 10, the group's flow 1.5). Then the person tries the next
stone (message 5 again) or, after placing a fitting one, starts the next
layer photo (flow step 11, "New stone?" = message 1 again).

## 7. Photo after placing: phone → Grasshopper

Topic: `alpinear/proto1/placed`
When: the new stone is laid on the wall; the person taps it on the camera
view (or the button "Check placement"). Added 2026-11-24.

```json
{"photo": "<JPEG, base64>", "layer_ts": 1763297262.123, "tap": [640.0, 360.0], "ts": 1763297500.0}
```

| field | type | what |
|---|---|---|
| `photo` | string | top view of the wall with the new stone on it and the QR marker **where it was for the layer photo**, JPEG base64, as in message 1 |
| `layer_ts` | number | the `photo_ts` of the layer photo whose zone the stone was laid for |
| `tap` | [number, number], optional | where the person tapped the new stone, in pixels of this photo (as in message 5). Picks the new stone when more changed in the photo (a hand, a moved tool). Without it, the changed region that lies most in the zone |
| `ts` | number | time of this photo |

Hold the phone about as for the layer photo. The marker must not be moved;
it may be cut off in this photo (the photo is lined up with the layer photo
by the stones' texture, and the marker of the layer photo gives the cm).

## 8. Placement check: Grasshopper → phone

Topic: `alpinear/proto1/placement`
When: right after message 7. Added 2026-11-24.

```json
{
  "photo_ts": 1763297500.0,
  "layer_ts": 1763297262.123,
  "result": "move",
  "image_size": [1280, 720],
  "outline": [[612, 300], [700, 296], [705, 420]],
  "outline_cm": [[30.2, 41.0], [36.0, 40.8], [36.2, 33.1]],
  "max": [[300, 150], [900, 150], [900, 520], [300, 520]],
  "min": [[480, 150], [720, 150], [720, 520], [480, 520]],
  "arrow": [[650, 360], [590, 362]],
  "move_cm": [-4.1, 0.2],
  "move_along_cm": -4.1,
  "move_across_cm": 0.0,
  "details": {"cover": [0.2, 0.71], "length_cm": 34.0, "depth_cm": 29.5,
              "shift_along_cm": [-6.9, -1.4], "shift_across_cm": [-3.0, 4.2]},
  "note": "lined up by texture (529 points)",
  "ts": 1763297501.4
}
```

| field | type | what |
|---|---|---|
| `photo_ts` | number | the `ts` of message 7, unchanged |
| `layer_ts` | number | copied from message 7 |
| `result` | string | `ok`: it lies right. `move`: move it as `arrow` shows. `wrong_size`: no shift makes it right (the stone does not fit this zone). `unknown`: no check, `note` says why (no zone in cm for this layer, the photo cannot be lined up with the layer photo, no new stone found) |
| `image_size` | [int, int] | width, height of this photo |
| `outline` | list of [int, int] | the new stone in this photo's pixels (as in message 2), empty if none |
| `outline_cm` | list of [number, number] or null | the same in cm, the marker's frame |
| `base` | list of outlines | added 2026-11-25. The base stones of the layer photo (message 2), carried into **this** photo: the phone draws them red, as at the start |
| `max`, `min` | list of [int, int] | the zone of message 4 drawn into **this** photo (through the marker): the phone draws it again over the new view |
| `arrow` | [[x, y], [x, y]] or [] | for `move`: from the stone's middle to where its middle should go, pixels of this photo |
| `move_cm` | [number, number] or null | the same move in cm in the marker's frame |
| `move_along_cm`, `move_across_cm` | number or null | the same move along the wall (u) and across it (n); 0 where it is right already |
| `details` | object or null | `cover`: how much of each base stone it covers, measured from the joint (want 0.25-0.75); its `length_cm` / `depth_cm` as seen; the shifts that would be right, along and across |
| `note` | string | how the photo was lined up, or why `result` is `unknown` |
| `ts` | number | time sent |

How the new stone is found (`python/placement.py`, since 2026-11-25): it is the
stone that fitted at the stone stock (the last message 6 for this layer with
`fits`), so its outline and texture are known. 1. Its texture is matched near
the tap: its known outline is carried over exactly. 2. Else (laid another face
up), its known outline is put at the tap, turned the way the fit check said
it goes along the wall. 3. Else (no tap), it is what **changed** since the
layer photo (lined up by the stones' texture; a shadow does not count). So the
phone asks for a tap on the new stone. It is
right when, along the wall, it covers 1/4 to 3/4 of each base stone from the
joint (within 1.5 cm, the measurement's error), and across the wall its faces
stay in line with the wall's within 2.5 cm (a stone deeper than the wall: its
middle within 2.5 cm of the wall's), plus 1 cm for the measurement. A stone on
top is nearer the camera and looks a few % bigger; hold the phone above it.

The phone shows the zone (contour + hatch) in the new photo, the stone green
with the jingle and vibration for `ok`, red with a yellow arrow and "Move the
stone about N cm the way the arrow shows" for `move`. "Next stone" starts the
next layer photo (message 1).
