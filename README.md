# AlpineAR-prototypes
Independent Python experiments for the AlpineAR project

| folder | what |
|---|---|
| [`experiments/mode1-rule-of-thirds/`](experiments/mode1-rule-of-thirds/README.md) | Mode 1 (Big Rock) midterm prototype: detects two base stones in a top-view photo and shows the rule-of-thirds box for the next stone. Includes a test protocol for real stones. |
| [`experiments/live-stone-on-paper/`](experiments/live-stone-on-paper/README.md) | Live webcam demo: finds a hand-held sheet of white paper, rectifies it and outlines every stone on it in real time, with area in cm² and size in mm. Successor of `archive/contour-detection/`. |
| [`archive/`](archive/) | Earlier single-stone experiments: `test_canny.py` (Canny on one photo) and `contour-detection/` (live contour + bounding box). |
