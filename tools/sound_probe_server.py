# Diagnostic server: runs the real app on port 8001 (no window) and
# auto-starts an engine-vs-engine game once a client connects.
# Every session "sound" emit is logged to tools/probe_server.log.
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nicegui import app, ui  # noqa: E402

from core.utils import get_resource_path  # noqa: E402
import webui.main_page as mp  # noqa: E402

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "probe_server.log")
ENGINE = os.path.join(os.getcwd(), "engines", "gfruit.exe")

s = mp.session
s.play_mode = s.MODE_EVE
s.e1_path = ENGINE
s.e2_path = ENGINE
s.e1_name = "gfruit (Black)"
s.e2_name = "gfruit (White)"
s.time_control = "bullet"
s.delay_s = 0.3

log_f = open(LOG, "w", encoding="utf-8")

_orig_emit = s._emit


def emit_spy(name, *args):
    if name in ("sound", "game_over"):
        log_f.write(f"{time.time():.3f} emit {name} {args}\n")
        log_f.flush()
    _orig_emit(name, *args)


s._emit = emit_spy

_started = False


@app.on_connect
async def _auto_start(client):
    global _started
    if _started:
        return
    _started = True
    log_f.write(f"{time.time():.3f} client connected, starting game soon\n")
    log_f.flush()
    await asyncio.sleep(5)     # let the boot asset loading settle
    await s.start_game()
    log_f.write(f"{time.time():.3f} start_game returned "
                f"(running={s.game_running})\n")
    log_f.flush()


app.add_static_files("/assets", get_resource_path("assets"))

ui.run(title="probe", dark=True, native=False, reload=False,
       show=False, port=8001)
