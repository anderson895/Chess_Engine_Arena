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
    # Bumped with every sound-system change; also reported from the browser
    # as "[arena-sound] v2 status" lines. If neither shows up, the running
    # copy (e.g. an old PyInstaller build in dist/) predates the fix.
    print("[arena] sound system v2 (wav + watchdog + beacon)", flush=True)

    native = "--browser" not in sys.argv

    if native:
        # WebView2 (pywebview) honors Chromium's autoplay policy: the Web
        # Audio context starts suspended and resume() is rejected without a
        # user gesture. NiceGUI silently reloads the page when a websocket
        # reconnect can't be rewound, and after that reload there is no
        # gesture — move sounds would die for the rest of the session.
        # Telling WebView2 to never require a gesture fixes that for good.
        flag = "--autoplay-policy=no-user-gesture-required"
        existing = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
        if flag not in existing:
            os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = \
                (existing + " " + flag).strip()

    # Allow "Export PGN" downloads inside the native (pywebview) window
    app.native.settings["ALLOW_DOWNLOADS"] = True

    # Open maximized (fills the screen, keeps the title bar)
    app.native.window_args["maximized"] = True

    # Serve piece sprites and UI icons
    app.add_static_files("/assets", get_resource_path("assets"))

    favicon = next(
        (p for p in (get_resource_path(os.path.join("assets", "logo.ico")),
                     get_resource_path(os.path.join("assets", "logo.png")))
         if os.path.isfile(p)),
        None)

    ui.run(
        title="Chess Engine Arena",
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
