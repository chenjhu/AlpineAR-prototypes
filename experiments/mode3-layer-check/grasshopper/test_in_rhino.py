#! python 3
"""Run mode3_component.py inside a running Rhino 8 without Grasshopper and
without touching the open document. Writes ../output/rhino_result.txt.

Easiest: open this file in Rhino's ScriptEditor and press Run.

From a terminal, with Rhino 8 open (macOS). rhinocode rejects paths with
spaces, so go through a link without spaces:

    ln -sfn "$PWD/.." /tmp/mode3                # run from grasshopper/
    export DOTNET_ROLL_FORWARD=Major            # rhinocode asks for .NET 7, Rhino ships 8
    "/Applications/Rhino 8.app/Contents/Resources/bin/rhinocode" script /tmp/mode3/grasshopper/test_in_rhino.py
"""
import os
import time
import traceback

import Rhino.Geometry as rg

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "output", "rhino_result.txt")

lines = []
try:
    ns = {"__name__": "gh_component_test"}
    t = time.time()
    with open(os.path.join(HERE, "mode3_component.py")) as f:
        exec(compile(f.read(), "mode3_component.py", "exec"), ns)
    volume = lambda breps: sum(rg.VolumeMassProperties.Compute(b).Volume for b in breps if b.IsSolid)
    lines += [
        "ran in %.2f s" % (time.time() - t),
        "cone solid: %s, volume %.3f m3" % (ns["cone"].IsSolid, ns["cone"].GetVolume()),
    ] + ["%s: %d items" % (k, len(ns[k])) for k in ("ok", "above", "outside", "cut_lines", "ar_geometry")] + [
        "volume above  : %.0f cm3" % (volume(ns["above"]) * 1e6),
        "volume outside: %.0f cm3" % (volume(ns["outside"]) * 1e6),
        "all ok parts solid: %s" % all(b.IsSolid for b in ns["ok"]),
        "ar_order: " + ns["ar_order"],
        ns["report"],
    ]
except Exception:
    lines.append(traceback.format_exc())

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
