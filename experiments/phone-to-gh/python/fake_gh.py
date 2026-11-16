"""Pretend to be Grasshopper for flow steps 3-6 (works on Windows too).

Listens for photos (MESSAGES.md message 1), detects the stones with the
same Mode 1 detection Grasshopper uses, and replies with their outlines
(message 2). Prints every answer the phone sends (message 3); after a Yes
it sends the rule-of-thirds zone for that photo (message 4). So the Unity
side can test steps 4-7 without the Mac:

    pip install paho-mqtt opencv-python numpy
    python fake_gh.py --stones 2          # Ctrl+C to stop

--save also writes check_<time>.jpg: the photo with the outlines drawn
from message 2 itself, to compare with what the phone shows, and
zone_<time>.jpg with the zone of message 4 (white = max, blue = min).
Do not run it while the real Grasshopper sends outlines too (two replies).
"""
import argparse
import base64
import json
import time

import cv2
import numpy as np
import paho.mqtt.client as mqtt

# the same code Grasshopper runs (grasshopper/detect_photo.py -> replies.py)
from replies import detect, draw, outlines_message, zone_message

BROKER = "broker.hivemq.com"
PHOTO = "alpinear/proto1/photo"
OUTLINES = "alpinear/proto1/outlines"
ANSWER = "alpinear/proto1/answer"
ZONE = "alpinear/proto1/zone"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stones", type=int, default=2, help="how many stones are in the photo")
    ap.add_argument("--broker", default=BROKER)
    ap.add_argument("--save", action="store_true", help="write check_<time>.jpg per photo")
    a = ap.parse_args()
    photos = {}  # photo_ts -> (image, detected stones), for the zone after a Yes

    def on_message(client, userdata, m):
        stamp = time.strftime("%H:%M:%S")
        try:
            data = json.loads(m.payload)
            if m.topic == ANSWER:
                print("%s answer: ok=%s for photo_ts %s" % (stamp, data.get("ok"), data.get("photo_ts")))
                if data.get("ok") is True:
                    send_zone(client, data["photo_ts"], stamp)
                return
            jpg = np.frombuffer(base64.b64decode(data["photo"]), np.uint8)
            img = cv2.imdecode(jpg, cv2.IMREAD_COLOR)
            found = detect(img, a.stones)
            msg = outlines_message(found, img.shape[1::-1], data["ts"])
            photos[data["ts"]] = (img, found)
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

    def send_zone(client, photo_ts, stamp):
        key = next((t for t in photos if abs(t - photo_ts) < 0.001), None)
        if key is None:
            print("         no photo with that photo_ts here, no zone sent")
            return
        img, found = photos[key]
        msg = zone_message(found, img.shape[1::-1], key)
        client.publish(ZONE, json.dumps(msg), qos=1)
        print("%s zone sent: %s" % (stamp, msg["note"] or "max %d points, min %d points" % (
            len(msg["max"]), len(msg["min"]))))
        if a.save:
            name = "zone_%s.jpg" % time.strftime("%Y%m%d_%H%M%S")
            cv2.imwrite(name, draw(img, msg))
            print("         drawn -> %s" % name)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    # subscribe again after every reconnect (the broker forgets subscriptions)
    client.on_connect = lambda c, u, f, rc, p=None: c.subscribe([(PHOTO, 1), (ANSWER, 1)])
    client.connect(a.broker, 1883)
    print("fake Grasshopper on %s: photo -> outlines (stones=%d), Yes -> zone. Ctrl+C to stop"
          % (a.broker, a.stones))
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
