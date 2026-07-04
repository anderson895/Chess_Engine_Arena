# Diagnostic client: impersonates the browser side of NiceGUI.
# Fetches "/", performs the socket.io handshake, and records every
# run_javascript message (this is how sounds reach the browser).
# Writes tools/probe_client.log.
import asyncio
import os
import re
import time
import uuid

import httpx
import socketio

BASE = "http://127.0.0.1:8001"
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "probe_client.log")
DURATION_S = int(os.environ.get("PROBE_DURATION_S", "45"))

log_f = open(LOG, "w", encoding="utf-8")


def log(msg):
    log_f.write(f"{time.time():.3f} {msg}\n")
    log_f.flush()


async def main():
    html = httpx.get(BASE + "/", timeout=30).text
    m = re.search(r'"client_id":\s*"([^"]+)"', html)
    if not m:
        m = re.search(r"client_id['\"]?\s*[:=]\s*['\"]([0-9a-fA-F-]+)", html)
    client_id = m.group(1)
    nm = re.search(r'"next_message_id":\s*(\d+)', html)
    next_message_id = int(nm.group(1)) if nm else 0
    log(f"client_id={client_id} next_message_id={next_message_id}")

    tab_id = str(uuid.uuid4())
    document_id = str(uuid.uuid4())

    sio = socketio.AsyncClient()
    counts = {}

    @sio.event
    async def connect():
        log("socket connected")
        ok = await sio.call("handshake", {
            "client_id": client_id,
            "tab_id": tab_id,
            "document_id": document_id,
            "next_message_id": next_message_id,
        })
        log(f"handshake ok={ok}")
        # Verify the browser→terminal beacon path used by arenaSoundLog
        await sio.emit("log", {"client_id": client_id, "level": "warning",
                               "message": "[arena-sound] probe beacon test"})

    @sio.on("*")
    async def catch_all(event, data=None):
        counts[event] = counts.get(event, 0) + 1
        if event == "run_javascript":
            log(f"run_javascript: {data.get('code')!r} _id={data.get('_id')}")
        elif event in ("notify", "open"):
            log(f"{event}: {data}")

    q = (f"client_id={client_id}&tab_id={tab_id}&document_id={document_id}"
         f"&next_message_id={next_message_id}")
    await sio.connect(
        BASE + "?" + q,
        socketio_path="/_nicegui_ws/socket.io",
        transports=["websocket"],
    )
    await asyncio.sleep(DURATION_S)
    log(f"event counts: {counts}")
    await sio.disconnect()


asyncio.run(main())
