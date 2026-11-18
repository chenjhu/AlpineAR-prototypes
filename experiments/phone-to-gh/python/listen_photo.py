"""Check what the phone sends, without Grasshopper (works on Windows too).

Listens on the photo topic (MESSAGES.md, message 1), checks every message
against the format and saves the photo, so the Unity side can be tested on
its own:

    pip install paho-mqtt
    python listen_photo.py            # Ctrl+C to stop

Each photo is saved as received_<time>.jpg in the current folder; open it
and check that it is the top view of the stones (no buttons drawn on it).
"""
import argparse
import base64
import json
import time

import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
TOPIC = "alpinear/proto1/photo"


def check(payload):
    """Problems with one message, as a list of strings (empty = OK)."""
    try:
        msg = json.loads(payload)
    except ValueError as e:
        return ["not JSON: %s" % e], None
    problems = []
    for field, kind in (("photo", str), ("ref_cm", (int, float)), ("ts", (int, float))):
        if field not in msg:
            problems.append("missing field '%s'" % field)
        elif not isinstance(msg[field], kind):
            problems.append("'%s' has the wrong type (%s)" % (field, type(msg[field]).__name__))
    if "dtype" in msg:
        problems.append("do not use a field called 'dtype' (COMPAS reads it)")
    jpg = None
    if isinstance(msg.get("photo"), str):
        try:
            jpg = base64.b64decode(msg["photo"], validate=True)
            if jpg[:2] != b"\xff\xd8":
                problems.append("'photo' is base64 but not a JPEG")
        except ValueError:
            problems.append("'photo' is not valid base64")
    return problems, jpg


def on_message(client, userdata, m):
    problems, jpg = check(m.payload)
    stamp = time.strftime("%H:%M:%S")
    if jpg is not None and not problems:
        name = "received_%s.jpg" % time.strftime("%Y%m%d_%H%M%S")
        with open(name, "wb") as f:
            f.write(jpg)
        print("%s OK: %d kB photo -> %s" % (stamp, len(jpg) // 1024, name))
    else:
        print("%s WRONG (%d bytes): %s" % (stamp, len(m.payload), "; ".join(problems)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--broker", default=BROKER)
    ap.add_argument("--topic", default=TOPIC)
    a = ap.parse_args()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    client.connect(a.broker, 1883)
    client.subscribe(a.topic, qos=1)
    print("listening on %s '%s' (Ctrl+C to stop)" % (a.broker, a.topic))
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
