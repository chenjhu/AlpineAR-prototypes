"""Pretend to be the phone: send one photo to Grasshopper over MQTT.

Sends exactly what the Unity app will send later (MESSAGES.md, message 1),
with plain paho-mqtt and plain JSON, so Grasshopper is tested against the
real format before Unity exists.

    .venv/bin/python fake_phone.py ../../photos/01_L0_AB.jpeg --ref-cm 45
"""
import argparse
import base64
import json
import sys
import time
from pathlib import Path

import cv2
import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
TOPIC = "alpinear/proto1/photo"
LONG_SIDE = 1280  # px, like a phone would send (detection works at 640 px)


def photo_message(path, ref_cm, long_side=LONG_SIDE):
    img = cv2.imread(str(path))
    if img is None:
        raise SystemExit("cannot read %s" % path)
    h, w = img.shape[:2]
    k = min(1.0, long_side / max(w, h))
    if k < 1:
        img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return {"photo": base64.b64encode(jpg.tobytes()).decode("ascii"),
            "ref_cm": ref_cm,
            "ts": time.time()}, img.shape[1::-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("photo", type=Path)
    ap.add_argument("--ref-cm", type=float, required=True,
                    help="real long side of the biggest stone, cm")
    ap.add_argument("--broker", default=BROKER)
    ap.add_argument("--topic", default=TOPIC)
    a = ap.parse_args()

    msg, size = photo_message(a.photo, a.ref_cm)
    payload = json.dumps(msg)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(a.broker, 1883)
    client.loop_start()
    info = client.publish(a.topic, payload, qos=1)
    info.wait_for_publish(timeout=20)
    client.loop_stop()
    client.disconnect()
    if not info.is_published():
        sys.exit("not sent (no answer from %s)" % a.broker)
    print("sent %s (%dx%d px, %d kB) to %s on '%s'" % (
        a.photo.name, size[0], size[1], len(payload) // 1024, a.broker, a.topic))


if __name__ == "__main__":
    main()
