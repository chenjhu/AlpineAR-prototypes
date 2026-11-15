#! python 3
"""Run receive_contours.py inside a running Rhino 8 on ../demo/stones.json
(made by ../python/photo_to_json.py from a real photo). Touches no Rhino file.
Writes ../output/rhino_result.txt.

Easiest: open this file in Rhino's ScriptEditor and press Run.
From a terminal (macOS), as in ../../mode3-layer-check:

    ln -sfn "$PWD/.." /tmp/contour2gh           # run from grasshopper/
    export DOTNET_ROLL_FORWARD=Major
    "/Applications/Rhino 8.app/Contents/Resources/bin/rhinocode" script /tmp/contour2gh/grasshopper/test_in_rhino.py
"""
import json
import os
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
JSON = os.path.normpath(os.path.join(HERE, "..", "demo", "stones.json"))
OUT = os.path.join(HERE, "..", "output", "rhino_result.txt")

lines = []
try:
    ns = {"__name__": "gh_component_test", "json_path": JSON, "refresh": False}
    with open(os.path.join(HERE, "receive_contours.py")) as f:
        exec(compile(f.read(), "receive_contours.py", "exec"), ns)
    lines.append(ns["info"])
    expected = len(json.load(open(JSON))["stones"])
    assert len(ns["contours"]) == expected, "expected %d curves" % expected
    assert all(c.IsClosed and c.IsPlanar() for c in ns["contours"]), "every curve closed and flat"
    assert "DIFFERS" not in ns["info"], "areas in Grasshopper and Python must agree"
    lines.append("PASS")
except Exception:
    lines.append(traceback.format_exc())

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
