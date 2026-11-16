# Messages between the phone (Unity) and Grasshopper

The one file both sides follow. If you change a topic or a field, change it
here first, then in Unity and in Grasshopper.

- Broker: `broker.hivemq.com`, port `1883` (public, no login, the course broker).
  Anyone who knows the topic can read it: send nothing private.
- Payload: plain JSON (UTF-8 text). Unity needs no COMPAS library to send it.
- Do not use a field called `dtype`: COMPAS would try to turn the message into a COMPAS object.

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
| `ref_cm` | number | the real length (long side) of the biggest stone in the photo, in cm. Placeholder for the scale until the phone sends its camera height |
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
  "stones": [
    {"id": 0, "outline": [[412, 118], [455, 101], [520, 99]]},
    {"id": 1, "outline": [[437, 470], [470, 421], [560, 402]]}
  ],
  "ts": 1763297265.4
}
```

| field | type | what |
|---|---|---|
| `photo_ts` | number | the `ts` of the photo these outlines belong to (copied from message 1). The phone ignores outlines whose `photo_ts` is not its last photo (compare with a tolerance of 0.001) |
| `image_size` | [int, int] | width, height of that photo in pixels |
| `stones` | list | one entry per stone, largest first; empty list = nothing found |
| `stones[].id` | int | 0, 1, ... (the same numbers as in Grasshopper's `info` Panel) |
| `stones[].outline` | list of [int, int] | the closed outline as pixel points **in that photo**: origin top-left, x to the right, y **down** (as in the JPEG). The last point connects back to the first |
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
| `note` | string | empty when there is a zone; otherwise why not (e.g. `need two base stones, found 1`), and `max` / `min` are empty |
| `ts` | number | time sent |

Pixels, like message 2, because the phone draws the zone over the same
view as the outlines (2D). Lengths in cm need the scale (camera height or
a QR marker): not in this message yet.

Status: Tested end to end on 2026-11-16 (Pixel 8 ↔ Grasshopper on the Mac, two runs, PASS). Grasshopper computes it with the photo's
detection and sends it right after the Yes (`grasshopper/reply_to_phone.py`,
made by `python/replies.py`); the same numbers as `fake_gh.py`. Unity draws
it (`unity/OutlineReview.cs`).

## Planned (not built)

| # | topic | direction | content |
|---|---|---|---|
| 5 | `alpinear/proto1/candidate` | phone → GH | photo of a candidate stone, same fields as message 1 |
| 6 | `alpinear/proto1/fit` | GH → phone | `{"result": "fits" \| "too_small" \| "too_big"}` |
