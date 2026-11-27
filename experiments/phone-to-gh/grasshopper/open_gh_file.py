#! python 3
"""Open ../demo/phone_to_gh.gh in Grasshopper, replacing the copy that is open
now (after build_gh_file.py wrote a new one). The open copy is closed WITHOUT
saving: build_gh_file.py has just written the file. Run inside Rhino 8
(ScriptEditor > Run, or rhinocode). Writes ../output/open_result.txt.
"""
import os
import traceback

import Grasshopper
import Rhino
from Grasshopper.Kernel import GH_DocumentIO

HERE = os.path.dirname(os.path.realpath(__file__))
GH_PATH = os.path.normpath(os.path.join(HERE, "..", "demo", "phone_to_gh.gh"))
OUT = os.path.join(HERE, "..", "output", "open_result.txt")

lines = []
try:
    Rhino.RhinoApp.RunScript("_Grasshopper", False)    # the editor must exist
    server = Grasshopper.Instances.DocumentServer
    for doc in list(server):
        if os.path.realpath(doc.FilePath or "") == os.path.realpath(GH_PATH):
            doc.Enabled = False
            server.RemoveDocument(doc)
            lines.append("closed the open copy")
    io = GH_DocumentIO()
    if not io.Open(GH_PATH):
        raise ValueError("could not open " + GH_PATH)
    doc = io.Document
    server.AddDocument(doc)
    canvas = Grasshopper.Instances.ActiveCanvas
    if canvas is not None:
        canvas.Document = doc
    doc.Enabled = True
    doc.NewSolution(True)
    lines.append("opened %s, %d objects" % (GH_PATH, doc.ObjectCount))
    for obj in doc.Objects:
        if hasattr(obj, "RuntimeMessages"):
            for m in obj.RuntimeMessages(Grasshopper.Kernel.GH_RuntimeMessageLevel.Error):
                lines.append("%s error: %s" % (obj.NickName, m))
except Exception:
    lines.append(traceback.format_exc())

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
