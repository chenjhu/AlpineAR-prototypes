#! python 3
"""Check the open ../demo/phone_to_gh.gh after a photo was sent.

1. open phone_to_gh.gh in Grasshopper (or run build_gh_file.py), listen = True
2. python/fake_phone.py ../../photos/01_L0_AB.jpeg --ref-cm 45
3. run this (ScriptEditor > Run, or rhinocode as in build_gh_file.py)

Reads the three info Panels and the curves from the open document and
writes ../output/rhino_result.txt (PASS / what failed).
"""
import os
import traceback

import Grasshopper

HERE = os.path.dirname(os.path.realpath(__file__))
GH_PATH = os.path.normpath(os.path.join(HERE, "..", "demo", "phone_to_gh.gh"))
OUT = os.path.join(HERE, "..", "output", "rhino_result.txt")


def output(comp, name):
    p = next(p for p in comp.Params.Output if p.NickName == name)
    return [g.Value if hasattr(g, "Value") else g for g in p.VolatileData.AllData(True)]


lines = []
try:
    canvas = Grasshopper.Instances.ActiveCanvas
    candidates = list(Grasshopper.Instances.DocumentServer) + ([canvas.Document] if canvas and canvas.Document else [])
    docs = [d for d in candidates  # (on macOS the open file is not always in DocumentServer)
            if d.FilePath and os.path.realpath(d.FilePath) == os.path.realpath(GH_PATH)]
    assert docs, "phone_to_gh.gh is not open in Grasshopper"
    comps = {o.NickName: o for o in docs[0].Objects if hasattr(o, "Params")}
    rec, det, con = comps["receive photo"], comps["detect"], comps["receive contours"]
    for c in (rec, det, con):
        lines.append("--- %s\n%s" % (c.NickName, "\n".join(str(t) for t in output(c, "info"))))
    photo = output(rec, "photo_path")
    curves = output(con, "contours")
    assert photo and os.path.exists(str(photo[0])), "no photo received"
    assert curves and all(c.IsClosed for c in curves), "no closed curves"
    assert "DIFFERS" not in str(output(con, "info")), "areas in Grasshopper and Python must agree"
    lines.append("PASS: photo %s -> %d closed curves" % (os.path.basename(str(photo[0])), len(curves)))
except Exception:
    lines.append(traceback.format_exc())

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
