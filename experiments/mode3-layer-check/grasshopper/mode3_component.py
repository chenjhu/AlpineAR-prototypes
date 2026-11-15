#! python 3
"""Mode 3 layer check, as a Grasshopper Python 3 Script component.

Same logic as ../mode3_core.py, but with RhinoCommon Breps, so it runs inside
Grasshopper and its outputs can go straight into the course's
"Geometry Payload Prep" -> "MQTT Publisher" (Send to Unity).

Set-up (Rhino 8, Grasshopper):
  1. Add a "Python 3 Script" component, paste this file into it.
  2. Inputs (right-click each > Type hint / Access):
       r_bottom      float   radius at the bottom of the cone [m]   (2.0)
       r_top         float   radius at the top [m]                  (1.4)
       height        float   total height [m]                       (2.4)
       layer_height  float   height of one layer [m]                (0.3)
       layer         int     current layer, 0 = bottom              (2)
       stones        Brep or Mesh, LIST access. Leave empty to use virtual stones.
       seed          int     virtual stones only                    (1)
       tolerance     float   ignore excess smaller than this [m]    (0.01)
     Number sliders work for all of them, like the layer slider in our
     earlier file.
  3. Outputs:
       cone          the target truncated cone (Brep)
       plane         the current layer's top plane, as a disc (Brep)
       ok            stone parts inside the cone and below the plane
       above         excess above the plane     -> preview RED
       outside       excess outside the cone    -> preview ORANGE
       cut_lines     where each too-tall stone meets the plane (chisel line)
       ar_geometry   everything in AR order: cone, ok parts, then red parts
       ar_order      text: which ar_geometry index is what
       report        one line per stone
  4. Preview: Custom Preview with a red Colour Swatch on `above`, orange on
     `outside`; turn off the component's own preview.

Tested inside Rhino 8 (run through rhinocode, see ../PROTOTYPING_LOG.md, 2).
The same calculation in plain Python: ../mode3_core.py.
"""
import math
import random

import Rhino.Geometry as rg
import scriptcontext as sc

TOL = sc.doc.ModelAbsoluteTolerance if sc.doc else 0.001


def value(x, default):
    return default if x is None else x


def truncated_cone(rb, rt, h):
    profile = rg.Line(rg.Point3d(rb, 0, 0), rg.Point3d(rt, 0, h))
    axis = rg.Line(rg.Point3d(0, 0, 0), rg.Point3d(0, 0, 1))
    return rg.Brep.CreateFromRevSurface(rg.RevSurface.Create(profile, axis), True, True)


def radius_at(rb, rt, h, z):
    z = min(max(z, 0.0), h)
    return rb + (rt - rb) * z / h


def below_box(z, size):
    return rg.Box(rg.Plane.WorldXY, rg.Interval(-size, size), rg.Interval(-size, size),
                  rg.Interval(-size, z)).ToBrep()


def virtual_stones(rb, rt, h, lh, k, seed, tall=(2, 9, 15), out=(5, 12)):
    """A course of block-like stones along the cone surface; a few too tall
    or sticking out, to see the check work."""
    rnd = random.Random(seed)
    z0 = k * lh
    r_mid = radius_at(rb, rt, h, z0 + lh / 2)
    length = 0.5
    count = int(2 * math.pi * r_mid / (length + 0.015))
    stones = []
    for i in range(count):
        a = 2 * math.pi * (i + rnd.uniform(-0.08, 0.08)) / count
        L = length * rnd.uniform(0.9, 1.0)
        D = rnd.uniform(0.34, 0.42)
        H = lh * (rnd.uniform(1.35, 1.5) if i in tall else rnd.uniform(0.82, 0.97))
        outward = rnd.uniform(0.06, 0.10) if i in out else -rnd.uniform(0.015, 0.03)
        r_c = radius_at(rb, rt, h, z0 + H) + outward - D / 2
        origin = rg.Point3d(r_c * math.cos(a), r_c * math.sin(a), z0)
        # x along the wall, y pointing inward: x × y = +z, so the box stands
        # on the layer (with y pointing outward it would hang below it)
        x_axis = rg.Vector3d(-math.sin(a), math.cos(a), 0)
        y_axis = rg.Vector3d(-math.cos(a), -math.sin(a), 0)
        plane = rg.Plane(origin, x_axis, y_axis)
        box = rg.Box(plane, rg.Interval(-L / 2, L / 2), rg.Interval(-D / 2, D / 2), rg.Interval(0, H))
        stones.append(box.ToBrep())
    return stones


