#! python 3
"""Photo -> stones, by running the existing detection outside Grasshopper.

Grasshopper's Python has no OpenCV, so this runs ../python/replies.py with
the Mode 1 venv (../../mode1-rule-of-thirds/.venv). It detects once and
writes three files next to the photo (nothing is re-implemented here):
  photo_<time>.json           stones in cm -> "receive contours" (curves)
  photo_<time>.outlines.json  message 2    -> "reply to phone"
  photo_<time>.zone.json      message 4    -> "reply to phone", after a Yes

Inputs:
  photo_path  str    from "receive photo"
  ref_cm      float  from "receive photo"
  photo_ts    float  from "receive photo" (goes into messages 2 and 4)
  stones      int    how many stones are in the photo (Panel, e.g. 2)
  qr_id       int    the QR marker lying in the photo that gives the scale
                     (Panel: 10 = Tracker_10; 0 = none, then ref_cm)
Outputs:
  json_path   photo_<time>.json -> "receive contours" and "reply to phone"
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


def detect(photo, ref, ts, count, qr):
    root = experiments_dir()
    python = os.path.join(root, "mode1-rule-of-thirds", ".venv", "bin", "python")
    script = os.path.join(root, "phone-to-gh", "python", "replies.py")
    for p in (python, script):
        if not os.path.exists(p):
            raise ValueError("missing %s" % p)
    out = os.path.splitext(photo)[0] + ".json"
    run = subprocess.run([python, script, photo, "--ref-cm", str(ref), "--ts", repr(float(ts)), "--stones", str(count), "--qr-id", str(qr)],
                         capture_output=True, text=True, timeout=120)
    if run.returncode != 0:
        raise ValueError("detection failed:\n" + (run.stderr or run.stdout)[-800:])
    return out, run.stdout.strip()


json_path, info = None, "waiting for a photo"
if photo_path:  # noqa: F821 (GH inputs)
    ts = photo_ts if photo_ts is not None else os.path.getmtime(photo_path)  # noqa: F821
    json_path, info = detect(photo_path, ref_cm, ts, int(stones or 2), int(qr_id if qr_id is not None else 10))  # noqa: F821
