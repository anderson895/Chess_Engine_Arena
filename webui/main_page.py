# ═══════════════════════════════════════════════════════════
#  webui/main_page.py — Main arena page (layout + event wiring)
# ═══════════════════════════════════════════════════════════

import os

from nicegui import app, ui, run

from core.constants import QUALITY_COLORS
from core.opening_book import OpeningBook
from core.utils import get_base_path, get_resource_path
from webui import dialogs, tournament, views, widgets
from webui.board import BoardView, EvalBar
from webui.session import GameSession, parse_opening_book
from webui.theme import (
    apply_theme, COLOR_GOLD, COLOR_SILVER, COLOR_BLUE, COLOR_GREEN,
    COLOR_ORANGE, COLOR_MUTED,
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
        n = len(session.opening_book._entries)
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
    path = next((p for p in _book_candidates() if os.path.isfile(p)), None)
    if path:
        book = await parse_opening_book(path)
        if book and book.loaded:
            session.opening_book = book
            session.opening_csv_path = path

    notify("Starting analyzer engine…")
    path = next((p for p in _analyzer_candidates() if os.path.isfile(p)), None)
    if path:
        await session.load_analyzer(path)

    refresh_asset_labels(book_lbl, analyzer_lbl, opening_lbl)
    _assets_ready = True


# ═══════════════════════════════════════════════════════════
#  Page
# ═══════════════════════════════════════════════════════════

@ui.page("/")
def main_page():
    apply_theme()
    session.clear_handlers()   # page rebuild → drop stale widget subscribers

    # ── Header ────────────────────────────────────────────
    # "row" is explicit: NiceGUI 3.x headers no longer default to it
    with ui.header().classes(
            "row no-wrap items-center bg-[#0F0F1E] px-4 py-2 gap-3"):
        ui.element("img").props('src="/assets/pieces/wN.png"') \
            .style("height: 34px; width: auto;")
        ui.label("ENGINE ARENA").classes("text-lg font-bold text-primary")
        ui.space()
        for card, handler, tip in [
            ("rankings",
             lambda: widgets.with_loader(
                 lambda: views.show_rankings(session), "Loading rankings…"),
             "Rankings & statistics"),
            ("openings",
             lambda: widgets.with_loader(
                 lambda: views.show_opening_stats(session),
                 "Analyzing openings…"),
             "Opening statistics"),
            ("tournaments",
             lambda: widgets.with_loader(
                 lambda: tournament.show_tournament_list(session),
                 "Loading tournaments…"),
             "Tournaments"),
            ("history",
             lambda: widgets.with_loader(
                 lambda: views.show_game_history(session),
                 "Loading game history…"),
             "Game history"),
        ]:
            ui.element("img").props(f'src="/assets/ui/nav_{card}.png"') \
                .classes("nav-card").on("click", handler) \
                .tooltip(tip)
        ui.space()
        pick_btn = ui.button("Pick Opening",
                             on_click=lambda: _pick_opening(pick_btn)) \
            .props("dense no-caps color=secondary")
        with pick_btn:
            ui.element("img").props('src="/assets/ui/ic_book.png"') \
                .classes("btn-ic ml-2")
        ui.button("✕", on_click=lambda: _clear_preset(pick_btn)) \
            .props("dense flat color=grey")

    # ── Main 3-column layout ──────────────────────────────
    with ui.row().classes("w-full no-wrap gap-3 p-2 items-stretch"):

        # ══ Left: configuration ══
        with ui.column().classes("w-[290px] shrink-0 gap-2"):
            with ui.card().classes("arena-panel w-full gap-1 p-3"):
                ui.label("CONFIGURATION").classes("arena-heading")
                mode = ui.radio(
                    {GameSession.MODE_EVE: "Engine vs Engine",
                     GameSession.MODE_HVE: "Play vs Engine"},
                    value=session.play_mode).props("dense")

                config_area = ui.column().classes("w-full gap-1")

                @ui.refreshable
                def config_ui():
                    if session.play_mode == GameSession.MODE_EVE:
                        _engine_config("BLACK", "e1", COLOR_SILVER, "bK")
                        with ui.row().classes("w-full justify-center"):
                            ui.button("⇄ SWITCH COLORS", on_click=_swap_colors) \
                                .props("dense flat size=sm") \
                                .classes("text-xs") \
                                .tooltip("Ipagpalit ang kulay ng dalawang engine")
                        _engine_config("WHITE", "e2", COLOR_GOLD, "wK")
                    else:
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            widgets.icon("ic_user", 14)
                            ui.label("PLAYER INFO").classes(
                                "text-xs font-bold").style("color:#00FF00")
                        ui.input(label="Your name", value=session.player_name,
                                 on_change=lambda e: setattr(
                                     session, "player_name", e.value or "")) \
                            .props("dense").classes("w-full")
                        ui.radio({"white": "White", "black": "Black"},
                                 value=session.player_color,
                                 on_change=lambda e: setattr(
                                     session, "player_color", e.value)) \
                            .props("inline dense")
                        with ui.row().classes("w-full justify-center"):
                            ui.button("⇄ SWITCH COLORS", on_click=_swap_colors) \
                                .props("dense flat size=sm") \
                                .classes("text-xs") \
                                .tooltip("Ipagpalit ang kulay mo at ng engine")
                        _engine_config("OPPONENT", "e2", COLOR_GOLD, "wK")

                def _engine_config(title, prefix, color, piece_code=None):
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        if piece_code:
                            widgets.piece(piece_code, 16)
                        ui.label(title).classes("text-xs font-bold") \
                            .style(f"color: {color}")

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
                        ui.button("…", on_click=browse).props("dense") \
                            .tooltip("Browse for an engine .exe")
                    ui.input(label="Display name",
                             value=getattr(session, f"{prefix}_name"),
                             on_change=lambda e, prefix=prefix: (
                                 setattr(session, f"{prefix}_name", e.value or ""),
                                 refresh_banners())) \
                        .props("dense").classes("w-full text-xs")

                def _swap_colors():
                    if session.game_running:
                        ui.notify("Itigil muna ang laro bago magpalit ng kulay",
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
                widgets.heading("ic_settings", "SETTINGS", size=15, text_cls="arena-heading")
                ui.number(label="Move time (ms)", value=session.movetime_ms,
                          min=100, max=60000, step=100,
                          on_change=lambda e: setattr(
                              session, "movetime_ms", int(e.value or 1000))) \
                    .props("dense").classes("w-full")
                ui.number(label="Move delay (s)", value=session.delay_s,
                          min=0.0, max=10.0, step=0.1,
                          on_change=lambda e: setattr(
                              session, "delay_s", float(e.value or 0.5))) \
                    .props("dense").classes("w-full")

                def on_piece_set(e):
                    set_piece_folder(e.value)
                    board_view.redraw_pieces()
                    config_ui.refresh()      # sidebar king icons follow
                ui.select(PIECE_SETS, value=piece_folder(),
                          label="Piece design", on_change=on_piece_set) \
                    .props("dense options-dense").classes("w-full")

                def on_board_theme(e):
                    set_board_theme(e.value)
                    push_board_colors()
                ui.select({k: label for k, (label, _, _)
                           in BOARD_THEMES.items()},
                          value=board_theme(), label="Board style",
                          on_change=on_board_theme) \
                    .props("dense options-dense").classes("w-full")

            with ui.card().classes("arena-panel w-full gap-1 p-3"):
                _action_btn("ic_play",    "START GAME",     session.start_game,
                            primary=True)
                _action_btn("ic_pause",   "PAUSE / RESUME", session.toggle_pause)
                _action_btn("ic_stop",    "STOP GAME",      _stop_game)
                _action_btn("ic_refresh", "NEW GAME",       session.new_game)
                _action_btn(None,         "FLIP BOARD",
                            lambda: board_view.flip())
                _action_btn("ic_export",  "EXPORT PGN",     _export_pgn)

            with ui.card().classes("arena-panel w-full gap-1 p-3"):
                widgets.heading("ic_flag", "STARTING OPENING", size=15, text_cls="arena-heading")
                preset_lbl = ui.label("Normal start") \
                    .classes("text-xs").style(f"color: {COLOR_MUTED}")
                ui.separator()
                ui.label("Material balance").classes("text-xs text-gray-500")
                material_lbl = ui.label("Equal").classes("mono text-sm")
                ui.separator()
                book_lbl = ui.label("Loading openings…").classes("text-xs")

                async def _load_csv():
                    p = await pick_file("Select openings CSV",
                                        ("CSV files (*.csv)", "All files (*.*)"))
                    if p and await session.load_opening_csv(p):
                        n = len(session.opening_book._entries)
                        book_lbl.set_text(f"{n} openings ({os.path.basename(p)})")
                        book_lbl.style(f"color: {COLOR_BLUE}")
                        ui.notify(f"{n} openings loaded", type="positive")
                widgets.icon_button("Load openings CSV…", "ic_download",
                                    on_click=_load_csv, secondary=True,
                                    dense=True, classes="w-full")
                ui.separator()
                widgets.heading("ic_search", "ANALYZER", size=15, text_cls="arena-heading")
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

        # ══ Center: board ══
        with ui.column().classes("flex-grow items-stretch gap-1 min-w-0"):
            status_lbl = ui.label("Ready — load engines and press START") \
                .classes("text-center font-bold text-primary w-full")
            opening_lbl = ui.label("").classes(
                "text-center italic text-sm w-full rounded px-2 py-1") \
                .style(f"color: {COLOR_BLUE}; background: #0D1B2A; "
                       f"border: 1px solid #003366")

            black_banner, black_name_lbl, black_rank_lbl = _banner(COLOR_SILVER)

            with ui.row().classes("w-full no-wrap flex-grow gap-2 "
                                  "justify-center items-stretch"):
                with ui.column().classes("items-center gap-0 py-1 self-stretch"):
                    ui.element("img").props('src="/assets/pieces/bK.png"') \
                        .style("height: 18px; width: auto;")
                    eval_bar = EvalBar()
                    ui.element("img").props('src="/assets/pieces/wK.png"') \
                        .style("height: 18px; width: auto;")
                with ui.element("div").classes("flex-grow min-w-0"):
                    board_view = BoardView(_board_state, on_click=_square_clicked)

            white_banner, white_name_lbl, white_rank_lbl = _banner(COLOR_GOLD)

            check_lbl = ui.label("").classes("text-center font-bold w-full") \
                .style("color: #FF4444")
            quality_lbl = ui.label("").classes(
                "text-center text-lg font-bold w-full")
            info_lbl = ui.label("").classes("text-center text-xs text-gray-500 w-full")

        # ══ Right: logs ══
        with ui.column().classes("w-[300px] shrink-0 gap-2"):
            with ui.card().classes("arena-panel w-full p-3 gap-1 h-[46%]"):
                ui.label("MOVES (SAN)").classes("arena-heading")
                moves_area = ui.scroll_area().classes("w-full flex-grow arena-log p-2")
                with moves_area:
                    moves_html = ui.html("").classes("mono text-sm leading-6")
            with ui.card().classes("arena-panel w-full p-3 gap-1 flex-grow"):
                ui.label("ENGINE OUTPUT").classes("arena-heading")
                eng_log = ui.log(max_lines=300).classes(
                    "w-full flex-grow arena-log text-xs")

    # ═══════════════════════════════════════════════════════
    #  Rendering helpers (closures over the widgets above)
    # ═══════════════════════════════════════════════════════

    def render_moves():
        parts = []
        for num, w_san, b_san in session.san_pairs():
            w_cls = "color:#FF8800" if ("+" in w_san or "#" in w_san) \
                else f"color:{COLOR_GOLD}"
            part = (f'<span style="color:#555">{num}.</span> '
                    f'<span style="{w_cls}">{w_san}</span>')
            if b_san:
                b_cls = "color:#FF8800" if ("+" in b_san or "#" in b_san) \
                    else "color:#CCCCCC"
                part += f' <span style="{b_cls}">{b_san}</span>'
            parts.append(part)
        if session.game_result and session.game_result not in ("", "*"):
            parts.append(f'<br><b style="color:#E94560">{session.game_result}</b>')
        moves_html.set_content("&nbsp; ".join(parts))
        moves_area.scroll_to(percent=1.0)

    def refresh_banners():
        white, black = session.player_names()
        white_name_lbl.set_text(white)
        black_name_lbl.set_text(black)
        for raw, lbl in ((white, white_rank_lbl), (black, black_rank_lbl)):
            text, color = session.rank_line(raw)
            lbl.set_text(text)
            lbl.style(f"color: {color}")
        # Active-turn highlight
        if session.board.turn == "b":
            black_banner.classes(add="active")
            white_banner.classes(remove="active")
        else:
            white_banner.classes(add="active")
            black_banner.classes(remove="active")

    def on_board_changed():
        board_view.refresh()
        render_moves()
        material_lbl.set_text(session.material_text())
        info_lbl.set_text(session.info_text())
        if session.board.in_check():
            side = "White" if session.board.turn == "w" else "Black"
            check_lbl.set_text(f"{side} is in CHECK!")
        else:
            check_lbl.set_text("")
        refresh_banners()

    def on_quality(quality):
        if not quality:
            quality_lbl.set_text("")
            return
        color = QUALITY_COLORS.get(quality, "#EAEAEA")
        quality_lbl.set_text(quality)
        quality_lbl.style(f"color: {color}")

    # ── Wire session events ───────────────────────────────
    session.on("board_changed", on_board_changed)
    session.on("status", status_lbl.set_text)
    session.on("opening", opening_lbl.set_text)
    session.on("engine_log", lambda text, tag: eng_log.push(text))
    session.on("eval_bar", eval_bar.set_cp)
    session.on("quality", on_quality)
    session.on("banners", refresh_banners)
    session.on("error", lambda msg: ui.notify(msg, type="negative",
                                              multi_line=True))
    session.on("eval", lambda side, ev, dp: eng_log.push(
        f"[{side.upper()}] eval {ev}  depth {dp}"))
    session.on("game_over", lambda result, reason, winner: (
        config_ui.refresh(),        # auto color-swap changed the selectors
        dialogs.show_game_over(
            session, result, reason, winner,
            on_new_game=lambda: ui.timer(
                0.05, session.new_game, once=True),
            on_rankings=lambda: views.show_rankings(session),
            on_export=_export_pgn)))

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
                .classes("text-xl font-bold text-primary")
            ui.spinner(size="46px", color="primary")
            boot_status = ui.label("Preparing…").classes("text-sm text-gray-400")
            widgets.hint("Unang takbo lang matagal — naka-cache na pagkatapos")
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

    # keep references used by the header closures
    main_page._preset_lbl = preset_lbl


# ═══════════════════════════════════════════════════════════
#  Header / button handlers
# ═══════════════════════════════════════════════════════════

def _board_state():
    return {
        "board": session.board,
        "last_move": session.last_move,
        "selected": session.selected_square,
        "legal_dests": session.legal_destinations(),
        "check_sq": session.check_square(),
    }


async def _square_clicked(br, bc):
    await session.click_square(br, bc)


def _banner(color):
    banner = ui.row().classes("player-banner w-full items-center justify-between")
    with banner:
        name_lbl = ui.label("").classes("font-bold").style(f"color: {color}")
        rank_lbl = ui.label("").classes("text-xs")
    return banner, name_lbl, rank_lbl


def _action_btn(icon, text, on_click, primary=False):
    """Full-width action button with an optional sprite icon."""
    btn = ui.button(on_click=on_click).classes("w-full")
    if not primary:
        btn.props("color=secondary")
    with btn:
        with ui.row().classes("items-center justify-center gap-2 no-wrap"):
            if icon:
                ui.element("img").props(f'src="/assets/ui/{icon}.png"') \
                    .classes("btn-ic")
            ui.label(text).classes("text-sm font-medium")
    return btn


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


def _export_pgn():
    pgn = session.export_pgn_text()
    if not pgn:
        ui.notify("No moves to export yet.", type="info")
        return
    ui.download.content(pgn, "game.pgn")
