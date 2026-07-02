# ═══════════════════════════════════════════════════════════
#  main.py — Chess Engine Arena entry point (NiceGUI)
#
#  Run:  python main.py             → native desktop window
#        python main.py --browser   → open in the web browser
# ═══════════════════════════════════════════════════════════

import os
import sys

from nicegui import app, ui

from core.utils import get_resource_path
import webui.main_page  # noqa: F401 — registers the "/" page


def main():
    native = "--browser" not in sys.argv

    # Allow "Export PGN" downloads inside the native (pywebview) window
    app.native.settings["ALLOW_DOWNLOADS"] = True

    # Serve piece sprites and UI icons
    app.add_static_files("/assets", get_resource_path("assets"))

    favicon = next(
        (p for p in (get_resource_path(os.path.join("assets", "logo.ico")),
                     get_resource_path(os.path.join("assets", "logo.png")))
         if os.path.isfile(p)),
        None)

    ui.run(
        title="♟ Chess Engine Arena",
        favicon=favicon,
        dark=True,
        native=native,
        window_size=(1280, 860) if native else None,
        reload=False,
        show=True,
    )


# "__mp_main__" guard is required: NiceGUI's native mode uses multiprocessing
if __name__ in {"__main__", "__mp_main__"}:
    main()
