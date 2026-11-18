"""Pretend to be the phone: send one photo to Grasshopper over MQTT.

Sends exactly what the Unity app sends (MESSAGES.md, message 1), with plain
paho-mqtt and plain JSON, so Grasshopper can be tested without the phone.

    .venv/bin/python fake_phone.py ../../photos/01_L0_AB.jpeg --ref-cm 45

With --answer it also does what the phone does in flow steps 4-6: wait for
the outlines (message 2), answer "Are these the stones?" (message 3) and,
after a yes, wait for the zone (message 4). --save then writes
reply_<time>.jpg: the photo with the outlines and the zone that came back.

    .venv/bin/python fake_phone.py ../../photos/01_L0_AB.jpeg --ref-cm 45 --answer yes --save

With --candidate (after --answer yes) it then sends a candidate stone's
photo (message 5) for that zone and waits for the fit check (message 6),
flow steps 8-10:

    .venv/bin/python fake_phone.py layer.jpg --ref-cm 45 --answer yes --candidate stone.jpg
"""
import argparse
import base64
import json
import queue
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
TOPIC = "alpinear/proto1/photo"
OUTLINES = "alpinear/proto1/outlines"
ANSWER = "alpinear/proto1/answer"
ZONE = "alpinear/proto1/zone"
CANDIDATE = "alpinear/proto1/candidate"
FIT = "alpinear/proto1/fit"
WAIT_S = 15  # like the phone
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
    ap.add_argument("--answer", choices=["yes", "no"],
                    help="then wait for the outlines and answer like the phone")
    ap.add_argument("--candidate", type=Path,
                    help="with --answer yes: then send this candidate stone's photo and wait for the fit check")
    ap.add_argument("--save", action="store_true",
                    help="with --answer: write reply_<time>.jpg with what came back")
    a = ap.parse_args()

    msg, size = photo_message(a.photo, a.ref_cm)
    payload = json.dumps(msg)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    inbox = queue.Queue()
    if a.answer:
        client.on_message = lambda c, u, m: inbox.put((m.topic, json.loads(m.payload)))
        client.on_subscribe = lambda c, u, mid, rc, p=None: inbox.put(("subscribed", None))
        client.on_connect = lambda c, u, f, rc, p=None: c.subscribe([(OUTLINES, 1), (ZONE, 1), (FIT, 1)])
    client.connect(a.broker, 1883)
    client.loop_start()
    if a.answer:
        inbox.get(timeout=20)  # subscribed before sending, so no reply is missed
    sent_at = time.time()
    info = client.publish(a.topic, payload, qos=1)
    info.wait_for_publish(timeout=20)
    if not info.is_published():
        sys.exit("not sent (no answer from %s)" % a.broker)
    print("sent %s (%dx%d px, %d kB) to %s on '%s'" % (
        a.photo.name, size[0], size[1], len(payload) // 1024, a.broker, a.topic))

    if a.answer:
        outlines = wait_for(inbox, OUTLINES, msg["ts"], sent_at)
        print("outlines after %.1f s: %d stones (%s points)" % (
            time.time() - sent_at, len(outlines["stones"]),
            "+".join(str(len(s["outline"])) for s in outlines["stones"])))
        ok = a.answer == "yes"
        client.publish(ANSWER, json.dumps({"photo_ts": msg["ts"], "ok": ok, "ts": time.time()}),
                       qos=1).wait_for_publish(timeout=20)
        print("answered ok=%s" % ok)
        zone = {}
        if ok:
            answered_at = time.time()
            zone = wait_for(inbox, ZONE, msg["ts"], answered_at)
            print("zone after %.1f s: %s" % (time.time() - answered_at, zone["note"] or "max %s, min %s" % (
                zone["max"], zone["min"])))
        if ok and a.candidate:
            cand, _ = photo_message(a.candidate, None)
            cand.pop("ref_cm")
            cand["layer_ts"] = msg["ts"]
            cand_at = time.time()
            client.publish(CANDIDATE, json.dumps(cand), qos=1).wait_for_publish(timeout=20)
            print("sent candidate %s" % a.candidate.name)
            fit = wait_for(inbox, FIT, cand["ts"], cand_at)
            print("fit after %.1f s: %s%s%s" % (
                time.time() - cand_at, fit["result"],
                ", %.1f x %.1f cm" % (fit["length_cm"], fit["width_cm"]) if fit["length_cm"] is not None else "",
                " (zone %.1f-%.1f cm)" % tuple(fit["need_cm"]) if fit["need_cm"] else "")
                + (", " + fit["note"] if fit["note"] else ""))
        if a.save:
            from replies import draw  # the same drawing as fake_gh.py
            img = cv2.imdecode(np.frombuffer(base64.b64decode(msg["photo"]), np.uint8), cv2.IMREAD_COLOR)
            name = "reply_%s.jpg" % time.strftime("%Y%m%d_%H%M%S")
            cv2.imwrite(name, draw(draw(img, outlines), zone))
            print("drawn -> %s" % name)
    client.loop_stop()
    client.disconnect()


def wait_for(inbox, topic, photo_ts, since):
    """The next message on `topic` for this photo; like the phone, give up after WAIT_S."""
    while True:
        left = WAIT_S - (time.time() - since)
        try:
            got_topic, data = inbox.get(timeout=max(left, 0.01))
        except queue.Empty:
            sys.exit("no %s within %d s (is Grasshopper listening?)" % (topic.rsplit("/", 1)[1], WAIT_S))
        if got_topic == topic and abs(data.get("photo_ts", 0) - photo_ts) < 0.001:
            return data


if __name__ == "__main__":
    main()
