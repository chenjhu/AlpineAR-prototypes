#! python 3
"""Photo -> stones.json, by running the existing detection outside Grasshopper.

Grasshopper's Python has no OpenCV, so this calls the tested script
../../rhino-contour-to-gh/python/photo_to_json.py with the Mode 1 venv
(../../mode1-rule-of-thirds/.venv). Nothing is re-implemented here.

Inputs:
  photo_path  str    from "receive photo"
  ref_cm      float  from "receive photo"
  stones      int    how many stones are in the photo (Panel, e.g. 2)
Outputs:
  json_path   photo_<time>.json next to the photo -> "receive contours"
  info        what the detection printed -> Panel
"""
import os
import subprocess


def experiments_dir():
    """The .gh lives in experiments/phone-to-gh/demo/."""
    gh_file = ghenv.Component.OnPingDocument().FilePath  # noqa: F821
    if not gh_file:
        raise ValueError("Save the .gh file first")
    return os.path.normpath(os.path.join(os.path.dirname(gh_file), "..", ".."))


def detect(photo, ref, count):
    root = experiments_dir()
    python = os.path.join(root, "mode1-rule-of-thirds", ".venv", "bin", "python")
    script = os.path.join(root, "rhino-contour-to-gh", "python", "photo_to_json.py")
    for p in (python, script):
        if not os.path.exists(p):
            raise ValueError("missing %s" % p)
    out = os.path.splitext(photo)[0] + ".json"
    run = subprocess.run([python, script, photo, "--ref-cm", str(ref), "--stones", str(count), "--out", out],
                         capture_output=True, text=True, timeout=120)
    if run.returncode != 0:
        raise ValueError("detection failed:\n" + (run.stderr or run.stdout)[-800:])
    return out, run.stdout.strip()


json_path, info = None, "waiting for a photo"
if photo_path:  # noqa: F821 (GH inputs)
    json_path, info = detect(photo_path, ref_cm, int(stones or 2))  # noqa: F821
