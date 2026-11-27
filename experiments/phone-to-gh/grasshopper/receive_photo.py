#! python 3
# venv: venv-compas-xr2.2
# r: compas==2.13.0, compas_model==0.9.3, compas_eve==2.3.0, compas_pb==1.0.0
"""Phone -> Grasshopper: wait for a photo on MQTT and save it next to the .gh.

Message format: ../MESSAGES.md, message 1 (topic alpinear/proto1/photo).
Same venv and packages as the course's MQTT Publisher, so nothing new to install.

Inputs:
  broker  str   "broker.hivemq.com"
  topic   str   "alpinear/proto1/photo"
  listen  bool  Toggle. True = subscribed. Off/on again = reconnect.
Outputs:
  photo_path  the newest photo, saved as inbox/photo_<time>.jpg next to the .gh
  ref_cm      the scale sent with it (real long side of the biggest stone)
  photo_ts    its ts, unchanged: the replies to the phone carry it back
  info        connected? / what arrived -> Panel

The MQTT callback runs on a background thread: it only writes the file and
asks Grasshopper to run this component again; everything else happens here.
"""
import base64
import json
import os
import time

import System
import Rhino
import scriptcontext as sc
from Grasshopper.Kernel import GH_Document

from compas_eve import Subscriber, Topic
from compas_eve.mqtt import MqttTransport

# kept across solves (and across re-opening the .gh while Rhino runs)
state = sc.sticky.setdefault("alpinear.receive_photo", {})


def stop():
    if state.get("subscriber"):
        try:
            state["subscriber"].unsubscribe()
        except Exception:
            pass
    if state.get("transport"):
        state["transport"].close()
    for k in ("subscriber", "transport", "key"):
        state.pop(k, None)


def run_again_later():
    """Background thread -> UI thread -> schedule a new solution of this component."""
    def on_ui():
        comp = state.get("component")
        doc = comp.OnPingDocument() if comp else None
        if doc is not None:
            doc.ScheduleSolution(1, GH_Document.GH_ScheduleDelegate(lambda d: comp.ExpireSolution(False)))
    Rhino.RhinoApp.InvokeOnUiThread(System.Action(on_ui))


def on_message(message):
    """MQTT thread. message = the JSON from the phone."""
    data = getattr(message, "data", message)
    try:
        ts = float(data.get("ts") or time.time())
        name = "photo_%s.jpg" % time.strftime("%Y%m%d_%H%M%S", time.localtime(ts))
        path = os.path.join(state["inbox"], name)
        jpg = base64.b64decode(data["photo"])
        if jpg[:2] != b"\xff\xd8":
            raise ValueError("'photo' is not a JPEG")
        with open(path, "wb") as f:
            f.write(jpg)
        if data.get("mode"):
            # The placement situation the person picked (message 1's `mode`); replies.py
            # reads it from here, so "detect" needs no new input.
            with open(os.path.splitext(path)[0] + ".msg.json", "w") as f:
                json.dump({"mode": str(data["mode"])}, f)
        state["last"] = {"path": path, "ref_cm": float(data["ref_cm"]), "ts": ts,
                         "kb": len(jpg) // 1024, "at": time.strftime("%H:%M:%S")}
        state.pop("error", None)
    except Exception as e:  # a wrong message must not kill the subscription
        state["error"] = "message ignored, %s: %s" % (type(e).__name__, e)
    run_again_later()


def start(host, topic_name):
    gh_file = ghenv.Component.OnPingDocument().FilePath  # noqa: F821
    if not gh_file:
        raise ValueError("Save the .gh file first: photos go to inbox/ next to it")
    state["inbox"] = os.path.join(os.path.dirname(gh_file), "inbox")
    os.makedirs(state["inbox"], exist_ok=True)
    state["component"] = ghenv.Component  # noqa: F821  (the callback re-runs this one)
    if state.get("key") == (host, topic_name):
        return  # already subscribed
    stop()
    transport = MqttTransport(host, port=1883)
    subscriber = Subscriber(Topic(topic_name), callback=on_message, transport=transport)
    subscriber.subscribe()  # sent as soon as the connection is up
    # paho reconnects by itself after a network drop (e.g. the Mac slept), but
    # the broker forgets the subscription and compas_eve subscribes only once:
    # then it is "connected" but deaf. So subscribe again on every (re)connect.
    transport.on("ready", lambda *a, **k: transport.client.subscribe(topic_name))
    state.update(transport=transport, subscriber=subscriber, key=(host, topic_name))


host = (broker or "broker.hivemq.com").strip()  # noqa: F821 (GH inputs)
topic_name = (topic or "alpinear/proto1/photo").strip()  # noqa: F821
lines = []
if listen:  # noqa: F821
    start(host, topic_name)
    connected = state["transport"].client.is_connected()
    lines.append("listening on %s '%s' (%s)" % (host, topic_name, "connected" if connected else "connecting..."))
else:
    stop()
    lines.append("not listening (switch listen on)")

last = state.get("last")
photo_path = last["path"] if last else None
ref_cm = last["ref_cm"] if last else None
photo_ts = last.get("ts") if last else None
if last:
    lines.append("last photo %s, %d kB, ref_cm %g, received %s" % (
        os.path.basename(last["path"]), last["kb"], last["ref_cm"], last["at"]))
else:
    lines.append("no photo yet")
if state.get("error"):
    lines.append(state["error"])
info = "\n".join(lines)
