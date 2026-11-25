#! python 3
"""The zone for the next stone in Rhino (added 2026-11-24), next to the stone
curves of "receive contours", in the same cm (the QR marker's frame).

Inputs:
  json_path    str  from "detect": photo_<time>.json; the zone is photo_<time>.zone.json
                    next to it (message 4)
  placed_path  str  from "reply to phone": the last placement check
                    (placed_<time>.placement.json, message 8)
Outputs:
  allowed  the allowed zone (max): a closed curve. The new stone stays inside it
  must     the must zone (min): a planar surface (shown filled, like the hatch on
           the phone). The new stone covers it
  placed   the new stone after placing, if it was checked for this layer: a closed curve
  info     -> Panel

Without the marker in the layer photo the zone has no cm: nothing is drawn.
"""
import json
import os

import Rhino.Geometry as rg
import scriptcontext as sc


def closed(points):
    pts = [rg.Point3d(x, y, 0) for x, y in points]
    pts.append(pts[0])
    return rg.PolylineCurve(pts)


def run(path, placed_file):
    stem = os.path.splitext(path)[0]
    zone_path = stem + ".zone.json"
    if not os.path.exists(zone_path):
        return None, None, None, "no zone file next to %s" % os.path.basename(path)
    with open(zone_path) as f:
        zone = json.load(f)
    if zone.get("note"):
        return None, None, None, "no zone: " + zone["note"]
    if not zone.get("max_cm"):
        return None, None, None, "the zone has no cm (no QR marker in the layer photo)"
    # As on the phone: the zone only after the person said Yes to the outlines
    # ("reply to phone" keeps which photos were answered Yes).
    answered = sc.sticky.get("alpinear.reply_to_phone", {}).get("answered", set())
    if not any(abs(t - float(zone["photo_ts"])) < 0.001 for t in answered):
        return None, None, None, "zone ready, shown after the Yes on the phone"
    allowed = closed(zone["max_cm"])
    must_curve = closed(zone["min_cm"])
    breps = rg.Brep.CreatePlanarBreps(must_curve, 0.01)
    must = breps[0] if breps else must_curve
    lines = ["zone of %s: next stone %.1f-%.1f cm long, %.1f-%.1f cm deep" % (
        os.path.basename(stem), zone["length_cm"][0], zone["length_cm"][1],
        zone["depth_range_cm"][0], zone["depth_range_cm"][1])]
    placed = None
    if placed_file and os.path.exists(placed_file):
        with open(placed_file) as f:
            msg = json.load(f)
        if abs(float(msg.get("layer_ts", -1)) - float(zone["photo_ts"])) < 0.001:
            if msg.get("outline_cm"):
                placed = closed(msg["outline_cm"])
            lines.append("placed (%s): %s%s" % (
                os.path.basename(placed_file), msg["result"],
                ", move %.1f cm along, %.1f across" % (msg["move_along_cm"], msg["move_across_cm"])
                if msg["result"] == "move" else ""))
    return allowed, must, placed, "\n".join(lines)


allowed = must = placed = None
info = "waiting for a photo"
if json_path:  # noqa: F821 (GH inputs)
    allowed, must, placed, info = run(json_path, placed_path)  # noqa: F821
