# ═══════════════════════════════════════════════════════════
#  webui/main_page.py — Main arena page (layout + event wiring)
# ═══════════════════════════════════════════════════════════

import os

from nicegui import app, ui, run

from core.review import move_number
from core.utils import (
    get_base_path, get_db_path, get_resource_path, fmt_clock,
    low_time_warning,
)
from data.database import retag_openings_once
from webui import dialogs, masters, review, tournament, views, widgets
from webui.board import BoardView, EvalBar
from webui.quality import MOVE_CLICK_JS, coach_html, move_list_html
from webui.session import GameSession, parse_opening_book, TIME_CONTROLS
from webui.sidebar import Sidebar
from webui.theme import (
    apply_theme, COLOR_BLUE, COLOR_GREEN, COLOR_ORANGE, COLOR_MUTED,
    PIECE_SETS, piece_folder, set_piece_folder,
    BOARD_THEMES, board_theme, set_board_theme, push_board_colors,
)

# One desktop app → one shared session
session = GameSession()
session.ask_promotion = dialogs.ask_promotion
app.on_shutdown(session.shutdown)


# ═══════════════════════════════════════════════════════════
#  Native file picker (falls back to a path prompt in browser)
# ═══════════════════════════════════════════════════════════

def _tk_file_dialog(title, file_types):
    """Open the standard Windows file dialog via a hidden Tk root."""
    import re
    import tkinter as tk
    from tkinter import filedialog

    # "Executables (*.exe;*.bin)" → ("Executables", "*.exe *.bin")
    patterns = []
    for ft in file_types:
        m = re.match(r"(.+?)\s*\((.+)\)", ft)
        if m:
            patterns.append((m.group(1).strip(),
                             m.group(2).replace(";", " ").strip()))
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        path = filedialog.askopenfilename(
            title=title, filetypes=patterns or [("All files", "*.*")])
    finally:
        root.destroy()
    return path or None


async def pick_file(title, file_types=("All files (*.*)",)):
    """Open a real file-explorer dialog. Returns the path or None."""
    # Native window → pywebview's file dialog (async proxy in NiceGUI)
    if app.native.main_window is not None:
        import inspect
        import webview
        # pywebview ≥6 uses the FileDialog enum; the legacy OPEN_DIALOG
        # shim is a fresh function object on every access, which cannot
        # be pickled across the process boundary NiceGUI uses.
        dialog_type = getattr(getattr(webview, "FileDialog", None),
                              "OPEN", None)
        if dialog_type is None:
            dialog_type = webview.OPEN_DIALOG
        result = app.native.main_window.create_file_dialog(
            dialog_type, allow_multiple=False, file_types=file_types)
        if inspect.isawaitable(result):
            result = await result
        if result:
            return result[0] if isinstance(result, (list, tuple)) else result
        return None

    # Browser mode → the app still runs locally, so open the standard
    # Windows file dialog on the server side (same UX as the old Tk UI)
    try:
        return await run.io_bound(_tk_file_dialog, title, file_types)
    except Exception as e:
        print(f"[pick_file] tk dialog failed: {e}")

    # Last resort: manual path prompt
    with ui.dialog() as dlg, ui.card().classes("arena-panel w-[520px]"):
        ui.label(title).classes("font-bold")
        path_input = ui.input(placeholder="Full path, e.g. D:\\engines\\x.exe") \
            .classes("w-full")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=lambda: dlg.submit(None)) \
                .props("flat color=grey")
            ui.button("OK", on_click=lambda: dlg.submit(path_input.value))
    return await dlg


# ═══════════════════════════════════════════════════════════
#  Startup asset loading (opening book + analyzer)
# ═══════════════════════════════════════════════════════════

STOCKFISH_NAMES = [
    "stockfish_18_x86-64.exe", "stockfish-18-x86-64.exe",
    "stockfish_18.exe", "stockfish-18.exe",
    "stockfish_17_x86-64.exe", "stockfish-17-x86-64.exe",
    "stockfish_17.exe", "stockfish-17.exe",
    "stockfish_16_x86-64.exe", "stockfish-16-x86-64.exe",
    "stockfish_16.exe", "stockfish-16.exe",
    "stockfish.exe", "stockfish_x86-64.exe", "stockfish-x86-64.exe",
    "stockfish-windows-x86-64.exe", "stockfish-windows.exe",
    "stockfish_avx2.exe", "stockfish-avx2.exe",
    "stockfish_bmi2.exe", "stockfish-bmi2.exe",
    "stockfish", "stockfish_x86-64", "stockfish-x86-64",
]


def _discover_engines():
    """Scan known folders for engine executables. Returns {path: label}."""
    found = {}
    seen_dirs = set()
    for base in [get_base_path(), os.getcwd()]:
        for sub in ["engines", "engine", "analyzer", "stockfish"]:
            d = os.path.normpath(os.path.join(base, sub))
            key = os.path.normcase(d)
            if key in seen_dirs or not os.path.isdir(d):
                continue
            seen_dirs.add(key)
            for f in sorted(os.listdir(d)):
                if f.lower().endswith((".exe", ".bin")):
                    p = os.path.join(d, f)
                    found[p] = f"{os.path.splitext(f)[0]}  ({sub})"
    return found


def _book_candidates():
    out = []
    for base in [get_base_path(), os.getcwd()]:
        for sub in ["openings", "opening", ""]:
            for fname in ["openings_sheet.csv", "openings.csv"]:
                out.append(os.path.join(base, sub, fname) if sub
                           else os.path.join(base, fname))
    return out


def _analyzer_candidates():
    out = []
    for base in [get_base_path(), os.getcwd()]:
        for sub in ["analyzer", "engines", "stockfish", "engine", "."]:
            for exe in STOCKFISH_NAMES:
                out.append(os.path.join(base, sub, exe))
    return out


