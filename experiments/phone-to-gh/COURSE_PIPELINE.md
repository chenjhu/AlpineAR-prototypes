# The course pipeline (Grasshopper → Unity), in short

What the course tutorial `261015_ARchitecture_rhino2unity_Tutorial.gh`
does, written down in our own words, because a `.gh` is a binary file and
the tutorial is course material that does not belong in this public repo
(it is in the user's OneDrive, `04_projects/`). Read from its scripts on
the Mac; the Unity side was **not** seen, so anything about Unity below is
what the Grasshopper scripts say about it. Check it in the Unity project.

## The chain

```
Rhino geometry ─> [Order Geo] ─> [Geometry Payload Prep] ─> [MQTT Publisher] ─MQTT─> Unity (COMPAS XR)
                  build order      COMPAS Model as JSON        compas_eve
```

All Python components use the Rhino venv `venv-compas-xr2.2` with
`compas==2.13.0, compas_model==0.9.3, compas_eve==2.3.0, compas_pb==1.0.0`.
Our `grasshopper/receive_photo.py` uses the same venv, so nothing else is
installed.

## Geometry Payload Prep

- Input: a list of Rhino geometry; **the list order is the build order**.
- Output: a COMPAS Model (JSON). Each item becomes an element whose tree
  node has `order` (index), `kind` and `shape`.
- `kind` is one of `box`, `cylinder`, `sphere`, `mesh`, `point`, `points`.
  Breps become box / sphere / cylinder if they are exactly that solid,
  otherwise a mesh. **Everything else (curves!) is skipped** and listed in
  its `summary` output. So stone outlines (curves) must become points or a
  mesh before they can go to the phone (flow step 4).
- No colour, no layer, no name is sent.

## MQTT Publisher

- Broker `broker.hivemq.com`, port 1883 (default), topic from a Panel.
- Codec `json` (COMPAS JSON) or `protobuf` (via compas_pb). The script says
  protobuf is what the Unity *GeometryPublisher* side consumes; check
  which one the Unity scene expects.
- The Model is flattened for Unity into buckets:
  `boxes`, `cylinders`, `meshes`, `spheres`, `points` (lists of shapes),
  plus `radius`, `height` (from the first cylinder / sphere),
  `compas_version`, and `order` (e.g. `order[3] == "cylinders[0]"`: element
  3 is the first cylinder). Unity draws a shape at the path
  `<topic>/cylinders[0]`.
- Every message gets a fresh **`ts`** (time). Reason given in the script:
  Unity's `MqttManager.Msg` setter **skips a value equal to the previous
  one**, so sending the same geometry twice would be swallowed. Our own
  messages also carry `ts` (see `MESSAGES.md`).
- Optional `qr_frames`: `{"7": Frame, ...}`, the plane of each printed QR
  code (origin = bottom-left corner, X = red line, Y = green line), so
  Unity can place the geometry on the real QR. `qr_ids` gives the QR
  numbers (QR7 = `Tracker_07`); each student should use different ones.
- The connection is kept open between solves (`scriptcontext.sticky`).
  It connects asynchronously; there is a short wait before publishing.

## What this means for our prototype

| our need | from the course pipeline |
|---|---|
| GH → phone (outlines, zone) | reuse Payload Prep + Publisher; outlines as `points` or `mesh` |
| phone → GH (photo) | **not in the course pipeline**: our `MESSAGES.md` message 1, received by `grasshopper/receive_photo.py` |
| the phone's MQTT connection | the course Unity project's `MqttManager`; reuse it for sending too, if it can publish |
