#! python 3
"""Put the current receive_photo.py / detect_photo.py / receive_contours.py /
reply_to_phone.py / zone_curves.py into the phone_to_gh.gh that is OPEN in Grasshopper,
restart the MQTT connections, and save the file. Use this instead of build_gh_file.py while the
.gh is open: re-opening a file can pop up dialogs that block Rhino.

Run inside Rhino 8 (ScriptEditor > Run, or rhinocode as in build_gh_file.py).
Writes ../output/reload_result.txt.
"""
import os
import traceback

import Grasshopper
import scriptcontext as sc
from Grasshopper.Kernel import GH_DocumentIO

HERE = os.path.dirname(os.path.realpath(__file__))
GH_PATH = os.path.normpath(os.path.join(HERE, "..", "demo", "phone_to_gh.gh"))
SOURCES = {
    "receive photo": os.path.join(HERE, "receive_photo.py"),
    "detect": os.path.join(HERE, "detect_photo.py"),
    "reply to phone": os.path.join(HERE, "reply_to_phone.py"),
    "zone curves": os.path.join(HERE, "zone_curves.py"),
    "receive contours": os.path.normpath(os.path.join(HERE, "..", "..", "rhino-contour-to-gh", "grasshopper", "receive_contours.py")),
}
OUT = os.path.join(HERE, "..", "output", "reload_result.txt")

lines = []
try:
    canvas = Grasshopper.Instances.ActiveCanvas
    doc = canvas.Document if canvas else None
    if doc is None or os.path.realpath(doc.FilePath or "") != os.path.realpath(GH_PATH):
        raise ValueError("open demo/phone_to_gh.gh in Grasshopper first")

    # drop the old MQTT connections, so the new code subscribes from scratch
    for name in ("alpinear.receive_photo", "alpinear.reply_to_phone"):
        state = sc.sticky.get(name, {})
        if state.get("transport"):
            state["transport"].close()
        for k in ("subscriber", "transport", "key", "error"):
            state.pop(k, None)
    lines.append("old MQTT connections closed")

    for obj in doc.Objects:
        path = SOURCES.get(getattr(obj, "NickName", None))
        if path and hasattr(obj, "SetSource"):
            with open(path) as f:
                obj.SetSource(f.read())
            obj.ExpireSolution(False)
            lines.append("reloaded %s" % obj.NickName)
    doc.NewSolution(False)
    lines.append("saved: %s" % GH_DocumentIO(doc).SaveQuiet(GH_PATH))
except Exception:
    lines.append(traceback.format_exc())

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
