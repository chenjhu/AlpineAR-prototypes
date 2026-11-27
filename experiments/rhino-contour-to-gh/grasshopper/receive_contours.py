#! python 3
"""Stone outlines detected in a photo (Python) -> curves in Grasshopper.

Reads the stones.json written by ../python/photo_to_json.py and turns every
stone into a closed polyline. Nothing else: no MQTT, no rule of thirds.

Set-up (Rhino 8, Grasshopper) - or just open ../demo/receive_contours.gh:
  Python 3 Script component with
  Inputs:
    json_path  str   path to stones.json; a relative path is relative to the
                     .gh file ("stones.json" = next to it)
    refresh    bool  wire a Button: press it after photo_to_json.py wrote a
                     new file (Grasshopper does not watch files on its own)
  Outputs:
    contours   one closed curve per stone (Rhino units = the file's unit)
    centroids  one point per stone
    info       per stone: Grasshopper's area next to Python's -> Panel.
               Equal areas = the outline arrived complete and unchanged.
"""
import json
import os

import Rhino.Geometry as rg


def resolve(path):
    if os.path.isabs(path):
        return path
    try:
        gh_file = ghenv.Component.OnPingDocument().FilePath  # noqa: F821 (Grasshopper)
    except NameError:
        gh_file = None
    if not gh_file:
        raise ValueError("Save the .gh file first, or give an absolute json_path")
    return os.path.join(os.path.dirname(gh_file), path)


def load(path):
    with open(path) as f:
        data = json.load(f)
    curves, points, lines = [], [], []
    unit = data["unit"]
    for s in data["stones"]:
        pts = [rg.Point3d(x, y, 0) for x, y in s["contour"]]
        pts.append(pts[0])
        crv = rg.PolylineCurve(pts)
        area = rg.AreaMassProperties.Compute(crv).Area
        diff = abs(area - s["area"]) / s["area"] * 100
        curves.append(crv)
        points.append(rg.Point3d(s["centroid"][0], s["centroid"][1], 0))
        lines.append("stone %d: area GH %.1f / Python %.1f %s2 (%s), %d points" % (
            s["id"], area, s["area"], unit, "same" if diff < 0.1 else "DIFFERS %.0f%%" % diff,
            len(s["contour"])))
    head = "%d stones from photo %s, unit %s" % (len(curves), data["source"], unit)
    return curves, points, "\n".join([head] + lines)


if json_path:  # noqa: F821 (GH input)
    contours, centroids, info = load(resolve(json_path))  # noqa: F821
else:
    contours, centroids, info = [], [], "no file yet (json_path is empty)"
