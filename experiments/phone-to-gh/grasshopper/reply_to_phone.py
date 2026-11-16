#! python 3
# venv: venv-compas-xr2.2
# r: compas==2.13.0, compas_model==0.9.3, compas_eve==2.3.0, compas_pb==1.0.0
"""Grasshopper -> phone, flow steps 4-6: send the stone outlines, wait for
"Are these the stones?", send the zone after a Yes.

Message formats: ../MESSAGES.md, messages 2 (outlines), 3 (answer), 4 (zone).
The messages themselves are made by ../python/replies.py (run by "detect"),
the same code python/fake_gh.py uses; this component only sends them.

Inputs:
  broker     str   "broker.hivemq.com"
  json_path  str   from "detect": photo_<time>.json. Next to it lie
                   photo_<time>.outlines.json and photo_<time>.zone.json
  listen     bool  the same toggle as "receive photo"
Outputs:
  info       what was sent and answered -> Panel

The outlines go out once per detection. The answer arrives on the MQTT
thread, which sends the zone right away (the phone waits only 15 s) and then
asks Grasshopper to re-run this component, only to update `info`.
"""
import json
import os
import time

import System
import Rhino
import scriptcontext as sc
from Grasshopper.Kernel import GH_Document

from compas_eve.mqtt import MqttTransport

OUTLINES = "alpinear/proto1/outlines"
ANSWER = "alpinear/proto1/answer"
ZONE = "alpinear/proto1/zone"

# kept across solves (and across re-opening the .gh while Rhino runs)
state = sc.sticky.setdefault("alpinear.reply_to_phone", {})
log = state.setdefault("log", [])        # the last few events, for the Panel
zones = state.setdefault("zones", {})    # photo_ts -> its zone file


def note(text):
    log.append("%s %s" % (time.strftime("%H:%M:%S"), text))
    del log[:-6]


def stop():
    if state.get("transport"):
        state["transport"].close()
    for k in ("transport", "key"):
        state.pop(k, None)


def run_again_later():
    """Background thread -> UI thread -> schedule a new solution of this component."""
    def on_ui():
        comp = state.get("component")
        doc = comp.OnPingDocument() if comp else None
        if doc is not None:
            doc.ScheduleSolution(1, GH_Document.GH_ScheduleDelegate(lambda d: comp.ExpireSolution(False)))
    Rhino.RhinoApp.InvokeOnUiThread(System.Action(on_ui))


def send(topic_name, msg):
    """Plain JSON, QoS 1, with a fresh ts (the phone skips a repeated message)."""
    msg["ts"] = time.time()
    return state["transport"].client.publish(topic_name, json.dumps(msg), qos=1).rc == 0


def on_answer(client, userdata, m):
    """MQTT thread: message 3 from the phone."""
    try:
        data = json.loads(m.payload)
        photo_ts = float(data["photo_ts"])
        if data.get("ok") is not True:
            note("answer No (photo %.3f): waiting for a new photo" % photo_ts)
        else:
            path = next((p for t, p in zones.items() if abs(t - photo_ts) < 0.001), None)
            if path is None:
                note("answer Yes for a photo not detected here (%.3f): no zone sent" % photo_ts)
            else:
                with open(path) as f:
                    zone = json.load(f)
                sent = send(ZONE, zone)
                note("answer Yes -> zone %s%s" % ("sent" if sent else "NOT sent (not connected)",
                                                 ", " + zone["note"] if zone["note"] else ""))
    except Exception as e:  # a wrong message must not kill the subscription
        note("answer ignored, %s: %s" % (type(e).__name__, e))
    run_again_later()


def start(host):
    state["component"] = ghenv.Component  # noqa: F821  (the callback re-runs this one)
    if state.get("key") == host:
        return  # already connected
    stop()
    transport = MqttTransport(host, port=1883)
    transport.client.message_callback_add(ANSWER, on_answer)
    subscribe = lambda *a, **k: transport.client.subscribe(ANSWER, qos=1)  # noqa: E731
    # on every (re)connect: the broker forgets subscriptions after a drop
    transport.on("ready", subscribe)
    if transport.client.is_connected():
        subscribe()
    state.update(transport=transport, key=host)


def send_outlines(path):
    """Message 2 for this detection, once (again only if it is detected again)."""
    stem = os.path.splitext(path)[0]
    outlines_path = stem + ".outlines.json"
    if not os.path.exists(outlines_path):
        return "no outlines file next to %s" % os.path.basename(path)
    key = (outlines_path, os.path.getmtime(outlines_path))
    if state.get("sent") == key:
        return None
    with open(outlines_path) as f:
        msg = json.load(f)
    zones[msg["photo_ts"]] = stem + ".zone.json"
    for t in sorted(zones)[:-20]:  # keep the last 20 photos
        zones.pop(t)
    if send(OUTLINES, msg):
        state["sent"] = key
        note("outlines sent: %d stones of %s" % (len(msg["stones"]), os.path.basename(stem)))
    else:
        note("outlines NOT sent (not connected); re-run to try again")
    return None


host = (broker or "broker.hivemq.com").strip()  # noqa: F821 (GH inputs)
lines = []
if listen:  # noqa: F821
    start(host)
    connected = state["transport"].client.is_connected()
    lines.append("replying on %s, answers on '%s' (%s)" % (
        host, ANSWER, "connected" if connected else "connecting..."))
    if json_path:  # noqa: F821
        problem = send_outlines(json_path)  # noqa: F821
        if problem:
            lines.append(problem)
else:
    stop()
    lines.append("not replying (switch listen on)")
info = "\n".join(lines + log)
