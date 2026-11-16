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

Status: format fixed; sent by `python/fake_gh.py` (stand-in for
Grasshopper, tested on the Mac with the mouse photo). The real Grasshopper
sender is the next Mac step.

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

Status: format fixed; `python/fake_gh.py` prints the answers it receives.
Grasshopper receiver not built yet.

## Planned (not built)

| # | topic | direction | content |
|---|---|---|---|
| 4 | `alpinear/proto1/zone` | GH → phone | max and min contour (rule of thirds) |
| 5 | `alpinear/proto1/candidate` | phone → GH | photo of a candidate stone, same fields as message 1 |
| 6 | `alpinear/proto1/fit` | GH → phone | `{"result": "fits" \| "too_small" \| "too_big"}` |
