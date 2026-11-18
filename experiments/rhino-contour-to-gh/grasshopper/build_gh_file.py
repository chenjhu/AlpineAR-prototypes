#! python 3
"""Build ../demo/receive_contours.gh: the Python 3 Script component from
receive_contours.py, wired to a json_path Panel ("stones.json", next to the
.gh), a refresh Button and an info Panel. Solves it once, writes what came
out to ../output/gh_build_result.txt, then opens it in Grasshopper.

Run inside Rhino 8 (ScriptEditor > Run, or rhinocode as in test_in_rhino.py).
Re-run it after changing receive_contours.py.
"""
import os
import traceback

import System
import Rhino
import Grasshopper
from Grasshopper.Kernel import GH_Document, GH_DocumentIO, GH_ParameterSide, GH_RuntimeMessageLevel
from Grasshopper.Kernel.Special import GH_ButtonObject, GH_Panel, GH_Scribble

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.normpath(os.path.join(HERE, "..", "demo"))
GH_PATH = os.path.join(DEMO, "receive_contours.gh")
OUT = os.path.join(HERE, "..", "output", "gh_build_result.txt")


def place(doc, obj, x, y, size=None):
    obj.CreateAttributes()
    obj.Attributes.Pivot = System.Drawing.PointF(x, y)
    if size:
        obj.Attributes.Bounds = System.Drawing.RectangleF(x, y, size[0], size[1])
    doc.AddObject(obj, False)
    return obj


def name_param(param, name):
    param.Name = name
    param.NickName = name
    param.VariableName = name


lines = []
try:
    Rhino.RhinoApp.GetPlugInObject("Grasshopper")  # make sure Grasshopper is loaded
    doc = GH_Document()
    doc.FilePath = GH_PATH  # so "stones.json" resolves next to the .gh while solving here

    note = GH_Scribble()
    note.Text = ("Photo -> Grasshopper\n"
                 "1. python/photo_to_json.py photo.jpg --ref-cm <length of biggest stone>\n"
                 "2. press refresh")
    place(doc, note, 40, 20)

    path_panel = place(doc, GH_Panel(), 40, 130, (150, 22))
    path_panel.UserText = "stones.json"
    path_panel.NickName = "json_path"

    button = place(doc, GH_ButtonObject(), 70, 190)
    button.NickName = "refresh"

    comp = Grasshopper.Instances.ComponentServer.FindObjectByName("Python 3 Script", True, True).CreateInstance()
    comp.NickName = "receive contours"
    with open(os.path.join(HERE, "receive_contours.py")) as f:
        comp.SetSource(f.read())
    name_param(comp.Params.Input[0], "json_path")
    name_param(comp.Params.Input[1], "refresh")
    name_param(comp.Params.Output[1], "info")  # Output[0] "out" = printed text
    for i, name in enumerate(("contours", "centroids"), start=2):
        p = comp.CreateParameter(GH_ParameterSide.Output, i)
        comp.Params.RegisterOutputParam(p, i)
        name_param(p, name)
    comp.VariableParameterMaintenance()
    comp.Params.OnParametersChanged()
    place(doc, comp, 300, 150)

    info_panel = place(doc, GH_Panel(), 540, 110, (460, 110))
    info_panel.NickName = "info"

    comp.Params.Input[0].AddSource(path_panel)
    comp.Params.Input[1].AddSource(button)
    info_panel.AddSource(comp.Params.Output[1])

    doc.Enabled = True
    doc.NewSolution(True)
    for level in (GH_RuntimeMessageLevel.Error, GH_RuntimeMessageLevel.Warning):
        for m in comp.RuntimeMessages(level):
            lines.append("%s: %s" % (level, m))
    out = {p.NickName: [str(g) for g in p.VolatileData.AllData(True)] for p in comp.Params.Output}
    lines.append("info:\n" + "\n".join(out.get("info", [])))
    lines.append("contours: %d, centroids: %d" % (len(out["contours"]), len(out["centroids"])))

    lines.append("saved %s: %s" % (GH_PATH, GH_DocumentIO(doc).SaveQuiet(GH_PATH)))
    doc.Dispose()

    # show it; drop an older copy first, otherwise Grasshopper asks in a
    # dialog whether to open the same file twice (and blocks Rhino)
    server = Grasshopper.Instances.DocumentServer
    for old in list(server):
        if old.FilePath and os.path.realpath(old.FilePath) == os.path.realpath(GH_PATH):
            server.RemoveDocument(old)
    Rhino.RhinoApp.GetPlugInObject("Grasshopper").OpenDocument(GH_PATH)
    lines.append("opened in Grasshopper")
except Exception:
    lines.append(traceback.format_exc())

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