# True once the opening book + analyzer have been loaded for this process
_assets_ready = False


def refresh_asset_labels(book_lbl, analyzer_lbl, opening_lbl):
    """Sync the config-panel labels with the session's asset state."""
    if session.opening_book.loaded:
        n = len(session.opening_book)
        name = os.path.basename(session.opening_csv_path or "")
        book_lbl.set_text(f"{n} openings ({name})")
        book_lbl.style(f"color: {COLOR_BLUE}")
        opening_lbl.set_text(f"{n} openings ready")
    else:
        book_lbl.set_text("No openings CSV found")
        book_lbl.style(f"color: {COLOR_ORANGE}")
    if session.analyzer and session.analyzer.alive:
        analyzer_lbl.set_text(
            f"Analyzer: {os.path.basename(session.analyzer_path or '')}")
        analyzer_lbl.style(f"color: {COLOR_GREEN}")
    else:
        analyzer_lbl.set_text("No analyzer — move quality disabled")
        analyzer_lbl.style(f"color: {COLOR_ORANGE}")


async def load_startup_assets(book_lbl, analyzer_lbl, opening_lbl,
                              status_cb=None):
    global _assets_ready
    notify = status_cb or (lambda msg: None)

    notify("Loading opening book…")
    csv_path = next((p for p in _book_candidates() if os.path.isfile(p)), None)
    if csv_path:
        book = await parse_opening_book(csv_path)
        if book and book.loaded:
            session.set_opening_book(book, csv_path)
            ui.timer(1.0, lambda: _retag_stored_openings(csv_path), once=True)

    notify("Starting analyzer engine…")
    engine_path = next((p for p in _analyzer_candidates() if os.path.isfile(p)),
                       None)
    if engine_path:
        await session.load_analyzer(engine_path)

    refresh_asset_labels(book_lbl, analyzer_lbl, opening_lbl)
    _assets_ready = True


async def _retag_stored_openings(csv_path):
    """
    Once per opening book: re-name the openings of the games already saved,
    which were named by move order before names followed positions. Runs
    in a worker process after a backup; does nothing on later starts.
    """
    try:
        changed = await run.cpu_bound(retag_openings_once, get_db_path(),
                                      csv_path)
    except Exception as e:
        # Same fallback as the book parse: no worker process, use a thread
        print(f"[openings] re-tag in a worker process failed ({e}); "
              "using a thread")
        try:
            changed = await run.io_bound(retag_openings_once, get_db_path(),
                                         csv_path)
        except Exception as e:
            print(f"[openings] re-tag failed: {e}")
            return
    if changed:
        session.invalidate_stats_caches()
        ui.notify(f"Opening names updated for {changed} saved games "
                  "(transpositions now recognised)", type="positive")


# ═══════════════════════════════════════════════════════════
#  Page
# ═══════════════════════════════════════════════════════════

