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

Status: Grasshopper side built and tested with `python/fake_phone.py`.
Unity side not built yet.

## Planned (not built)

| # | topic | direction | content |
|---|---|---|---|
| 2 | `alpinear/proto1/outlines` | GH → phone | the detected outlines, as points (Payload Prep skips curves) |
| 3 | `alpinear/proto1/answer` | phone → GH | `{"ok": true}` after "Are these the stones?" |
| 4 | `alpinear/proto1/zone` | GH → phone | max and min contour (rule of thirds) |
| 5 | `alpinear/proto1/candidate` | phone → GH | photo of a candidate stone, same fields as message 1 |
| 6 | `alpinear/proto1/fit` | GH → phone | `{"result": "fits" \| "too_small" \| "too_big"}` |
