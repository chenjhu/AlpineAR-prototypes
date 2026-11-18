"""Run Mode 3 on a virtual wall: finished layers below, the current layer on
top with a few stones that are too tall or stick out of the cone.

    python demo_mode3.py                    # layer 2 of the default cone
    python demo_mode3.py --layer 4 --seed 3

Writes to output/:
  mode3_overview.png, mode3_closeup.png   images for the slides
  mode3_scene.3dm                         open in Rhino: one layer per role,
                                          red = excess, ready for Grasshopper
  mode3_report.json                       per stone: OK or how much to remove
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rhino3dm
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from mode3_core import Target, check_stone, virtual_layer

COLORS = {                          # (r, g, b) 0-255, same in images and .3dm
    "target cone": (60, 140, 160),
    "layer plane": (60, 140, 160),
    "stones below": (170, 166, 156),
    "stones ok": (205, 200, 190),
    "excess above": (215, 45, 35),
    "excess outside": (240, 120, 40),
    "cut lines": (20, 20, 20),
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--layer", type=int, default=2, help="current layer (0 = bottom)")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out-dir", type=Path, default=Path("output"))
    return parser.parse_args()


def build_scene(target: Target, layer: int, seed: int):
    """Layers below the current one are correct; the current layer has three
    stones that are too tall and two that stick out."""
    below = []
    for k in range(layer):
        below += virtual_layer(target, k, seed=seed + 100 + k)
    current = virtual_layer(target, layer, seed=seed, tall=(2, 9, 15), out=(5, 12))
    return below, current


# ---------- images ----------

def rgb(name, alpha=1.0):
    r, g, b = COLORS[name]
    return (r / 255, g / 255, b / 255, alpha)


def mesh_polys(mesh, color):
    """Triangles + shaded face colours. Everything goes into ONE collection
    per image, because matplotlib only depth-sorts faces within a collection."""
    tris = mesh.vertices[mesh.faces]
    shade = 0.6 + 0.4 * np.clip(mesh.face_normals @ np.array([0.3, -0.5, 0.8]), 0, 1)
    c = np.array(color)
    fc = np.c_[np.clip(c[:3] * shade[:, None], 0, 1), np.full(len(shade), c[3])]
    return list(tris), list(fc)


def plane_polys(target, z, alpha=0.16, rings=6, sectors=48):
    """The layer plane as a disc of small faces, so it sorts against stones."""
    r = target.radius_at(z) + 0.25
    rs = np.linspace(0, r, rings + 1)
    a = np.linspace(0, 2 * np.pi, sectors + 1)
    cx, cy = target.center
    tris = []
    for i in range(rings):
        for j in range(sectors):
            p = [(rs[i] * np.cos(a[j]), rs[i] * np.sin(a[j])), (rs[i + 1] * np.cos(a[j]), rs[i + 1] * np.sin(a[j])),
                 (rs[i + 1] * np.cos(a[j + 1]), rs[i + 1] * np.sin(a[j + 1])), (rs[i] * np.cos(a[j + 1]), rs[i] * np.sin(a[j + 1]))]
            tris.append([(cx + x, cy + y, z) for x, y in p])
    return tris, [rgb("layer plane", alpha)] * len(tris)


def cone_wire(ax, target, z_max):
    a = np.linspace(0, 2 * np.pi, 120)
    for z in np.arange(0, z_max + 1e-9, target.layer_height):
        r = target.radius_at(z)
        ax.plot(target.center[0] + r * np.cos(a), target.center[1] + r * np.sin(a),
                np.full_like(a, z), color=rgb("target cone", 0.3), lw=0.6)
    for t in np.linspace(0, 2 * np.pi, 24, endpoint=False):
        ax.plot([target.center[0] + target.r_bottom * np.cos(t), target.center[0] + target.r_top * np.cos(t)],
                [target.center[1] + target.r_bottom * np.sin(t), target.center[1] + target.r_top * np.sin(t)],
                [0, target.height], color=rgb("target cone", 0.15), lw=0.5)


def render(path, target, layer, below, results, view, focus=None, title=""):
    fig = plt.figure(figsize=(12, 8), dpi=150)
    ax = fig.add_subplot(projection="3d")
    ax.set_proj_type("persp", focal_length=0.9)
    z_top = target.layer_top(layer)
    polys, colors = [], []

    def add(p):
        polys.extend(p[0]); colors.extend(p[1])

    for _, s in below:
        add(mesh_polys(s, rgb("stones below")))
    for r in results:
        if r.ok is not None:
            add(mesh_polys(r.ok, rgb("stones ok")))
        if not r.ok_flag:
            for part, name in ((r.above, "excess above"), (r.outside, "excess outside")):
                if part is not None:
                    add(mesh_polys(part, rgb(name)))
    add(plane_polys(target, z_top))
    ax.add_collection3d(Poly3DCollection(polys, facecolors=colors, edgecolors="none"))
    cone_wire(ax, target, target.height)
    for r in results:
        if not r.ok_flag:
            for line in r.section:
                ax.plot(*line.T, color=rgb("cut lines"), lw=1.8)
    if focus is None:
        R = target.r_bottom + 0.2
        ax.set_xlim(-R, R); ax.set_ylim(-R, R); ax.set_zlim(0, 1.2 * R)
        ax.set_box_aspect((1, 1, 0.6), zoom=1.25)
    else:
        c, R = focus
        ax.set_xlim(c[0] - R, c[0] + R); ax.set_ylim(c[1] - R, c[1] + R)
        ax.set_zlim(c[2] - R * 0.6, c[2] + R * 0.6)
        ax.set_box_aspect((1, 1, 0.6), zoom=1.2)
    ax.view_init(*view)
    ax.set_axis_off()
    handles = [plt.Line2D([], [], color=rgb(n), lw=8) for n in
               ("stones below", "stones ok", "excess above", "excess outside")]
    labels = ["finished layers", "current layer: OK", "excess above the layer plane",
              "excess outside the cone"]
    handles += [plt.Line2D([], [], color=rgb("target cone"), lw=1.5),
                plt.Line2D([], [], color=rgb("cut lines"), lw=1.5)]
    labels += ["target cone + layer plane", "cut line on the layer plane"]
    fig.legend(handles, labels, loc="lower left", frameon=False, fontsize=9)
    fig.suptitle(title, x=0.02, ha="left", fontsize=12)
    fig.subplots_adjust(0, 0, 1, 1)
    fig.savefig(path)
    plt.close(fig)


# ---------- Rhino export ----------

def to_rhino_mesh(mesh) -> rhino3dm.Mesh:
    m = rhino3dm.Mesh()
    for x, y, z in mesh.vertices:
        m.Vertices.Add(float(x), float(y), float(z))
    for a, b, c in mesh.faces:
        m.Faces.AddFace(int(a), int(b), int(c))
    m.Normals.ComputeNormals()
    m.Compact()
    return m


def export_3dm(path, target, layer, below, results):
    model = rhino3dm.File3dm()
    model.Settings.ModelUnitSystem = rhino3dm.UnitSystem.Meters
    layer_ids = {}
    for name, (r, g, b) in COLORS.items():
        lay = rhino3dm.Layer()
        lay.Name = f"M3 {name}"
        lay.Color = (r, g, b, 255)
        layer_ids[name] = model.Layers.Add(lay)

    def add(geo, layer_name, obj_name=""):
        attr = rhino3dm.ObjectAttributes()
        attr.LayerIndex = layer_ids[layer_name]
        attr.Name = obj_name
        model.Objects.Add(geo, attr)

    add(to_rhino_mesh(target.cone_mesh()), "target cone", "target cone")
    z_top = target.layer_top(layer)
    rr = float(target.radius_at(z_top)) + 0.25
    add(rhino3dm.Circle(rhino3dm.Point3d(target.center[0], target.center[1], z_top), rr).ToNurbsCurve(),
        "layer plane", f"layer {layer} top plane z={z_top:.2f}")
    for name, s in below:
        add(to_rhino_mesh(s), "stones below", name)
    for r in results:
        if r.ok is not None:
            add(to_rhino_mesh(r.ok), "stones ok", r.name)
        if r.ok_flag:
            continue
        if r.above is not None:
            add(to_rhino_mesh(r.above), "excess above", f"{r.name} above")
        if r.outside is not None:
            add(to_rhino_mesh(r.outside), "excess outside", f"{r.name} outside")
        for line in r.section:
            pts = [rhino3dm.Point3d(*map(float, p)) for p in line]
            add(rhino3dm.PolylineCurve(pts), "cut lines", f"{r.name} cut")
    model.Write(str(path), 8)


def main() -> int:
    args = parse_args()
    target = Target()
    if not 0 <= args.layer < target.layers:
        raise SystemExit(f"--layer must be 0..{target.layers - 1}")
    below, current = build_scene(target, args.layer, args.seed)
    results = [check_stone(n, s, target, args.layer) for n, s in current]
    bad = [r for r in results if not r.ok_flag]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    title = (f"Layer {args.layer} checked against the target cone: "
             f"{len(results) - len(bad)} of {len(results)} stones OK, {len(bad)} to trim")
    render(args.out_dir / "mode3_overview.png", target, args.layer, below, results,
           view=(28, -60), title=title)
    worst = max(bad, key=lambda r: r.above_volume + r.outside_volume, default=None)
    if worst is not None:
        c = worst.stone.vertices.mean(axis=0)
        render(args.out_dir / "mode3_closeup.png", target, args.layer, below, results,
               view=(22, np.degrees(np.arctan2(c[1], c[0])) - 35), focus=(c, 0.7),
               title=f"Close-up of {worst.name}")
    export_3dm(args.out_dir / "mode3_scene.3dm", target, args.layer, below, results)

    report = {
        "target": {"r_bottom": target.r_bottom, "r_top": target.r_top, "height": target.height,
                   "layer_height": target.layer_height, "layer": args.layer,
                   "layer_top_z": round(target.layer_top(args.layer), 3)},
        "stones": [{
            "name": r.name, "ok": r.ok_flag,
            "too_tall_by_cm": round(r.too_tall_by * 100, 1),
            "sticks_out_by_cm": round(r.sticks_out_by * 100, 1),
            "excess_above_cm3": round(r.above_volume * 1e6),
            "excess_outside_cm3": round(r.outside_volume * 1e6),
            "hint": ("OK" if r.ok_flag else
                     "; ".join(h for h in (
                         f"cut along the layer plane, {r.too_tall_by * 100:.0f} cm too tall"
                         if r.too_tall_by >= r.tolerance else "",
                         f"trim the outer face, {r.sticks_out_by * 100:.0f} cm outside the cone"
                         if r.sticks_out_by >= r.tolerance else "") if h)),
        } for r in results],
    }
    (args.out_dir / "mode3_report.json").write_text(json.dumps(report, indent=1))

    print(title)
    for s in report["stones"]:
        if not s["ok"]:
            print(f"  {s['name']}: {s['hint']}")
    print(f"saved {args.out_dir}/ (overview, close-up, mode3_scene.3dm, mode3_report.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