@ui.page("/")
def main_page():
    apply_theme()
    session.clear_handlers()   # page rebuild → drop stale widget subscribers

    # Sound effects (assets/sounds/default, chess.com-style pack).
    # Web Audio API, not <audio> elements: each file is fetched and decoded
    # once, then every play is a cheap buffer source. Audio elements would
    # hit Chromium's ~75 WebMediaPlayer-per-page cap after a minute of
    # engine-vs-engine play and go permanently silent.
    ui.add_body_html(f"""
    <script>
    window.arenaSoundMuted = {str(session.sound_muted).lower()};
    window.arenaSoundBuffers = {{}};
    window.arenaAudioCtx = null;
    // WAV (raw PCM) instead of mp3: decodeAudioData needs no codec, so a
    // flaky WebView2 mp3 decoder can never leave a sound silently missing.
    const arenaSoundFiles = {{
        move: 'move-self', move_opp: 'move-opponent', capture: 'capture',
        castle: 'castle', promote: 'promote', check: 'move-check',
        game_start: 'game-start', game_end: 'game-end', illegal: 'illegal',
        low_time: 'tenseconds',
    }};
    // Report sound problems back to the server terminal (the native
    // window has no visible devtools console).
    function arenaSoundLog(msg) {{
        console.warn('[arena] ' + msg);
        try {{
            if (window.did_handshake) window.socket.emit('log', {{
                client_id: window.clientId, level: 'warning',
                message: '[arena-sound] ' + msg,
            }});
        }} catch (e) {{}}
    }}
    // (Re)create the context if it is missing or was closed, and try to
    // resume it whenever it is not running. resume() without a user
    // gesture may be rejected by the autoplay policy — swallow that and
    // keep retrying on every play/gesture instead of dying silently.
    function arenaEnsureCtx() {{
        let ctx = window.arenaAudioCtx;
        if (!ctx || ctx.state === 'closed') {{
            ctx = new (window.AudioContext || window.webkitAudioContext)();
            window.arenaAudioCtx = ctx;
            arenaStartKeepAlive(ctx);
        }}
        if (ctx.state !== 'running')
            ctx.resume().catch(() => {{}});
        return ctx;
    }}
    // Permanent, inaudible keep-alive tone (40 Hz at -54 dB). Chromium
    // closes the physical audio stream after a few seconds of *silence*
    // (especially when the window is occluded / another screen is up),
    // and the ~100-200 ms reopen latency swallows entire 0.15 s move
    // sounds. A continuously non-silent context keeps the stream open,
    // so every move sound starts instantly.
    function arenaStartKeepAlive(ctx) {{
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.frequency.value = 40;
        gain.gain.value = 0.002;
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
    }}
    // Fetch + decode one sound; on failure the slot is cleared so the
    // next play attempt retries instead of staying silent forever
    // (startup is busy parsing books/engines, so first loads can fail).
    function arenaLoadSound(kind) {{
        const file = arenaSoundFiles[kind];
        if (!file || window.arenaSoundBuffers[kind]) return;
        window.arenaSoundBuffers[kind] = 'loading';
        fetch('/assets/sounds/default/' + file + '.wav')
            .then((r) => {{
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.arrayBuffer();
            }})
            .then((buf) => arenaEnsureCtx().decodeAudioData(buf))
            .then((decoded) => {{ window.arenaSoundBuffers[kind] = decoded; }})
            .catch((e) => {{
                delete window.arenaSoundBuffers[kind];
                arenaSoundLog('sound load failed: ' + kind + ' — ' + e);
            }});
    }}
    // One status line per page load (and on every game start) so the
    // terminal always shows whether this JS version is live and healthy —
    // "no warnings" alone can't distinguish success from stale code.
    function arenaSoundStatus(when) {{
        const total = Object.keys(arenaSoundFiles).length;
        const ready = Object.values(window.arenaSoundBuffers)
            .filter((b) => b && b !== 'loading').length;
        const st = window.arenaAudioCtx ? window.arenaAudioCtx.state : 'none';
        arenaSoundLog('v2 status (' + when + '): ctx=' + st +
                      ', sounds=' + ready + '/' + total);
    }}
    arenaEnsureCtx();
    for (const kind of Object.keys(arenaSoundFiles)) arenaLoadSound(kind);
    setTimeout(() => arenaSoundStatus('page load'), 4000);
    // any user gesture unlocks/resumes the context (autoplay policy)
    for (const ev of ['pointerdown', 'keydown', 'touchend'])
        document.addEventListener(ev, arenaEnsureCtx);
    // Watchdog: report state changes; the keep-alive tone does the rest.
    let arenaLastState = '';
    setInterval(() => {{
        const ctx = arenaEnsureCtx();
        if (ctx.state !== arenaLastState) {{
            if (ctx.state !== 'running')
                arenaSoundLog('audio context state: ' + ctx.state);
            arenaLastState = ctx.state;
        }}
    }}, 10000);
    // Diagnostic: correlate sound loss with the window being hidden or
    // covered by another screen (Chromium throttles occluded windows).
    document.addEventListener('visibilitychange', () => {{
        arenaSoundLog('window became ' + document.visibilityState);
        if (document.visibilityState === 'visible') arenaEnsureCtx();
    }});
    window.arenaPlaySound = function(kind) {{
        if (window.arenaSoundMuted) return;
        if (kind === 'game_start') arenaSoundStatus('game start');
        try {{
            const buf = window.arenaSoundBuffers[kind];
            if (!buf || buf === 'loading') {{
                arenaSoundLog('no decoded buffer yet for: ' + kind);
                arenaLoadSound(kind);
                return;
            }}
            const ctx = arenaEnsureCtx();
            if (ctx.state !== 'running')
                arenaSoundLog('context not running (' + ctx.state +
                              ') while playing: ' + kind);
            const src = ctx.createBufferSource();
            src.buffer = buf;
            src.connect(ctx.destination);
            src.start();
        }} catch (e) {{
            arenaSoundLog('sound play failed: ' + kind + ' — ' + e);
        }}
    }};
    </script>
    """)

    # ── Sidebar: one row per screen, as on chess.com ──────
    nav = Sidebar("Engine Arena")
    nav.item("Play", "ic_play", current=True)
    for label, icon_name, handler, tip in [
        ("Rankings", "ic_trophy",
         lambda: widgets.with_loader(
             lambda: views.show_rankings(session), "Loading rankings…"),
         "Rankings & statistics"),
        ("Openings", "ic_book",
         lambda: widgets.with_loader(
             lambda: views.show_opening_stats(session),
             "Analyzing openings…"),
         "Opening statistics"),
        ("Tournaments", "badge_swords",
         lambda: widgets.with_loader(
             lambda: tournament.show_tournament_list(session),
             "Loading tournaments…"),
         "Tournaments"),
        ("History", "ic_calendar",
         lambda: widgets.with_loader(
             lambda: views.show_game_history(session),
             "Loading game history…"),
         "Game history"),
        ("Masters", "ic_database",
         lambda: widgets.with_loader(
             lambda: masters.show_masters_db(session),
             "Loading masters database…"),
         "Real games by GMs, IMs and other rated human players"),
    ]:
        item = nav.item(label, icon_name, handler, tooltip=tip)
    with item.row:                      # the last row: Masters
        masters_badge = ui.badge("").props("floating color=positive")
        masters_badge.set_visibility(False)
    # Pulls newly relayed tournament games on a worker thread a few
    # seconds from now; no-ops unless the user turned auto-sync on.
    masters.schedule_auto_sync(session, masters_badge)

    def _toggle_sound():
        session.sound_muted = not session.sound_muted
        sound_item.set_text("Sound off" if session.sound_muted else "Sound on")
        ui.run_javascript(
            f"window.arenaSoundMuted = {str(session.sound_muted).lower()}")

    nav.item("Settings", "ic_settings", lambda: settings_dlg.open(),
             footer=True, tooltip="Board and piece style")
    sound_item = nav.item("Sound off" if session.sound_muted else "Sound on",
                          "ic_bell", _toggle_sound, footer=True,
                          tooltip="Toggle sound effects")

    # ── Settings dialog, opened from the sidebar ──────────
    with ui.dialog() as settings_dlg, \
            ui.card().classes("arena-panel w-[360px] gap-3"):
        widgets.heading("ic_settings", "Settings", size=18,
                        text_cls="text-lg font-bold arena-title")

        def on_piece_set(e):
            set_piece_folder(e.value)
            board_view.redraw_pieces()
            refresh_banners()           # the avatars follow
            config_ui.refresh()         # and the kings by the names
        ui.select(PIECE_SETS, value=piece_folder(), label="Piece design",
                  on_change=on_piece_set) \
            .props("options-dense").classes("w-full")

        def on_board_theme(e):
            set_board_theme(e.value)
            push_board_colors()
        ui.select({k: label for k, (label, _, _) in BOARD_THEMES.items()},
                  value=board_theme(), label="Board style",
                  on_change=on_board_theme) \
            .props("options-dense").classes("w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Close", on_click=settings_dlg.close) \
                .props("flat no-caps color=grey")

    # ── Board column and side panel ───────────────────────
    with ui.row().classes("w-full no-wrap gap-4 items-start justify-center"):

        # ══ Board: status, player bars, eval bar ══
        # As wide as the board (its height limit plus the eval bar), so the
        # clocks line up with the board's right edge
        with ui.column().classes("flex-grow min-w-0 gap-1 items-stretch") \
                .style("max-width: calc(100vh - 136px)"):
            status_lbl = ui.label("Ready — set up a game and press Start Game") \
                .classes("arena-status w-full text-center")
            top_bar = widgets.PlayerBar()
            with ui.row().classes("w-full no-wrap gap-2 items-stretch"):
                with ui.column().classes("gap-0 self-stretch"):
                    eval_bar = EvalBar()
                with ui.element("div").classes("flex-grow min-w-0"):
                    # overlay: the grade badge of a move being previewed.
                    # Pieces move by click-click or by drag and drop.
                    board_view = BoardView(_board_state, on_click=_square_clicked,
                                           overlay=True,
                                           on_drag_start=_piece_picked,
                                           on_drop=_piece_dropped)
            bottom_bar = widgets.PlayerBar()

        # ══ Side panel: Play / Game / Engine ══
        with ui.column().classes("side-panel w-[400px] shrink-0 gap-0 no-wrap") \
                .style("height: calc(100vh - 32px)"):
            tabs = widgets.PanelTabs([("play", "Play", "ic_play"),
                                      ("game", "Game", "ic_flag"),
                                      ("engine", "Engine", "ic_power")])

            # ── Play: set a game up ──
            with tabs.page("play"), \
                    ui.scroll_area().classes("w-full flex-grow min-h-0"), \
                    ui.column().classes("panel-body w-full gap-2"):
                mode = ui.toggle(
                    {GameSession.MODE_EVE: "Engine vs Engine",
                     GameSession.MODE_HVE: "Play vs Engine",
                     GameSession.MODE_HVH: "2 Players"},
                    value=session.play_mode) \
                    .props("spread no-caps unelevated toggle-color=primary "
                           "color=secondary text-color=white") \
                    .classes("w-full")

                config_area = ui.column().classes("w-full gap-1")

                # Inputs that must not move under a running game. Which
                # engine plays is fixed when it is loaded, but its *name* is
                # read again when the result is saved, so swapping the
                # selector mid-game files the game under an engine that
                # never played it — and Elo is computed from exactly those
                # saved names. config_ui rebuilds these, so the list is
                # repopulated on every refresh.
                locked = []

                @ui.refreshable
                def config_ui():
                    locked.clear()
                    if session.play_mode == GameSession.MODE_EVE:
                        # No display-name input in EvE: the name is derived
                        # from the selected engine file anyway
                        _engine_config("BLACK", "e1", "bK", name_input=False)
                        _switch_colors_button("Swap the colors of the two engines")
                        _engine_config("WHITE", "e2", "wK", name_input=False)
                    elif session.play_mode == GameSession.MODE_HVH:
                        _two_player_config()
                    else:
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            widgets.icon("ic_user", 14)
                            ui.label("YOU").classes("arena-heading")
                        locked.append(
                            ui.input(label="Your name",
                                     value=session.player_name,
                                     on_change=lambda e: setattr(
                                         session, "player_name", e.value or ""))
                            .props("dense").classes("w-full"))
                        locked.append(
                            ui.radio({"white": "White", "black": "Black"},
                                     value=session.player_color,
                                     on_change=lambda e: setattr(
                                         session, "player_color", e.value))
                            .props("inline dense"))
                        _switch_colors_button("Swap colors with the engine")
                        _engine_config("OPPONENT", "e2", "wK")
                    for w in locked:
                        w.set_enabled(not session.game_running)

                def _two_player_config():
                    """Two names, one board: both sides are played by hand."""
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        widgets.icon("ic_user", 14)
                        ui.label("PLAYERS").classes("arena-heading")
                    for attr, label, piece_code in (
                            ("white_player", "White", "wK"),
                            ("black_player", "Black", "bK")):
                        with ui.row().classes("w-full items-center gap-1 no-wrap"):
                            widgets.piece(piece_code, 16)
                            locked.append(
                                ui.input(label=f"{label} player",
                                         value=getattr(session, attr),
                                         on_change=lambda e, attr=attr: (
                                             setattr(session, attr, e.value or ""),
                                             refresh_banners()))
                                .props("dense").classes("flex-grow"))
                    _switch_colors_button("Swap which player has White")
                    widgets.hint("Every move is graded as you play. Finished "
                                 "games are saved and rated under these names.")

                def _switch_colors_button(tip):
                    """The ⇄ link between the two sides' settings."""
                    with ui.row().classes("w-full justify-center"):
                        locked.append(
                            ui.button("⇄ Switch colors", on_click=_swap_colors)
                            .props("dense flat no-caps size=sm color=grey-5")
                            .tooltip(tip))

                def _engine_config(title, prefix, piece_code=None,
                                   name_input=True):
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        if piece_code:
                            widgets.piece(piece_code, 18)
                        ui.label(title).classes("arena-heading")

                    def apply_engine(path, prefix=prefix):
                        name = os.path.splitext(os.path.basename(path))[0]
                        setattr(session, f"{prefix}_path", path)
                        suffix = ("Black" if prefix == "e1" else
                                  ("Engine" if session.play_mode ==
                                   GameSession.MODE_HVE else "White"))
                        setattr(session, f"{prefix}_name", f"{name} ({suffix})")

                    # Dropdown of auto-discovered engines + Browse… button
                    options = _discover_engines()
                    current = getattr(session, f"{prefix}_path")
                    if current and current not in options:
                        options[current] = os.path.splitext(
                            os.path.basename(current))[0]
                    if not options:
                        options = {"": "— no engines found — use Browse"}

                    with ui.row().classes("w-full no-wrap items-center gap-1"):
                        sel = ui.select(options, value=current or None,
                                        label="Engine", with_input=True) \
                            .props("dense options-dense") \
                            .classes("flex-grow text-xs")
                        locked.append(sel)

                        def on_sel(e, prefix=prefix):
                            if e.value:
                                apply_engine(e.value, prefix)
                                config_ui.refresh()
                                refresh_banners()
                        sel.on_value_change(on_sel)

                        async def browse(prefix=prefix):
                            p = await pick_file(
                                "Select engine",
                                ("Executables (*.exe;*.bin)", "All files (*.*)"))
                            if p:
                                apply_engine(p, prefix)
                                config_ui.refresh()
                                refresh_banners()
                        locked.append(
                            ui.button("…", on_click=browse)
                            .props("dense color=secondary")
                            .tooltip("Browse for an engine .exe"))
                    if name_input:
                        locked.append(
                            ui.input(label="Display name",
                                     value=getattr(session, f"{prefix}_name"),
                                     on_change=lambda e, prefix=prefix: (
                                         setattr(session, f"{prefix}_name",
                                                 e.value or ""),
                                         refresh_banners()))
                            .props("dense").classes("w-full text-xs"))

                def _swap_colors():
                    if session.game_running:
                        ui.notify("Stop the game before switching colors",
                                  type="warning")
                        return
                    if session.swap_colors():
                        config_ui.refresh()

                def on_mode_change(e):
                    session.play_mode = e.value
                    if (session.play_mode == GameSession.MODE_HVE
                            and not session.e2_path.strip()):
                        default = get_resource_path(
                            os.path.join("engines", "gfruit.exe"))
                        if os.path.isfile(default):
                            session.e2_path = default
                            name = os.path.splitext(os.path.basename(default))[0]
                            session.e2_name = f"{name} (Engine)"
                    config_ui.refresh()
                    refresh_banners()
                mode.on_value_change(on_mode_change)

                with config_area:
                    config_ui()

                ui.separator()
                ui.label("TIME CONTROL").classes("arena-heading")
                tc_sel = ui.select(
                    {k: v[0] for k, v in TIME_CONTROLS.items()},
                    value=session.time_control, label="Time control",
                    on_change=lambda e: setattr(
                        session, "time_control", e.value)) \
                    .props("dense options-dense").classes("w-full") \
                    .tooltip("Bullet/Blitz: engines manage their own clock "
                             "and lose on time. Classic: no clock — fixed "
                             "think time per move. Each is rated separately.")
                ui.number(label="Move delay (s)", value=session.delay_s,
                          min=0.0, max=10.0, step=0.1,
                          on_change=lambda e: setattr(
                              session, "delay_s", float(e.value or 0.5))) \
                    .props("dense").classes("w-full")

                ui.separator()
                ui.label("STARTING POSITION").classes("arena-heading")
                preset_lbl = ui.label("Normal start").classes("text-sm") \
                    .style(f"color: {COLOR_MUTED}")
                with ui.row().classes("w-full no-wrap gap-2"):
                    pick_btn = ui.button(
                        "Pick Opening", on_click=lambda: _pick_opening(pick_btn)) \
                        .props("dense no-caps color=secondary") \
                        .classes("flex-grow") \
                        .tooltip("Start the game from a book opening")
                    ui.button(icon="close", on_click=lambda: _clear_preset(pick_btn)) \
                        .props("dense flat color=grey").tooltip("Normal start")

            with tabs.page("play"), ui.column().classes("panel-foot w-full"):
                # color=None: the green comes from .cta
                ui.button("Start Game", color=None,
                          on_click=lambda: _start_game()) \
                    .props("no-caps unelevated").classes("cta w-full")

            # ── Game: the coach, the moves, the controls ──
            with tabs.page("game"):
                with ui.element("div").classes("coach panel-body w-full"):
                    ui.element("img").props('src="/assets/logo.png"')
                    coach = ui.html("", sanitize=False).classes("coach-bubble")
                with ui.row().classes("w-full items-center no-wrap gap-2 px-[14px]"):
                    opening_lbl = ui.label("").classes("opening-line flex-grow")
                    # Shown while the board previews an earlier move
                    preview_bar = ui.button("Back to game", on_click=preview.leave) \
                        .props("dense no-caps unelevated color=secondary") \
                        .tooltip("Show the position as it stands in the game")
                    preview_bar.set_visibility(False)
                moves_area = ui.scroll_area().classes(
                    "w-full flex-grow min-h-0 px-[14px]")
                with moves_area:
                    # Our own markup; SAN comes from the board and is escaped
                    moves_html = ui.html("", sanitize=False).classes("move-grid w-full")
                    # A click on a move previews the position after it
                    moves_html.on("click", lambda e: preview.show(e.args),
                                  js_handler=MOVE_CLICK_JS)
                with ui.column().classes("panel-foot w-full gap-3"):
                    with ui.row().classes("nav-row w-full no-wrap gap-2"):
                        for icon_name, where, tip in (
                                ("first_page", "start", "Start position"),
                                ("chevron_left", "back", "Previous move"),
                                ("chevron_right", "forward", "Next move"),
                                ("last_page", "end", "Back to the game")):
                            ui.button(icon=icon_name, color=None,
                                      on_click=lambda w=where: _step(w)) \
                                .props("flat dense").classes("flex-grow").tooltip(tip)
                    with ui.row().classes("nav-row w-full no-wrap gap-2"):
                        undo_btn = ui.button("Undo", icon="undo", color=None,
                                             on_click=lambda: _undo()) \
                            .props("flat dense no-caps").classes("flex-grow") \
                            .tooltip("Take back your last move (against an "
                                     "engine, its reply too)")
                        pause_btn = ui.button("Pause", icon="pause", color=None,
                                              on_click=session.toggle_pause) \
                            .props("flat dense no-caps").classes("flex-grow")
                        stop_btn = ui.button("Stop", icon="stop", color=None,
                                             on_click=_stop_game) \
                            .props("flat dense no-caps").classes("flex-grow")
                        ui.button("Flip", icon="swap_vert", color=None,
                                  on_click=lambda: _flip()) \
                            .props("flat dense no-caps").classes("flex-grow")
                    ui.button("Game Review", color=None, on_click=_open_review) \
                        .props("no-caps unelevated").classes("cta w-full")
                    with ui.row().classes("w-full no-wrap gap-2"):
                        ui.button("New Game", on_click=lambda: _new_game()) \
                            .props("no-caps color=secondary").classes("flex-grow")
                        ui.button("Export PGN", on_click=_export_pgn) \
                            .props("no-caps color=secondary").classes("flex-grow")

            # ── Engine: what the engines say, and the assets ──
            with tabs.page("engine"), ui.column().classes(
                    "panel-body w-full flex-grow min-h-0 gap-2 no-wrap"):
                ui.label("ENGINE OUTPUT").classes("arena-heading")
                eng_log = ui.log(max_lines=300).classes(
                    "w-full flex-grow min-h-0 arena-log text-xs")
                info_lbl = ui.label("").classes("text-xs") \
                    .style(f"color: {COLOR_MUTED}")
                ui.separator()
                ui.label("OPENING BOOK").classes("arena-heading")
                book_lbl = ui.label("Loading openings…").classes("text-xs")

                async def _load_csv():
                    p = await pick_file("Select openings CSV",
                                        ("CSV files (*.csv)", "All files (*.*)"))
                    if p and await session.load_opening_csv(p):
                        n = len(session.opening_book)
                        book_lbl.set_text(f"{n} openings ({os.path.basename(p)})")
                        book_lbl.style(f"color: {COLOR_BLUE}")
                        ui.notify(f"{n} openings loaded", type="positive")
                widgets.icon_button("Load openings CSV…", "ic_download",
                                    on_click=_load_csv, secondary=True,
                                    dense=True, classes="w-full")
                ui.separator()
                ui.label("ANALYZER").classes("arena-heading")
                analyzer_lbl = ui.label("Loading analyzer…").classes("text-xs")

                async def _load_analyzer():
                    p = await pick_file("Select Stockfish / analyzer engine",
                                        ("Executables (*.exe)", "All files (*.*)"))
                    if p and await session.load_analyzer(p):
                        analyzer_lbl.set_text(f"Analyzer: {os.path.basename(p)}")
                        analyzer_lbl.style(f"color: {COLOR_GREEN}")
                        ui.notify("Analyzer ready", type="positive")
                widgets.icon_button("Load analyzer…", "ic_download",
                                    on_click=_load_analyzer, secondary=True,
                                    dense=True, classes="w-full")

    # ═══════════════════════════════════════════════════════
    #  Rendering helpers (closures over the widgets above)
    # ═══════════════════════════════════════════════════════

    def render_moves():
        """The move list: each move with its grade badge, clickable to preview."""
        analyst = session.analyst
        moves_html.set_content(move_list_html(
            analyst.sans, analyst.reviews, preview.shown_ply,
            session.game_result))
        if not preview.active:
            moves_area.scroll_to(percent=1.0)

    def show_shown_move():
        """The coach's line, the eval bar and Back to game for the move shown."""
        analyst = session.analyst
        ply = preview.shown_ply
        evaluation = analyst.eval_after(ply)
        if evaluation == (None, None) and not preview.active:
            # The latest position is still being analysed: until it is,
            # the bar shows the game's last known evaluation
            evaluation = next((r.evaluation for r in reversed(analyst.reviews)
                               if r and r.evaluation), (None, None))
        if evaluation != (None, None):
            eval_bar.set_eval(*evaluation)
        preview_bar.set_visibility(preview.active)
        if ply:
            rv = preview.review()
            if ply <= session.preset_plies:
                waiting = " — from the chosen opening"     # never graded live
            else:
                waiting = " — grading…" if session.analyzer else ""
            coach.set_content(coach_html(
                rv, f"{move_number(ply)} {analyst.sans[ply - 1]}", evaluation,
                analyst.best_line_san(ply) if rv else (), waiting))
        else:
            coach.set_content(
                "<div class='title'>Start position</div>"
                "<div>Every move is graded here as it is played.</div>")

    def on_preview_change():
        board_view.refresh()
        render_moves()
        show_shown_move()

    preview.on_change = on_preview_change
    preview.ply = None                  # a fresh page shows the game itself

    # Driven off both "banners" and "status". "banners" catches the start
    # immediately, but new_game clears game_running without emitting it, so
    # on its own the panel stayed locked after New Game interrupted a game.
    # "status" fires on every transition, including that one.
    #
    # Acting only on an actual change matters as much as the events do:
    # "status" also fires on every move, and refreshing config_ui that often
    # would rebuild the selectors under the user's cursor.
    _lock_state = {"running": None}

    def _sync_config_lock():
        running = session.game_running
        if running == _lock_state["running"]:
            return
        _lock_state["running"] = running
        mode.set_enabled(not running)
        tc_sel.set_enabled(not running)
        config_ui.refresh()

    def bars_by_side():
        """{'w': bar, 'b': bar} — White sits at the bottom unless flipped."""
        if board_view.flipped:
            return {"w": top_bar, "b": bottom_bar}
        return {"w": bottom_bar, "b": top_bar}

    def refresh_banners():
        white, black = session.player_names()
        # Head-to-head record of this exact pairing (from saved games)
        w_wins, draws, b_wins = session.head_to_head(white, black)
        white_pts, black_pts = session.board.material()
        lead = white_pts - black_pts
        bars = bars_by_side()
        for side, name, h2h, ahead in (
                ("w", white, widgets.h2h_html(w_wins, draws, b_wins), lead),
                ("b", black, widgets.h2h_html(b_wins, draws, w_wins), -lead)):
            text, color = session.rank_line(name)
            bars[side].show(side, name, text, color, h2h)
            bars[side].set_material(ahead)
            # The side to move has its clock lit, as on chess.com
            bars[side].set_active(session.game_running
                                  and session.board.turn == side)
        _update_clocks()

    def sync_controls():
        """Undo, Pause and Stop are live only when they can do something."""
        undo_btn.set_enabled(session.can_undo())
        pause_btn.set_enabled(session.game_running)
        stop_btn.set_enabled(session.game_running)
        pause_btn.set_text("Resume" if session.game_paused else "Pause")

    def on_board_changed():
        if preview.active and preview.ply >= session.analyst.ply:
            # The game was reset under the preview (new game, takeback)
            preview.ply = None
        board_view.refresh()
        render_moves()
        show_shown_move()
        info_lbl.set_text(session.info_text())
        refresh_banners()
        sync_controls()

    # Whether each side was last seen under ten seconds, so the warning
    # sounds on the poll that crosses the line and not on the nine after
    low_time = {}

    def _update_clocks():
        bars = bars_by_side()
        if not session.uses_clock():
            for bar in bars.values():
                bar.set_clock("")
            low_time.clear()
            return
        w, b = session.clock_ms()
        for side, ms in (("w", w), ("b", b)):
            bars[side].set_clock(fmt_clock(ms),
                                 low=session.game_running and ms < 10000)
        if not session.game_running:
            return
        # Both clocks are checked, not just the side to move: a frozen one
        # cannot cross the line anyway, so this costs a comparison and
        # saves having to know which side the game loop is waiting on.
        for side, ms in (("w", w), ("b", b)):
            warn, low_time[side] = low_time_warning(ms, low_time.get(side))
            if warn:
                # not ui.run_javascript: this also runs as the session's
                # "clock" handler, on the game loop, with no slot context
                client.run_javascript("window.arenaPlaySound('low_time')")

    def on_move_review(_rv):
        """A move was graded: its badge joins the list, the coach speaks."""
        render_moves()
        if not preview.active:          # else the board shows an earlier move
            show_shown_move()

    async def _start_game():
        await session.start_game()
        if session.game_running:
            tabs.select("game")

    async def _new_game():
        await session.new_game()
        tabs.select("play")

    def _undo():
        if not session.undo():
            ui.notify("Nothing to take back right now", type="info")

    def _flip():
        board_view.flip()
        eval_bar.set_flipped(board_view.flipped)
        refresh_banners()

    def _step(where):
        """Walk the board through the game: start, back, forward, end."""
        latest = session.analyst.ply
        ply = preview.shown_ply
        target = {"start": 0, "back": ply - 1, "forward": ply + 1,
                  "end": latest}[where]
        preview.show(max(0, min(latest, target)))

    def on_eval_bar(cp):
        if not preview.active:
            eval_bar.set_cp(cp)

    # ── Wire session events ───────────────────────────────
    # Session events fire from the background game-loop task, which has no
    # slot/client context in NiceGUI. Handlers that only mutate existing
    # elements (set_text, refresh) are fine, but anything that creates
    # elements or talks to the browser must go through the page's client.
    client = ui.context.client

    def _on_game_over(result, reason, winner):
        with client:                    # dialog needs a slot to attach to
            config_ui.refresh()         # auto color-swap changed the selectors
            dialogs.show_game_over(
                session, result, reason, winner,
                on_new_game=lambda: ui.timer(0.05, _new_game, once=True),
                on_rankings=lambda: views.show_rankings(session),
                on_export=_export_pgn,
                on_review=_open_review)

    def _on_error(msg):
        with client:
            ui.notify(msg, type="negative", multi_line=True)

    session.on("board_changed", on_board_changed)
    session.on("status", status_lbl.set_text)
    session.on("opening", opening_lbl.set_text)
    session.on("engine_log", lambda text, tag: eng_log.push(text))
    session.on("eval_bar", on_eval_bar)
    session.on("move_review", on_move_review)
    session.on("banners", refresh_banners)
    session.on("banners", _sync_config_lock)
    session.on("status", lambda _msg: _sync_config_lock())
    session.on("status", lambda _msg: sync_controls())
    session.on("banners", sync_controls)
    session.on("clock", _update_clocks)
    session.on("sound", lambda kind: client.run_javascript(
        f"window.arenaPlaySound('{kind}')"))
    # Live countdown while an engine is thinking (clock mode). 0.1 s so the
    # tenths shown under ten seconds actually move; set_text is a no-op when
    # the string is unchanged, so the other 9 polls in every second cost
    # nothing on the wire.
    ui.timer(0.1, _update_clocks)
    session.on("error", _on_error)
    session.on("eval", lambda side, ev, dp: eng_log.push(
        f"[{side.upper()}] eval {ev}  depth {dp}"))
    session.on("game_over", _on_game_over)

    # Startup: banner + assets. On first launch a persistent overlay blocks
    # the UI until the opening book and analyzer are ready — interacting
    # earlier would misbehave (and the parse would make clicks laggy).
    on_board_changed()
    if not _assets_ready:
        boot_dlg = ui.dialog().props(
            "persistent no-esc-dismiss no-backdrop-dismiss")
        with boot_dlg, ui.card().classes("arena-panel items-center gap-3 p-10"):
            ui.element("img").props('src="/assets/pieces/wN.png"') \
                .style("height: 72px; width: auto;")
            ui.label("CHESS ENGINE ARENA") \
                .classes("text-xl font-bold arena-title")
            ui.spinner(size="46px", color="primary")
            boot_status = ui.label("Preparing…").classes("text-sm text-gray-400")
            widgets.hint("Only the first run is slow — cached after that")
        boot_dlg.open()

        async def _boot():
            try:
                await load_startup_assets(book_lbl, analyzer_lbl, opening_lbl,
                                          boot_status.set_text)
            finally:
                boot_dlg.close()
        ui.timer(0.1, _boot, once=True)
    else:
        refresh_asset_labels(book_lbl, analyzer_lbl, opening_lbl)

    # keep references used by the module-level handlers below
    main_page._preset_lbl = preset_lbl


