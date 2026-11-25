"""Step 2 of the real-scale test: run the photos through the real system, blind.

Reads only inputs/ (the photos and where a person would tap), plays the
phone over MQTT against the Grasshopper that is listening (demo/phone_to_gh.gh,
which runs python/replies.py) and writes every reply to outputs/. It never
opens sealed_truth/.

The system's files are hashed before and after the run (outputs/system.sha256)
to show nothing of it was changed for this test.

    python step2_run_blind.py --round round2
"""
import argparse
import hashlib
import json
import queue
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "python"))
from fake_phone import (ANSWER, BROKER, CANDIDATE, FIT, OUTLINES, PLACED, PLACEMENT, TOPIC,  # noqa: E402
                        ZONE, photo_message)

WAIT_S = 30  # the phone gives up after 15 s; here the time is recorded instead
EXP = HERE.parents[1]
SYSTEM = [EXP / "phone-to-gh" / "python" / f for f in ("replies.py", "qr_marker.py", "placement.py", "fake_phone.py")] + \
         [EXP / "phone-to-gh" / "grasshopper" / f for f in ("detect_photo.py", "reply_to_phone.py", "zone_curves.py")] + \
         [EXP / "phone-to-gh" / "demo" / "phone_to_gh.gh"] + \
         [EXP / "mode1-rule-of-thirds" / f for f in ("rule_of_thirds.py", "stone_detect.py")] + \
         [EXP / "rhino-contour-to-gh" / "python" / "photo_to_json.py"]


def hashes():
    return {str(p.relative_to(EXP)): hashlib.sha256(p.read_bytes()).hexdigest() for p in SYSTEM}


def wait_for(inbox, topic, ts):
    since = time.time()
    while True:
        try:
            got, data = inbox.get(timeout=max(WAIT_S - (time.time() - since), 0.01))
        except queue.Empty:
            return None, WAIT_S
        if got == topic and abs(data.get("photo_ts", 0) - ts) < 0.001:
            return data, time.time() - since


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--round", default="round2")
    rnd = HERE / ap.parse_args().round
    inputs, out = rnd / "inputs", rnd / "outputs"
    out.mkdir(exist_ok=True)
    before = hashes()
    layers = json.loads((inputs / "layers.json").read_text())
    taps = json.loads((inputs / "taps.json").read_text())

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    inbox = queue.Queue()
    client.on_message = lambda c, u, m: inbox.put((m.topic, json.loads(m.payload)))
    client.on_subscribe = lambda c, u, mid, rc, p=None: inbox.put(("subscribed", None))
    client.on_connect = lambda c, u, f, rc, p=None: c.subscribe([(OUTLINES, 1), (ZONE, 1), (FIT, 1), (PLACEMENT, 1)])
    client.connect(BROKER, 1883)
    client.loop_start()
    inbox.get(timeout=20)

    log = {}
    for scene, files in layers.items():
        rec = log[scene] = {"layer": files["layer"]}
        msg, size = photo_message(inputs / files["layer"], 45.0)
        client.publish(TOPIC, json.dumps(msg), qos=1).wait_for_publish(timeout=20)
        outlines, rec["outlines_s"] = wait_for(inbox, OUTLINES, msg["ts"])
        rec["outlines"] = outlines
        print("%s: outlines %s after %.1f s" % (scene, len(outlines["stones"]) if outlines else "NONE", rec["outlines_s"]))
        if not outlines:
            continue
        client.publish(ANSWER, json.dumps({"photo_ts": msg["ts"], "ok": True, "ts": time.time()}),
                       qos=1).wait_for_publish(timeout=20)
        zone, rec["zone_s"] = wait_for(inbox, ZONE, msg["ts"])
        rec["zone"] = zone
        print("   zone: L %s D %s %s" % (zone and zone["length_cm"], zone and zone["depth_range_cm"],
                                        zone and zone["note"]))
        rec["candidates"] = []
        for name in files["candidates"]:
            cand, _ = photo_message(inputs / name, None)
            cand.pop("ref_cm")
            cand["layer_ts"] = msg["ts"]
            cand["tap"] = [float(v) for v in taps[name]]
            client.publish(CANDIDATE, json.dumps(cand), qos=1).wait_for_publish(timeout=20)
            fit, secs = wait_for(inbox, FIT, cand["ts"])
            rec["candidates"].append({"photo": name, "tap": cand["tap"], "fit": fit, "fit_s": secs})
            print("   %s: %s %s x %s cm %s" % (name, fit and fit["result"], fit and fit["length_cm"],
                                             fit and fit["width_cm"], fit and fit["note"]))
        # After placing (messages 7-8): the wall photographed again, the person
        # taps the new stone.
        rec["placed"] = []
        if files.get("placed"):
            # The person lays the stone they checked last and that fitted: in this world
            # candidate 1. Check it once more, so it is the last one that fitted (Grasshopper
            # takes that stone's outline and texture for the placement check).
            name = files["candidates"][0]
            cand, _ = photo_message(inputs / name, None)
            cand.pop("ref_cm")
            cand["layer_ts"] = msg["ts"]
            cand["tap"] = [float(v) for v in taps[name]]
            client.publish(CANDIDATE, json.dumps(cand), qos=1).wait_for_publish(timeout=20)
            fit, _ = wait_for(inbox, FIT, cand["ts"])
            rec["laid"] = {"photo": name, "fit": fit and fit["result"]}
            print("   laid %s (checked again: %s)" % (name, fit and fit["result"]))
        for name in files.get("placed", []):
            placed, _ = photo_message(inputs / name, None)
            placed.pop("ref_cm")
            placed["layer_ts"] = msg["ts"]
            placed["tap"] = [float(v) for v in taps[name]]
            client.publish(PLACED, json.dumps(placed), qos=1).wait_for_publish(timeout=20)
            reply, secs = wait_for(inbox, PLACEMENT, placed["ts"])
            rec["placed"].append({"photo": name, "tap": placed["tap"], "placement": reply, "placement_s": secs})
            print("   %s: %s %s" % (name, reply and reply["result"], reply and reply["note"]))
    client.loop_stop()
    client.disconnect()

    after = hashes()
    (out / "replies.json").write_text(json.dumps(log, indent=1))
    (out / "system.sha256").write_text("".join("%s  %s%s\n" % (h, f, "" if after[f] == h else "  CHANGED DURING RUN")
                                               for f, h in before.items()))
    print("replies -> outputs/replies.json; system unchanged: %s" % (before == after))


if __name__ == "__main__":
    main()