def as_brep(geo):
    if isinstance(geo, rg.Brep):
        return geo
    if isinstance(geo, rg.Mesh):
        return rg.Brep.CreateFromMesh(geo, True)
    if isinstance(geo, rg.Extrusion):
        return geo.ToBrep()
    if isinstance(geo, rg.Box):
        return geo.ToBrep()
    return None


def bool_list(result):
    return [b for b in (result or []) if b is not None and b.IsValid]


def inside(a, b):
    """True / False if every vertex of `a` is inside / outside solid `b`,
    None if mixed."""
    flags = {b.IsPointInside(v.Location, TOL, False) for v in a.Vertices}
    return flags.pop() if len(flags) == 1 else None


def intersect(a, b):
    """a ∩ b. Rhino's Brep booleans work by intersecting surfaces, so when
    one solid lies entirely inside or outside the other (no surfaces cross)
    they return nothing; decide those cases with a point test."""
    result = bool_list(rg.Brep.CreateBooleanIntersection(a, b, TOL))
    if result:
        return result
    return [a] if inside(a, b) else []


def difference(a, b):
    """a - b, with the same containment handling as intersect()."""
    result = bool_list(rg.Brep.CreateBooleanDifference(a, b, TOL))
    if result:
        return result
    return [] if inside(a, b) else [a]


def points_of(brep):
    return [v.Location for v in brep.Vertices]


def run(r_bottom, r_top, height, layer_height, layer, stones, seed, tolerance):
    rb, rt, h = value(r_bottom, 2.0), value(r_top, 1.4), value(height, 2.4)
    lh, k = value(layer_height, 0.3), int(value(layer, 2))
    tol_ex = value(tolerance, 0.01)
    z_top = (k + 1) * lh

    cone = truncated_cone(rb, rt, h)
    top_plane = rg.Plane(rg.Point3d(0, 0, z_top), rg.Vector3d.ZAxis)
    disc = rg.Brep.CreatePlanarBreps(rg.Circle(top_plane, radius_at(rb, rt, h, z_top) + 0.25).ToNurbsCurve(), TOL)[0]
    below = below_box(z_top, 4 * max(rb, rt) + 10)

    breps = [as_brep(s) for s in (stones or [])]
    breps = [b for b in breps if b is not None]
    if not breps:
        breps = virtual_stones(rb, rt, h, lh, k, int(value(seed, 1)))

    ok, above, outside, cuts, report = [], [], [], [], []
    for i, stone in enumerate(breps):
        name = "L{}-{:02d}".format(k, i + 1)
        ok_parts = [p2 for p in intersect(stone, cone) for p2 in intersect(p, below)]
        above_parts = difference(stone, below)
        outside_parts = [p2 for p in intersect(stone, below) for p2 in difference(p, cone)]

        pts = points_of(stone)
        too_tall = max(0.0, max(p.Z for p in pts) - z_top)
        sticks_out = max(0.0, max(math.hypot(p.X, p.Y) - radius_at(rb, rt, h, p.Z) for p in pts))

        ok += ok_parts
        if too_tall < tol_ex and sticks_out < tol_ex:
            report.append("{}: OK".format(name))
            continue
        above += above_parts
        outside += outside_parts
        if above_parts:
            _, curves, _ = rg.Intersect.Intersection.BrepPlane(stone, top_plane, TOL)
            cuts += list(curves or [])
        hints = []
        if too_tall >= tol_ex:
            hints.append("cut along the layer plane, {:.0f} cm too tall".format(too_tall * 100))
        if sticks_out >= tol_ex:
            hints.append("trim the outer face, {:.0f} cm outside the cone".format(sticks_out * 100))
        report.append("{}: {}".format(name, "; ".join(hints)))

    # AR order: the phone slider shows elements in this order, so the red
    # parts come last ("what to cut" appears as the final step).
    ar_geometry = [cone] + ok + above + outside
    n_ok = len(ok)
    ar_order = ("0: target cone | 1-{}: stones OK | {}-{}: excess above (red) | {}-{}: excess outside (orange)"
                .format(n_ok, n_ok + 1, n_ok + len(above), n_ok + len(above) + 1, len(ar_geometry) - 1))
    bad = sum(1 for line in report if not line.endswith("OK"))
    report.insert(0, "Layer {} (top at z = {:.2f} m): {} of {} stones OK".format(
        k, z_top, len(report) - bad, len(report)))
    return cone, disc, ok, above, outside, cuts, ar_geometry, ar_order, "\n".join(report)


cone, plane, ok, above, outside, cut_lines, ar_geometry, ar_order, report = run(
    globals().get("r_bottom"), globals().get("r_top"), globals().get("height"),
    globals().get("layer_height"), globals().get("layer"), globals().get("stones"),
    globals().get("seed"), globals().get("tolerance"))
