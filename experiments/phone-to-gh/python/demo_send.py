"""For a screen recording: play the phone for the first steps, with pauses.

    .venv/Scripts/python.exe demo_send.py [photo] [--wait 5] [--pause 1.5]

After --wait seconds it sends the layer photo (message 1): Grasshopper draws
the stone outlines in Rhino. --pause seconds after the outlines came back it
answers Yes (message 3): Grasshopper sends the zone and draws it in Rhino.
Default photo: the real-scale test's round 3, wall s1 (white ground, 35 cm stones).
"""
import argparse
import json
import queue
import time
from pathlib import Path

import paho.mqtt.client as mqtt

from fake_phone import ANSWER, BROKER, OUTLINES, TOPIC, ZONE, photo_message

DEFAULT = Path(__file__).resolve().parents[1] / "realscale_test" / "round3" / "inputs" / "s1_layer.jpg"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("photo", nargs="?", type=Path, default=DEFAULT)
    ap.add_argument("--wait", type=float, default=5.0, help="seconds before the photo goes out")
    ap.add_argument("--pause", type=float, default=1.5, help="seconds between the outlines and the Yes")
    a = ap.parse_args()

    inbox = queue.Queue()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = lambda c, u, m: inbox.put((m.topic, json.loads(m.payload)))
    client.on_connect = lambda c, u, f, rc, p=None: c.subscribe([(OUTLINES, 1), (ZONE, 1)])
    client.connect(BROKER, 1883)
    client.loop_start()

    def wait_for(topic, ts, s=30):
        end = time.time() + s
        while time.time() < end:
            try:
                got, data = inbox.get(timeout=0.5)
            except queue.Empty:
                continue
            if got == topic and abs(data.get("photo_ts", 0) - ts) < 0.001:
                return data
        return None

    start = time.time()
    time.sleep(a.wait)
    msg, _ = photo_message(a.photo, 45.0)
    client.publish(TOPIC, json.dumps(msg), qos=1)
    print("%4.1f s  photo sent" % (time.time() - start), flush=True)
    outlines = wait_for(OUTLINES, msg["ts"])
    print("%4.1f s  outlines: %s" % (time.time() - start, len(outlines["stones"]) if outlines else "NONE"), flush=True)
    time.sleep(a.pause)
    client.publish(ANSWER, json.dumps({"photo_ts": msg["ts"], "ok": True, "ts": time.time()}), qos=1)
    zone = wait_for(ZONE, msg["ts"])
    print("%4.1f s  Yes -> zone: %s" % (time.time() - start, zone["length_cm"] if zone else "NONE"), flush=True)
    client.loop_stop()


if __name__ == "__main__":
    main()
