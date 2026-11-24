"""Pretend to be Grasshopper for flow steps 3-6 (works on Windows too).

Listens for photos (MESSAGES.md message 1), detects the stones with the
same Mode 1 detection Grasshopper uses, and replies with their outlines
(message 2). Prints every answer the phone sends (message 3); after a Yes
it sends the zone (quarter rule) for that photo (message 4). A candidate
stone's photo (message 5) gets the fit check (message 6). So the Unity
side can test steps 4-10 without the Mac:

    pip install paho-mqtt opencv-python numpy
    python fake_gh.py --stones 2          # Ctrl+C to stop

--save also writes check_<time>.jpg: the photo with the outlines drawn
from message 2 itself, to compare with what the phone shows, and
zone_<time>.jpg with the zone of message 4 (white = max, blue = min),
and layer_<time>.jpg / candidate_<time>.jpg: each photo exactly as the
phone sent it, to run a failure again.
Do not run it while the real Grasshopper sends outlines too (two replies).
"""
import argparse
import base64
import json
import time
import traceback
from pathlib import Path

import cv2
import numpy as np
import paho.mqtt.client as mqtt

# the same code Grasshopper runs (grasshopper/detect_photo.py -> replies.py)
from replies import candidate_stones, detect, draw, fit_message, outlines_message, zone_message

BROKER = "broker.hivemq.com"
PHOTO = "alpinear/proto1/photo"
OUTLINES = "alpinear/proto1/outlines"
ANSWER = "alpinear/proto1/answer"
ZONE = "alpinear/proto1/zone"
CANDIDATE = "alpinear/proto1/candidate"
FIT = "alpinear/proto1/fit"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stones", type=int, default=2, help="how many stones are in the photo")
    ap.add_argument("--qr-id", type=int, default=10, help="the QR marker that gives the scale (0 = none)")
    ap.add_argument("--broker", default=BROKER)
    ap.add_argument("--save", action="store_true", help="write check_<time>.jpg per photo")
    a = ap.parse_args()
    photos = {}  # photo_ts -> (image, detected stones, QR marker), for the zone after a Yes

    def on_message(client, userdata, m):
        stamp = time.strftime("%H:%M:%S")
        try:
            data = json.loads(m.payload)
            if m.topic == ANSWER:
                print("%s answer: ok=%s for photo_ts %s" % (stamp, data.get("ok"), data.get("photo_ts")))
                if data.get("ok") is True:
                    send_zone(client, data["photo_ts"], stamp)
                return
            if m.topic == CANDIDATE:
                send_fit(client, data, stamp)
                return
            jpg = np.frombuffer(base64.b64decode(data["photo"]), np.uint8)
            keep(jpg, "layer")
            img = cv2.imdecode(jpg, cv2.IMREAD_COLOR)
            found, marker = detect(img, a.stones, a.qr_id)
            msg = outlines_message(found, img.shape[1::-1], data["ts"], marker)
            photos[data["ts"]] = (img, found, marker)
            client.publish(OUTLINES, json.dumps(msg), qos=1)
            print("%s photo %dx%d -> sent %d outlines (%s points), %s" % (
                stamp, img.shape[1], img.shape[0], len(msg["stones"]),
                "+".join(str(len(s["outline"])) for s in msg["stones"]),
                "QR %d found, cm" % marker.qr_id if marker else "no QR, pixels only"))
            if a.save:
                name = "check_%s.jpg" % time.strftime("%Y%m%d_%H%M%S")
                cv2.imwrite(name, draw(img, msg))
                print("         drawn -> %s" % name)
        except Exception as e:  # keep listening
            print("%s message on %s ignored: %s: %s" % (stamp, m.topic, type(e).__name__, e))
            traceback.print_exc()

    def send_zone(client, photo_ts, stamp):
        key = next((t for t in photos if abs(t - photo_ts) < 0.001), None)
        if key is None:
            print("         no photo with that photo_ts here, no zone sent")
            return
        img, found, marker = photos[key]
        msg = zone_message(found, img.shape[1::-1], key, marker)
        client.publish(ZONE, json.dumps(msg), qos=1)
        print("%s zone sent: %s" % (stamp, msg["note"] or "max %d points, min %d points%s" % (
            len(msg["max"]), len(msg["min"]),
            ", next stone %.1f-%.1f cm long" % tuple(msg["length_cm"]) if msg["length_cm"] else "")))
        if a.save:
            name = "zone_%s.jpg" % time.strftime("%Y%m%d_%H%M%S")
            cv2.imwrite(name, draw(img, msg))
            print("         drawn -> %s" % name)

    def keep(jpg, kind):
        """With --save: the photo exactly as the phone sent it, to run a failure again."""
        if a.save:
            Path("%s_%s.jpg" % (kind, time.strftime("%Y%m%d_%H%M%S"))).write_bytes(jpg.tobytes())

    def send_fit(client, data, stamp):
        jpg = np.frombuffer(base64.b64decode(data["photo"]), np.uint8)
        keep(jpg, "candidate")
        img = cv2.imdecode(jpg, cv2.IMREAD_COLOR)
        found, marker, note = candidate_stones(img, a.qr_id, data.get("tap"))
        key = next((t for t in photos if abs(t - data["layer_ts"]) < 0.001), None)
        zone = None
        if key is not None:
            layer_img, layer_found, layer_marker = photos[key]
            zone = zone_message(layer_found, layer_img.shape[1::-1], key, layer_marker)
        msg = fit_message(found, marker, img.shape[1::-1], data["ts"], data["layer_ts"], zone, note)
        client.publish(FIT, json.dumps(msg), qos=1)
        print("%s candidate -> %s%s%s" % (stamp, msg["result"],
              ", %.1f cm long (zone %.1f-%.1f)" % ((msg["length_cm"],) + tuple(msg["need_cm"]))
              if msg["length_cm"] is not None and msg["need_cm"] else "",
              ", " + msg["note"] if msg["note"] else ""))
        if a.save:
            name = "fit_%s.jpg" % time.strftime("%Y%m%d_%H%M%S")
            cv2.imwrite(name, draw(img, {"stones": [{"id": msg["result"], "outline": msg["outline"]}]} if msg["outline"] else {}))
            print("         drawn -> %s" % name)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    # subscribe again after every reconnect (the broker forgets subscriptions)
    client.on_connect = lambda c, u, f, rc, p=None: c.subscribe([(PHOTO, 1), (ANSWER, 1), (CANDIDATE, 1)])
    client.connect(a.broker, 1883)
    print("fake Grasshopper on %s: photo -> outlines (stones=%d), Yes -> zone, candidate -> fit. Ctrl+C to stop"
          % (a.broker, a.stones))
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
