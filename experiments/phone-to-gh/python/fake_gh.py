"""Pretend to be Grasshopper for flow steps 3-5 (works on Windows too).

Listens for photos (MESSAGES.md message 1), detects the stones with the
same Mode 1 detection Grasshopper uses, and replies with their outlines
(message 2). Prints every answer the phone sends (message 3). So the Unity
side can test steps 4-5 without the Mac:

    pip install paho-mqtt opencv-python numpy
    python fake_gh.py --stones 2          # Ctrl+C to stop

--save also writes check_<time>.jpg: the photo with the outlines drawn
from message 2 itself, to compare with what the phone shows.
Do not run it while the real Grasshopper sends outlines too (two replies).
"""
import argparse
import base64
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mode1-rule-of-thirds"))
from stone_detect import DetectParams, detect_stones  # noqa: E402

BROKER = "broker.hivemq.com"
PHOTO = "alpinear/proto1/photo"
OUTLINES = "alpinear/proto1/outlines"
ANSWER = "alpinear/proto1/answer"
SIMPLIFY_PX = 1.5  # same as rhino-contour-to-gh/python/photo_to_json.py


def outlines_message(img, photo_ts, stones):
    """MESSAGES.md message 2 for one photo (BGR image)."""
    found = detect_stones(img, DetectParams(stones=stones)).stones
    out = []
    for i, s in enumerate(found):
        c = cv2.approxPolyDP(s.contour, SIMPLIFY_PX, True).reshape(-1, 2)
        out.append({"id": i, "outline": [[int(x), int(y)] for x, y in c]})
    h, w = img.shape[:2]
    return {"photo_ts": photo_ts, "image_size": [w, h], "stones": out, "ts": time.time()}


def draw(img, msg):
    """The photo with the outlines of message 2 drawn on it."""
    img = img.copy()
    for s in msg["stones"]:
        pts = np.int32(s["outline"]).reshape(-1, 1, 2)
        cv2.polylines(img, [pts], True, (0, 0, 255), 3)
        x, y = pts.reshape(-1, 2).mean(axis=0)
        cv2.putText(img, str(s["id"]), (int(x), int(y)), 0, 1.2, (0, 0, 255), 3)
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stones", type=int, default=2, help="how many stones are in the photo")
    ap.add_argument("--broker", default=BROKER)
    ap.add_argument("--save", action="store_true", help="write check_<time>.jpg per photo")
    a = ap.parse_args()

    def on_message(client, userdata, m):
        stamp = time.strftime("%H:%M:%S")
        try:
            data = json.loads(m.payload)
            if m.topic == ANSWER:
                print("%s answer: ok=%s for photo_ts %s" % (stamp, data.get("ok"), data.get("photo_ts")))
                return
            jpg = np.frombuffer(base64.b64decode(data["photo"]), np.uint8)
            img = cv2.imdecode(jpg, cv2.IMREAD_COLOR)
            msg = outlines_message(img, data["ts"], a.stones)
            client.publish(OUTLINES, json.dumps(msg), qos=1)
            print("%s photo %dx%d -> sent %d outlines (%s points)" % (
                stamp, img.shape[1], img.shape[0], len(msg["stones"]),
                "+".join(str(len(s["outline"])) for s in msg["stones"])))
            if a.save:
                name = "check_%s.jpg" % time.strftime("%Y%m%d_%H%M%S")
                cv2.imwrite(name, draw(img, msg))
                print("         drawn -> %s" % name)
        except Exception as e:  # keep listening
            print("%s message on %s ignored: %s: %s" % (stamp, m.topic, type(e).__name__, e))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    # subscribe again after every reconnect (the broker forgets subscriptions)
    client.on_connect = lambda c, u, f, rc, p=None: c.subscribe([(PHOTO, 1), (ANSWER, 1)])
    client.connect(a.broker, 1883)
    print("fake Grasshopper on %s: photo -> outlines (stones=%d), printing answers. Ctrl+C to stop"
          % (a.broker, a.stones))
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