# ═══════════════════════════════════════════════════════════
#  Board and button handlers
# ═══════════════════════════════════════════════════════════

class BoardPreview:
    """
    Which position the main board shows: the game as it stands, or — once
    a move in the move list is clicked — the position after that move, with
    its grade. A preview holds while the game goes on, until the player
    goes back to the game (the latest move, a click on the board, or the
    "Back to game" bar). Positions and grades come from the session's
    analyst, which follows every move played.
    """

    def __init__(self):
        self.ply = None                  # None: the game as it stands
        self.on_change = lambda: None    # the page redraws through this

    @property
    def active(self):
        return self.ply is not None

    @property
    def shown_ply(self):
        """The ply whose position the board shows."""
        return session.analyst.ply if self.ply is None else self.ply

    def show(self, ply):
        """Preview the position after *ply* plies; the latest one is the game."""
        ply = max(0, int(ply))
        ply = None if ply >= session.analyst.ply else ply
        if ply != self.ply:
            self.ply = ply
            self.on_change()

    def leave(self):
        self.show(session.analyst.ply)

    def review(self):
        """core.review.MoveReview of the move shown, or None."""
        ply = self.shown_ply
        return session.analyst.reviews[ply - 1] if ply else None

    def state(self):
        """BoardView state for the position shown."""
        if self.ply is None:
            return {
                "board": session.board,
                "last_move": session.last_move,
                "selected": session.selected_square,
                "legal_dests": session.legal_destinations(),
                "check_sq": session.check_square(),
                "movable": session.movable_squares(),
            }
        analyst = session.analyst
        board = analyst.boards[self.ply]
        rv = self.review()
        return {
            "board": board,
            "last_move": analyst.moves[self.ply - 1] if self.ply else None,
            "selected": None,
            "legal_dests": set(),
            "check_sq": board.find_king(board.turn) if board.in_check() else None,
            "move_class": rv.cls if rv else None,
        }


