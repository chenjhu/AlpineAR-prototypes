# Mode 3 prototyping log

Same format as Mode 1: problem -> cause -> change -> result, with a one-line
**Say it** for the slides. Images in [`presentation/`](presentation/), prefixed
`m3itNN`.

| # | iteration | data | outcome |
|---|---|---|---|
| 1 | Layer check against the target cone | virtual stones, 1 course + 2 finished courses | works in Python; GH component written |
| 2 | **Grasshopper component run inside Rhino** | same virtual course | 2 bugs found and fixed; matches Python |

---

## 1. Layer check against the target cone

- **Starting point:** the course's Grasshopper tutorial
  (`261015_ARchitecture_rhino2unity_Tutorial.gh`), read by decompressing the
  file and decoding its Python components. Its pipeline: ordered geometry
  -> *Geometry Payload Prep* (COMPAS Model JSON with `order`, `kind`, `shape`
  per element) -> *MQTT Publisher* (`broker.hivemq.com`) -> phone. Finding:
  **no colour is sent**, only shape and order.
- **Rule:** a stone part is OK if it lies inside the truncated cone and below
  the current layer's top plane. Everything else is excess: *above* (too
  tall, red) or *outside* (sticks out of the cone, orange). Excess under 1 cm
  is ignored.
- **How:** mesh booleans (trimesh + manifold): `ok = stone ∩ cone ∩ below`,
  `above = stone − below`, `outside = (stone ∩ below) − cone`. The cone is a
  128-sided polygon drawn *around* the circle, so faceting never cuts into
  the target. Cut line = section of the stone at the top plane.
- **Virtual stones:** a round course along the cone surface (22 stones in
  layer 2), 3 made too tall and 2 pushed outward on purpose, plus 2 finished
  courses below for context.
- **Result:** exactly the 5 wrong stones flagged (11-14 cm too tall, 9 cm
  outside); 17 OK; about 1 s per layer. Exports `mode3_scene.3dm` (one Rhino
  layer per role, red/orange) and `mode3_report.json` (per-stone hint, e.g.
  "cut along the layer plane, 14 cm too tall").
- **Rendering fix:** in the first images the layer plane covered stones that
  were in front of it. Matplotlib only depth-sorts within one collection, so
  everything now goes into one collection, with the plane split into small
  faces. The first stones were also small with big gaps and did not read as
  a wall; they are now longer, blockier and tighter.
- **Grasshopper:** `grasshopper/mode3_component.py` does the same with
  RhinoCommon Brep booleans; it outputs `ar_geometry` ordered cone -> OK
  parts -> red parts, so the phone's order slider shows "what to cut" last.
  **Not yet run inside Rhino.**
- **Images:** `m3it01a` (overview), `m3it01b` (close-up of a too-tall stone).
- **Say it:** "After each layer, the app compares the stones with the target cone and paints in red exactly what sticks out: above the layer plane, or outside the cone."

## 2. Grasshopper component run inside Rhino

- **How:** Rhino 8's `rhinocode` command line runs a script inside the open
  Rhino. Two obstacles: it asks for .NET 7 while Rhino ships .NET 8
  (`DOTNET_ROLL_FORWARD=Major`), and it rejects paths with spaces (run it
  through a link without spaces). `grasshopper/test_in_rhino.py` executes the
  component code with default inputs and writes the results to a file,
  without touching the open document.
- **First run:** the cone was right (22.016 m³, exactly the frustum
  formula), but **0 OK parts, 0 red parts**, and no stone too tall.
- **Bug 1, stones hanging below their layer:** each virtual stone is a box
  on a plane with x along the wall and y pointing outward. x × y then points
  **down**, so every box hung below its layer (z 0.34-0.60 instead of
  0.60-0.90). Fix: y points inward, so x × y = +z.
- **Bug 2, Rhino booleans and containment:** Rhino's Brep booleans work by
  intersecting surfaces. When a stone lies entirely inside the cone (most
  stones), no surfaces cross and the intersection comes back **empty**
  instead of the whole stone. The Python version (manifold) does not have
  this problem. Fix: if Rhino returns nothing, test the stone's corners
  against the other solid (all inside -> whole stone; all outside -> nothing).
- **Result:** same 5 stones flagged as in Python (11-14 cm too tall, 9 cm
  outside), 17 of 22 OK, all parts valid solids, 0.1 s. `ar_geometry` has 28
  items in AR order: cone, 22 OK, 3 red, 2 orange.
- **Say it:** "We run the same check twice, in Python and natively in Grasshopper, and they agree; testing inside Rhino caught two bugs that only appear there."
