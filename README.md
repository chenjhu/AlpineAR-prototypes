# AlpineAR-prototypes
Independent Python experiments for the AlpineAR project

| folder | what |
|---|---|
| [`experiments/mode1-rule-of-thirds/`](experiments/mode1-rule-of-thirds/README.md) | Mode 1 (Big Rock) midterm prototype: detects two base stones in a top-view photo and shows the rule-of-thirds box for the next stone. Includes a test protocol for real stones. |
| [`experiments/mode3-layer-check/`](experiments/mode3-layer-check/README.md) | Mode 3 (3D controlling) prototype: checks a finished layer of (virtual) stones against the target truncated cone and marks in red what is above the layer plane or outside the cone. Python + a Grasshopper component. |
| [`experiments/rhino-contour-to-gh/`](experiments/rhino-contour-to-gh/README.md) | One pipeline step on its own: stone outlines detected in a photo (Mode 1 detection) are written to `stones.json` and read into Grasshopper as curves (ready-made `.gh`, tested in Rhino 8), with an area check per stone. Notes why curves need a conversion before MQTT. |
| [`experiments/phone-to-gh/`](experiments/phone-to-gh/README.md) | Next pipeline step: a photo sent over MQTT (fake phone now, Unity later) arrives in Grasshopper, the stones are detected and appear as curves automatically. `MESSAGES.md` is the message format both sides follow. |
| [`experiments/live-stone-on-paper/`](experiments/live-stone-on-paper/README.md) | Live webcam demo: outlines a stone held on a sheet of white paper in real time (the paper is only a clean background; cm² / mm when all four paper corners are visible). Successor of `archive/contour-detection/`. |
| [`archive/`](archive/) | Earlier single-stone experiments: `test_canny.py` (Canny on one photo) and `contour-detection/` (live contour + bounding box). |
