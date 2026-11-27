#! python 3
"""One step to get the demo running in a fresh Rhino: load Grasshopper, build
../demo/phone_to_gh.gh from the current scripts (build_gh_file.py) and open it.

    "C:\\Program Files\\Rhino 8\\System\\Rhino.exe" /nosplash /runscript="_-RunPythonScript <this file>"

or in Rhino: ScriptEditor > open this file > Run. Writes ../output/start_result.txt.
"""
import os
import traceback

import Rhino

HERE = os.path.dirname(os.path.realpath(__file__))
GH_PATH = os.path.normpath(os.path.join(HERE, "..", "demo", "phone_to_gh.gh"))
OUT = os.path.join(HERE, "..", "output", "start_result.txt")

lines = []
try:
    gh = Rhino.RhinoApp.GetPlugInObject("Grasshopper")
    gh.LoadEditor()                       # Grasshopper's assemblies, before build_gh_file imports them
    build = os.path.join(HERE, "build_gh_file.py")
    with open(build) as f:
        exec(compile(f.read(), build, "exec"), {"__file__": build, "__name__": "__main__"})
    with open(os.path.join(HERE, "..", "output", "gh_build_result.txt")) as f:
        lines.append(f.read())
    gh.ShowEditor()
    lines.append("opened: %s" % gh.OpenDocument(GH_PATH))
except Exception:
    lines.append(traceback.format_exc())

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