preview = BoardPreview()


def _board_state():
    return preview.state()


async def _square_clicked(br, bc):
    if preview.active:
        preview.leave()             # a click on the board brings the game back
        return
    await session.click_square(br, bc)


def _piece_picked(br, bc):
    if not preview.active:          # a preview shows no movable pieces anyway
        session.pick_up(br, bc)


async def _piece_dropped(fr, fc, br, bc):
    if not preview.active:
        await session.drop_piece(fr, fc, br, bc)


async def _pick_opening(pick_btn):
    if not session.opening_book.loaded:
        ui.notify("Opening book not loaded — load an openings CSV first.",
                  type="warning")
        return
    moves, name = await dialogs.ask_opening_choice(session.opening_book)
    if moves is None:
        return
    session.preset_moves = moves
    session.preset_name = name
    lbl = getattr(main_page, "_preset_lbl", None)
    if moves:
        short = (name[:30] + "…") if name and len(name) > 30 else (name or "")
        pick_btn.set_text(short)
        if lbl:
            lbl.set_text(short)
            lbl.style(f"color: {COLOR_BLUE}")
    else:
        _clear_preset(pick_btn)


def _clear_preset(pick_btn):
    session.preset_moves = []
    session.preset_name = None
    pick_btn.set_text("Pick Opening")
    lbl = getattr(main_page, "_preset_lbl", None)
    if lbl:
        lbl.set_text("Normal start")
        lbl.style(f"color: {COLOR_MUTED}")


async def _stop_game():
    if not session.game_running:
        ui.notify("No game running.", type="info")
        return
    was_paused = session.game_paused
    session.game_paused = True
    white, black = session.player_names()
    result, reason = await dialogs.ask_stop_result(white, black)
    if result is None:
        session.game_paused = was_paused
        return
    await session.stop_game(result, reason)


def _open_review():
    """Game Review of the game on the board, or of the one just finished."""
    source = review.ReviewSource.from_session(session)
    if source is None:
        ui.notify("Play some moves first — there is nothing to review yet.",
                  type="info")
        return
    review.show_game_review(session, source)


def _export_pgn():
    pgn = session.export_pgn_text()
    if not pgn:
        ui.notify("No moves to export yet.", type="info")
        return
    ui.download.content(pgn, "game.pgn")
