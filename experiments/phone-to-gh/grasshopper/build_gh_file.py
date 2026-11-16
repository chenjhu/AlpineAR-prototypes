#! python 3
"""Build ../demo/phone_to_gh.gh and open it in Grasshopper:

  broker / topic / listen -> [receive photo] -> [detect] -> [receive contours] -> curves
                                  info Panel     info Panel  +  info Panel
                                                     json_path +-> [reply to phone] -> outlines / zone to the phone
                                                                   info Panel

receive contours is ../../rhino-contour-to-gh/grasshopper/receive_contours.py,
unchanged. Re-run after editing any of the scripts (or, with the .gh open,
use reload_scripts.py). Writes
../output/gh_build_result.txt.

Run inside Rhino 8 (ScriptEditor > Run), or from a terminal (macOS):
    ln -sfn "$PWD/.." /tmp/phone2gh            # run from grasshopper/
    export DOTNET_ROLL_FORWARD=Major
    "/Applications/Rhino 8.app/Contents/Resources/bin/rhinocode" script /tmp/phone2gh/grasshopper/build_gh_file.py
"""
import os
import traceback

import System
import Rhino
import Grasshopper
import scriptcontext as sc
from Grasshopper.Kernel import GH_Document, GH_DocumentIO, GH_ParameterSide
from Grasshopper.Kernel.Special import GH_BooleanToggle, GH_Panel, GH_Scribble

HERE = os.path.dirname(os.path.realpath(__file__))  # real path, not the /tmp link
DEMO = os.path.normpath(os.path.join(HERE, "..", "demo"))
GH_PATH = os.path.join(DEMO, "phone_to_gh.gh")
RECEIVE_CONTOURS = os.path.normpath(os.path.join(HERE, "..", "..", "rhino-contour-to-gh", "grasshopper", "receive_contours.py"))
OUT = os.path.join(HERE, "..", "output", "gh_build_result.txt")


def place(doc, obj, x, y, size=None):
    obj.CreateAttributes()
    obj.Attributes.Pivot = System.Drawing.PointF(x, y)
    if size:
        obj.Attributes.Bounds = System.Drawing.RectangleF(x, y, size[0], size[1])
    doc.AddObject(obj, False)
    return obj


def panel(doc, x, y, nickname, text=None, size=(170, 22)):
    p = place(doc, GH_Panel(), x, y, size)
    p.NickName = nickname
    if text is not None:
        p.UserText = text
    return p


def script(doc, source_path, nickname, inputs, outputs, x, y):
    """Python 3 Script component with the given input / output names."""
    comp = Grasshopper.Instances.ComponentServer.FindObjectByName("Python 3 Script", True, True).CreateInstance()
    comp.NickName = nickname
    with open(source_path) as f:
        comp.SetSource(f.read())
    for side, names, params in ((GH_ParameterSide.Input, inputs, comp.Params.Input),
                                (GH_ParameterSide.Output, ["out"] + outputs, comp.Params.Output)):
        while len(params) < len(names):
            i = len(params)
            p = comp.CreateParameter(side, i)
            (comp.Params.RegisterInputParam if side == GH_ParameterSide.Input else comp.Params.RegisterOutputParam)(p, i)
        for p, name in zip(params, names):
            p.Name = p.NickName = p.VariableName = name
    comp.VariableParameterMaintenance()
    comp.Params.OnParametersChanged()
    place(doc, comp, x, y)
    return comp


def by_name(params, name):
    return next(p for p in params if p.NickName == name)


lines = []
try:
    Rhino.RhinoApp.GetPlugInObject("Grasshopper")
    # drop MQTT connections still running the old script code (kept in sticky)
    for name in ("alpinear.receive_photo", "alpinear.reply_to_phone"):
        state = sc.sticky.get(name, {})
        if state.get("transport"):
            state["transport"].close()
        for k in ("subscriber", "transport", "key", "error"):
            state.pop(k, None)
    os.makedirs(DEMO, exist_ok=True)
    doc = GH_Document()
    doc.FilePath = GH_PATH

    note = GH_Scribble()
    note.Text = ("Phone <-> Grasshopper (MESSAGES.md, messages 1-4)\n"
                 "Test without a phone: python/fake_phone.py photo.jpg --ref-cm 45 --answer yes")
    place(doc, note, 40, 10)

    broker = panel(doc, 40, 90, "broker", "broker.hivemq.com")
    topic = panel(doc, 40, 130, "topic", "alpinear/proto1/photo")
    listen = place(doc, GH_BooleanToggle(), 40, 175)
    listen.NickName = "listen"
    listen.Value = True

    rec = script(doc, os.path.join(HERE, "receive_photo.py"), "receive photo",
                 ["broker", "topic", "listen"], ["photo_path", "ref_cm", "photo_ts", "info"], 290, 110)
    rec_info = panel(doc, 250, 230, "info", size=(330, 70))

    count = panel(doc, 440, 60, "stones", "2", size=(40, 22))
    det = script(doc, os.path.join(HERE, "detect_photo.py"), "detect",
                 ["photo_path", "ref_cm", "photo_ts", "stones"], ["json_path", "info"], 560, 100)
    det_info = panel(doc, 600, 230, "info", size=(330, 70))

    con = script(doc, RECEIVE_CONTOURS, "receive contours",
                 ["json_path", "refresh"], ["info", "contours", "centroids"], 860, 100)
    con_info = panel(doc, 950, 230, "info", size=(380, 70))

    rep = script(doc, os.path.join(HERE, "reply_to_phone.py"), "reply to phone",
                 ["broker", "json_path", "listen"], ["info"], 860, 340)
    rep_info = panel(doc, 950, 450, "info", size=(420, 110))

    for src, dst in ((broker, rec.Params.Input[0]), (topic, rec.Params.Input[1]), (listen, rec.Params.Input[2]),
                     (by_name(rec.Params.Output, "photo_path"), det.Params.Input[0]),
                     (by_name(rec.Params.Output, "ref_cm"), det.Params.Input[1]),
                     (by_name(rec.Params.Output, "photo_ts"), det.Params.Input[2]),
                     (count, det.Params.Input[3]),
                     (by_name(det.Params.Output, "json_path"), con.Params.Input[0]),
                     (broker, rep.Params.Input[0]),
                     (by_name(det.Params.Output, "json_path"), rep.Params.Input[1]),
                     (listen, rep.Params.Input[2])):
        dst.AddSource(src)
    rec_info.AddSource(by_name(rec.Params.Output, "info"))
    det_info.AddSource(by_name(det.Params.Output, "info"))
    con_info.AddSource(by_name(con.Params.Output, "info"))
    rep_info.AddSource(by_name(rep.Params.Output, "info"))

    doc.Enabled = True
    doc.NewSolution(True)
    for comp in (rec, det, con, rep):
        for m in comp.RuntimeMessages(Grasshopper.Kernel.GH_RuntimeMessageLevel.Error):
            lines.append("%s error: %s" % (comp.NickName, m))
    for p in (rec_info, det_info, con_info, rep_info):
        lines.append("--- " + "\n".join(str(g) for g in p.VolatileData.AllData(True)))

    lines.append("saved %s: %s" % (GH_PATH, GH_DocumentIO(doc).SaveQuiet(GH_PATH)))
    doc.Enabled = False
    doc.Dispose()
    # Not opened from here on purpose: opening a file while another one has
    # unsaved changes pops up Grasshopper's save dialog, which blocks Rhino.
    lines.append("now open it in Grasshopper: File > Open > demo/phone_to_gh.gh")
except Exception:
    lines.append(traceback.format_exc())

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
