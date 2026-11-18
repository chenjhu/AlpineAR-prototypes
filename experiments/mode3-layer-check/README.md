# Mode 3 - 3D controlling: layer check against the target cone

> "Every layer has to be as flat as possible" (p.32)

The target shape of the wall is a **truncated cone**, built in layers of equal
height. After a layer is finished, every stone is compared with the target:

- **OK**: inside the cone and below the layer's top plane `z = (layer + 1) × layer_height`
- **red, above**: the part above the top plane. The stone is too tall; the cut
  line where it meets the plane is where to chisel.
- **orange, outside**: the part outside the cone surface. It sticks out of
  the target shape; trim the outer face.

Excess under 1 cm is ignored, since nobody chisels 3 mm.

Stones are **virtual** for now: a round course of irregular stones with a few
deliberately too tall or sticking out. Later they can be replaced by scanned
meshes of real stones.

| file | what |
|---|---|
| `mode3_core.py` | target cone, virtual stones, the check (mesh booleans with trimesh + manifold) |
| `demo_mode3.py` | runs a scene: images, `mode3_scene.3dm` for Rhino, `mode3_report.json` |
| `grasshopper/mode3_component.py` | the same check as a Grasshopper Python 3 component (RhinoCommon) |
| `grasshopper/test_in_rhino.py` | runs the component inside a running Rhino 8, without Grasshopper |
| `PROTOTYPING_LOG.md`, `presentation/` | iterations and images for the slides |

## Run

```bash
pip install -r requirements.txt
python demo_mode3.py                 # layer 2
python demo_mode3.py --layer 4 --seed 3
```

Output in `output/`: `mode3_overview.png`, `mode3_closeup.png`,
`mode3_scene.3dm`, `mode3_report.json`.

## How Grasshopper and the code connect

```
            Grasshopper (sliders)                     Python (this folder)
  target ─  r_bottom, r_top, height,      same        Target(...) in mode3_core.py
            layer_height, layer           numbers
  stones ─  virtual boxes / referenced    ◀─ .3dm ─   virtual stones now,
            Rhino objects                             scanned meshes later
  check  ─  mode3_component.py            same rule   check_stone()
  result ─  ok / above / outside  ─▶ Payload Prep ─▶ MQTT ─▶ phone (AR)
```

Two ways that work today:

1. **All in Grasshopper.** Paste `grasshopper/mode3_component.py` into a
   Python 3 Script component (set-up in its header). Its `ar_geometry` output
   goes into the course's *Geometry Payload Prep* → *MQTT Publisher*, like
   the tutorial file.
2. **Code first, Grasshopper for display.** `demo_mode3.py` writes
   `mode3_scene.3dm`. Open it in Rhino; each role is its own layer (`M3 excess
   above` is red, and so on). In Grasshopper, reference those layers into
   Geometry parameters and send them on as in 1. This is the path for
   scanned stones, which arrive as meshes from outside Rhino.

### Colour in AR

The tutorial's Payload Prep sends **shape + build order only, no colour**, so
the phone cannot yet show the excess in red. Options:

- **Works today:** `ar_geometry` puts the red parts **last** in the build
  order. Moving the phone's order slider to the end reveals "what to cut" as
  the final step.
- **Ask the teaching team (Vicky):** Payload Prep already stores `order`,
  `kind` and `shape` per element (`element.treenode.attributes.update(...)`).
  Adding `color` there is one line on the Grasshopper side; the Unity
  visualiser would need to read it.

## Status

- `mode3_core.py` / `demo_mode3.py`: tested. 5 of 22 stones flagged, exactly
  the 5 made wrong on purpose; about 1 s per layer.
- `grasshopper/mode3_component.py`: **tested inside Rhino 8** with
  `grasshopper/test_in_rhino.py`: same 5 stones flagged as the Python
  version, 0.1 s. Not yet wired into a .gh file with sliders and Custom
  Preview (set-up steps are in the component's header).
