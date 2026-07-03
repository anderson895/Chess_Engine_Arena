# ═══════════════════════════════════════════════════════════
#  webui/tournament.py — Phase 2: Tournament UI (NiceGUI)
#
#  Reuses the UI-free tournament logic from tournament/manager.py
#  (Tournament, pairing algorithms, TournamentRunner). The runner
#  executes on its own thread; TournamentSession bridges it to the
#  NiceGUI event loop via a lock-protected snapshot + polling timer.
# ═══════════════════════════════════════════════════════════

import os
import threading
from datetime import datetime

from nicegui import app, ui

from core.constants import TIME_CONTROLS
from core.utils import normalize_engine_name
from tournament.manager import (
    Tournament, TournamentPlayer, TournamentRunner,
)
from webui import widgets
from webui.board import BoardView, EvalBar
from webui.theme import (
    COLOR_GOLD, COLOR_SILVER, COLOR_BLUE, COLOR_GREEN, COLOR_ORANGE,
    COLOR_MUTED,
)

# Live tournaments registry: {tournament_id: TournamentSession}
ACTIVE: dict = {}

_STATUS_BADGE_SLOT = """
<q-td :props="props" class="text-center">
  <img :src="'/assets/ui/st_' + props.row.badge + '.png'"
       style="height: 16px; width: auto; vertical-align: middle;" />
</q-td>
"""

_RANK_MEDAL_SLOT = """
<q-td :props="props" class="text-center">
  <img v-if="props.row.rank <= 3"
       :src="'/assets/ui/medal_' + props.row.rank + '.png'"
       style="height: 24px; width: auto; vertical-align: middle;" />
  <span v-else>#{{ props.row.rank }}</span>
</q-td>
"""


class SnapshotBoard:
    """Immutable board snapshot usable by BoardView."""

    def __init__(self, rows=None):
        self.rows = rows or [["."] * 8 for _ in range(8)]

    def get(self, r, c):
        if 0 <= r < 8 and 0 <= c < 8:
            return self.rows[r][c]
        return None


class TournamentSession:
    """
    Bridges a threaded TournamentRunner to the UI.

    Runner callbacks (worker thread) only write lock-protected snapshot
    state and set dirty flags; the tournament window polls with a timer.
    Game persistence happens directly in the game-end callback via the
    Database (per-call connections → thread-safe).
    """

    def __init__(self, tournament: Tournament, db):
        self.t = tournament
        self.db = db
        self.runner = None
        self.lock = threading.Lock()

        self.board = SnapshotBoard()
        self.last_move = None
        self.cp = None
        self.opening = ""
        self.game_label = "—"
        self.status_msg = "Ready — press Start"
        self.state = "ready"          # ready | running | paused | stopped | finished

        self.board_dirty = True
        self.tables_dirty = True

    # ── Runner callbacks (worker thread!) ─────────────────

    def _cb_game_start(self, game):
        with self.lock:
            self.game_label = (f"Round {game.round_num}:  "
                               f"{game.white.name}  vs  {game.black.name}")
            self.board = SnapshotBoard()
            self.last_move = None
            self.cp = None
            self.opening = ""
            self.board_dirty = True
            self.tables_dirty = True

    def _cb_board_update(self, game, board, last_move, cp, mate, opening):
        with self.lock:
            self.board = SnapshotBoard([row[:] for row in board.board])
            self.last_move = last_move
            self.cp = cp
            self.opening = opening or ""
            self.board_dirty = True

    def _cb_game_end(self, game):
        if game.pgn:
            game_id, _ = self.db.save_tournament_game(
                tournament_id=self.t.tournament_id,
                tournament_name=self.t.name,
                fmt=self.t.format,
                round_num=game.round_num,
                white_name=game.white.name,
                black_name=game.black.name,
                result=game.result or "*",
                reason=game.reason,
                pgn=game.pgn,
                move_count=game.move_count,
                duration_sec=game.duration,
                opening=game.opening or None,
                time_control=TIME_CONTROLS.get(
                    getattr(self.t, "time_control", "classic"),
                    TIME_CONTROLS["classic"])[0],
            )
            game.db_game_id = game_id
        with self.lock:
            self.tables_dirty = True

    def _cb_round_end(self, rnd):
        with self.lock:
            self.tables_dirty = True

    def _cb_tournament_end(self, t):
        with self.lock:
            self.state = "finished"
            self.tables_dirty = True
            self.board_dirty = True

    _EMOJI_RE = None

    def _cb_status(self, msg):
        # Runner messages may carry emojis (legacy manager.py) — strip them
        import re
        if TournamentSession._EMOJI_RE is None:
            TournamentSession._EMOJI_RE = re.compile(
                r"[←-⯿️\U0001F000-\U0001FAFF]")
        with self.lock:
            self.status_msg = TournamentSession._EMOJI_RE.sub("", msg or "").strip()

    # ── Controls ──────────────────────────────────────────

    def start(self):
        if self.runner is None:
            self.runner = TournamentRunner(
                self.t,
                on_game_start=self._cb_game_start,
                on_board_update=self._cb_board_update,
                on_game_end=self._cb_game_end,
                on_round_end=self._cb_round_end,
                on_tournament_end=self._cb_tournament_end,
                on_status=self._cb_status,
            )
            self.runner.start()
        elif self.state == "paused":
            self.runner.resume()
        self.state = "running"

    def pause(self):
        if self.runner and self.state == "running":
            self.runner.pause()
            self.state = "paused"
            self.status_msg = "Paused"

    def stop(self):
        if self.runner:
            self.runner.stop()
        if self.state != "finished":
            self.state = "stopped"


def stop_all_tournaments():
    for tsess in ACTIVE.values():
        try:
            tsess.stop()
        except Exception:
            pass


app.on_shutdown(stop_all_tournaments)


# ═══════════════════════════════════════════════════════════
#  Tournament list
# ═══════════════════════════════════════════════════════════

def show_tournament_list(session):
    with ui.dialog() as dialog, ui.card().classes(
            "arena-panel w-[880px] max-w-full h-[620px] flex flex-col"):
        with ui.row().classes("w-full items-center gap-2"):
            ui.element("img").props('src="/assets/ui/nav_tournaments.png"') \
                .style("height: 44px; width: auto;")
            ui.label("TOURNAMENTS").classes("text-xl font-bold text-primary")
            ui.space()
            widgets.icon_button(
                "New Tournament", "ic_trophy",
                on_click=lambda: (dialog.close(),
                                  show_tournament_setup(session)))

        columns = [
            {"name": "badge",  "label": "",       "field": "badge", "align": "center",
             "style": "width: 90px"},
            {"name": "name",   "label": "Name",   "field": "name",  "align": "left"},
            {"name": "format", "label": "Format", "field": "format", "align": "center"},
            {"name": "games",  "label": "Games",  "field": "games", "align": "center"},
            {"name": "info",   "label": "Status", "field": "info",  "align": "left"},
            {"name": "date",   "label": "Date",   "field": "date",  "align": "center"},
        ]
        table = ui.table(columns=columns, rows=[], row_key="tid",
                         pagination=12).classes("w-full flex-grow arena-log")
        table.add_slot("body-cell-badge", _STATUS_BADGE_SLOT)

        def refresh():
            rows = []
            live_ids = set()
            for tid, tsess in ACTIVE.items():
                live_ids.add(tid)
                t = tsess.t
                badge = ("finished" if t.finished else
                         ("running" if tsess.state == "running" else "upcoming"))
                done = len(t.get_all_completed_games())
                rows.append({
                    "tid": tid, "live": True, "badge": badge,
                    "name": t.name, "format": t.format,
                    "games": f"{done}/{len(t.all_games) or '?'}",
                    "info": t.status_msg,
                    "date": t.created_at.strftime("%Y.%m.%d"),
                })
            for row in session.db.get_tournament_list():
                if row["tournament_id"] in live_ids:
                    continue
                rows.append({
                    "tid": row["tournament_id"], "live": False,
                    "badge": "finished",
                    "name": row["tournament_name"], "format": row["format"],
                    "games": row["game_count"], "info": "Saved in database",
                    "date": row["date"],
                })
            table.rows = rows
            table.update()

        async def open_row(row):
            if row["live"]:
                dialog.close()
                show_tournament_window(session, ACTIVE[row["tid"]])
            else:
                await widgets.with_loader(
                    lambda: show_tournament_history(session, row["tid"],
                                                    row["name"]),
                    "Loading tournament…")

        table.on("rowDblclick", lambda e: open_row(e.args[1]))
        widgets.hint("Double-click a tournament to open it")
        with ui.row().classes("w-full justify-end gap-2 dlg-foot"):
            widgets.icon_button("Refresh", "ic_refresh", on_click=refresh,
                                secondary=True)
            ui.button("Close", on_click=dialog.close) \
                .props("flat color=grey no-caps")
        refresh()
    dialog.open()


# ═══════════════════════════════════════════════════════════
#  Setup wizard
# ═══════════════════════════════════════════════════════════

def show_tournament_setup(session):
    from webui.main_page import _discover_engines, pick_file

    roster: list[dict] = []   # {"name": str, "path": str}

    with ui.dialog() as dialog, ui.card().classes(
            "arena-panel w-[640px] max-w-full flex flex-col"):
        widgets.heading("ic_trophy", "NEW TOURNAMENT")

        name_in = ui.input(
            label="Tournament name",
            value=f"Tournament {datetime.now().strftime('%Y-%m-%d %H:%M')}") \
            .props("dense").classes("w-full")

        with ui.row().classes("w-full items-center gap-4"):
            fmt = ui.select(
                [Tournament.FORMAT_SWISS, Tournament.FORMAT_ROUNDROBIN,
                 Tournament.FORMAT_KNOCKOUT],
                value=Tournament.FORMAT_SWISS, label="Format") \
                .props("dense").classes("w-40")
            rounds_in = ui.number(label="Rounds", value=5, min=1, max=30) \
                .props("dense").classes("w-24")
            double_rr = ui.checkbox("Double round-robin")
            double_rr.set_visibility(False)

        def on_fmt(e):
            rounds_in.set_visibility(e.value == Tournament.FORMAT_SWISS)
            double_rr.set_visibility(e.value == Tournament.FORMAT_ROUNDROBIN)
        fmt.on_value_change(on_fmt)

        with ui.row().classes("w-full items-center gap-4"):
            tc_sel = ui.select({k: v[0] for k, v in TIME_CONTROLS.items()},
                               value="classic", label="Time control") \
                .props("dense options-dense").classes("w-36") \
                .tooltip("Bullet/Blitz/Rapid: engines manage their own "
                         "clock and lose on time. Classic: fixed think "
                         "time per move")
            movetime_in = ui.number(label="Move time (ms)", value=500,
                                    min=100, max=60000, step=100) \
                .props("dense").classes("w-32")
            delay_in = ui.number(label="Move delay (s)", value=0.1,
                                 min=0.0, max=5.0, step=0.1) \
                .props("dense").classes("w-32")

        # Move time only applies to the clockless Classic preset
        tc_sel.on_value_change(
            lambda e: movetime_in.set_visibility(e.value == "classic"))

        ui.separator()
        ui.label("PLAYERS (engines)").classes("arena-heading")

        with ui.row().classes("w-full items-center gap-1"):
            options = _discover_engines()
            eng_sel = ui.select(options or {"": "— none found —"},
                                label="Engine", with_input=True) \
                .props("dense options-dense").classes("flex-grow")

            def add_player(path=None):
                p = path or eng_sel.value
                if not p or not os.path.isfile(p):
                    ui.notify("Select a valid engine first.", type="warning")
                    return
                base = normalize_engine_name(
                    os.path.splitext(os.path.basename(p))[0])
                name = base
                n = 2
                while any(r["name"] == name for r in roster):
                    name = f"{base}-{n}"
                    n += 1
                roster.append({"name": name, "path": p})
                roster_ui.refresh()

            ui.button("Add", on_click=lambda: add_player()).props("dense no-caps")

            async def browse_add():
                p = await pick_file("Select engine",
                                    ("Executables (*.exe;*.bin)",
                                     "All files (*.*)"))
                if p:
                    add_player(p)
            ui.button("…", on_click=browse_add).props("dense") \
                .tooltip("Browse for an engine")

        @ui.refreshable
        def roster_ui():
            if not roster:
                ui.label("No players yet — add at least 2 engines.") \
                    .classes("text-xs text-gray-500")
                return
            for i, r in enumerate(roster):
                with ui.row().classes(
                        "w-full items-center gap-2 no-wrap arena-log "
                        "rounded px-2 py-1"):
                    ui.element("img").props('src="/assets/ui/st_engine.png"') \
                        .style("height: 14px; width: auto;")
                    ui.input(value=r["name"],
                             on_change=lambda e, r=r: r.__setitem__(
                                 "name", e.value or r["name"])) \
                        .props("dense borderless").classes("w-40 text-sm")
                    ui.label(os.path.basename(r["path"])) \
                        .classes("text-xs text-gray-500 flex-grow")
                    ui.button("✕", on_click=lambda i=i: (
                        roster.pop(i), roster_ui.refresh())) \
                        .props("dense flat color=grey")

        roster_ui()

        analyzer_note = ("Analyzer attached — move quality will be recorded"
                         if session.analyzer and session.analyzer.alive
                         else "No analyzer — eval data will not be recorded")
        ui.label(analyzer_note).classes("text-xs") \
            .style(f"color: {COLOR_GREEN if session.analyzer else COLOR_ORANGE}")

        def create():
            names = {r["name"] for r in roster}
            if len(roster) < 2 or len(names) < 2:
                ui.notify("Add at least 2 players with unique names.",
                          type="warning")
                return
            players = [TournamentPlayer(r["name"], r["path"]) for r in roster]
            t = Tournament(
                name=(name_in.value or "Tournament").strip(),
                fmt=fmt.value,
                players=players,
                rounds=int(rounds_in.value or 5),
                movetime_ms=int(movetime_in.value or 500),
                time_control=tc_sel.value or "classic",
                double_rr=bool(double_rr.value),
                delay=float(delay_in.value or 0.1),
                analyzer_path=session.analyzer_path,
                opening_book=session.opening_book
                if session.opening_book.loaded else None,
            )
            tsess = TournamentSession(t, session.db)
            ACTIVE[t.tournament_id] = tsess
            dialog.close()
            show_tournament_window(session, tsess)

        with ui.row().classes("w-full justify-end gap-2 mt-2 dlg-foot"):
            ui.button("Cancel", on_click=dialog.close)                 .props("flat color=grey no-caps")
            widgets.icon_button("Create Tournament", "ic_trophy",
                                on_click=create)
    dialog.open()


# ═══════════════════════════════════════════════════════════
#  Live tournament window
# ═══════════════════════════════════════════════════════════

def show_tournament_window(session, tsess: TournamentSession):
    t = tsess.t

    with ui.dialog().props("maximized") as dialog, \
            ui.card().classes("arena-panel w-full h-full flex flex-col"):

        # ── Header + controls ─────────────────────────────
        with ui.row().classes("w-full items-center gap-3"):
            ui.element("img").props('src="/assets/ui/nav_tournaments.png"') \
                .style("height: 44px; width: auto;")
            with ui.column().classes("gap-0"):
                ui.label(t.name).classes("text-lg font-bold text-primary")
                fmt_lbl = ui.label("").classes("text-xs text-gray-500")
            ui.space()
            status_lbl = ui.label(tsess.status_msg).classes("text-sm") \
                .style(f"color: {COLOR_BLUE}")
            start_btn = ui.button(on_click=lambda: (
                tsess.start(), _sync_controls())).props("no-caps")
            with start_btn:
                with ui.row().classes("items-center gap-2 no-wrap"):
                    widgets.icon("ic_play", 15)
                    start_lbl = ui.label("Start").classes("text-sm font-medium")
            pause_btn = widgets.icon_button(
                "Pause", "ic_pause", secondary=True,
                on_click=lambda: (tsess.pause(), _sync_controls()))
            stop_btn = widgets.icon_button(
                "Stop", "ic_stop", secondary=True,
                on_click=lambda: (tsess.stop(), _sync_controls()))
            ui.button("Close", on_click=lambda: _close()) \
                .props("flat color=grey no-caps")

        with ui.row().classes("w-full flex-grow no-wrap gap-4 min-h-0"):

            # ── Left: live board ──────────────────────────
            with ui.column().classes("w-[46%] items-center gap-1 min-w-0"):
                game_lbl = ui.label(tsess.game_label) \
                    .classes("font-bold text-center w-full")
                opening_lbl = ui.label("").classes("text-xs italic") \
                    .style(f"color: {COLOR_BLUE}")
                with ui.row().classes("w-full no-wrap flex-grow gap-2 "
                                      "justify-center items-stretch"):
                    with ui.column().classes(
                            "items-center gap-0 py-1 self-stretch"):
                        eval_bar = EvalBar()
                    with ui.element("div").classes("flex-grow min-w-0"):
                        board_view = BoardView(lambda: {
                            "board": tsess.board,
                            "last_move": tsess.last_move,
                            "selected": None,
                            "legal_dests": set(),
                            "check_sq": None,
                        })

            # ── Right: standings / schedule / bracket ─────
            with ui.column().classes("flex-grow min-w-0"):
                with ui.tabs().classes("w-full") as tabs:
                    tab_stand = ui.tab("Standings")
                    tab_sched = ui.tab("Schedule")
                    tab_brack = (ui.tab("Bracket")
                                 if t.format == Tournament.FORMAT_KNOCKOUT
                                 else None)
                with ui.tab_panels(tabs, value=tab_stand) \
                        .classes("w-full flex-grow"):
                    with ui.tab_panel(tab_stand):
                        stand_table = _standings_table(t)
                    with ui.tab_panel(tab_sched):
                        sched_table = _schedule_table()
                    if tab_brack:
                        with ui.tab_panel(tab_brack):
                            bracket_html = ui.html("").classes(
                                "mono text-sm leading-7")

        winner_row = ui.row().classes("w-full justify-center items-center gap-3")
        winner_row.set_visibility(False)

        # ── Refresh plumbing ──────────────────────────────

        def _sync_controls():
            start_lbl.set_text("Resume" if tsess.state == "paused" else "Start")
            start_btn.set_visibility(tsess.state in ("ready", "paused"))
            pause_btn.set_visibility(tsess.state == "running")
            stop_btn.set_visibility(tsess.state in ("running", "paused"))

        def _refresh_tables():
            fmt_lbl.set_text(
                f"{t.format}  ·  Round {t.current_round}"
                + (f"/{t.rounds}" if t.format != Tournament.FORMAT_KNOCKOUT
                   else ""))
            _fill_standings(stand_table, t)
            _fill_schedule(sched_table, t)
            if tab_brack:
                bracket_html.set_content(_bracket_text(t))
            if t.finished and not winner_row.visible:
                winner_row.set_visibility(True)
                with winner_row:
                    ui.element("img").props('src="/assets/ui/medal_1.png"') \
                        .style("height: 42px; width: auto;")
                    ui.label(f"WINNER: {t.winner.name if t.winner else '?'}") \
                        .classes("text-2xl font-bold") \
                        .style(f"color: {COLOR_GOLD}")
                _sync_controls()
                _show_final_modal()

        def _show_final_modal():
            """Result modal shown once when the tournament finishes."""
            standings = t.get_standings()
            with ui.dialog() as fdlg, ui.card().classes(
                    "arena-panel items-center w-[460px] max-w-full gap-2 p-6"):
                ui.element("img").props('src="/assets/ui/badge_crown.png"') \
                    .style("height: 72px; width: auto;")
                ui.label("TOURNAMENT CHAMPION") \
                    .classes("text-2xl font-bold text-primary")
                ui.label(t.winner.name if t.winner else "?") \
                    .classes("text-xl font-bold").style(f"color: {COLOR_GOLD}")
                ui.label(f"{t.name}  ·  {t.format}  ·  "
                         f"{len(t.all_games)} games") \
                    .classes("text-xs text-gray-500")
                ui.separator()
                ui.label("FINAL STANDINGS").classes("arena-heading")
                for i, p in enumerate(standings[:3], 1):
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        ui.element("img").props(
                            f'src="/assets/ui/medal_{i}.png"') \
                            .style("height: 22px; width: auto;")
                        ui.label(f"{p.name}") \
                            .classes("font-bold text-sm")
                        ui.label(f"{p.score} pts "
                                 f"({p.wins}/{p.draws}/{p.losses})") \
                            .classes("text-xs text-gray-500")
                with ui.row().classes("w-full justify-end gap-2 mt-2 dlg-foot"):
                    ui.button("Close", on_click=fdlg.close) \
                        .props("flat color=grey no-caps")
            fdlg.open()

        def _tick():
            with tsess.lock:
                board_dirty = tsess.board_dirty
                tables_dirty = tsess.tables_dirty
                tsess.board_dirty = False
                tsess.tables_dirty = False
                status = tsess.status_msg
                cp = tsess.cp
                opening = tsess.opening
                game_label = tsess.game_label
            status_lbl.set_text(status)
            if board_dirty:
                board_view.refresh()
                game_lbl.set_text(game_label)
                opening_lbl.set_text(opening or "")
                if cp is not None:
                    eval_bar.set_cp(cp)
            if tables_dirty:
                _refresh_tables()
            if tsess.state == "finished":
                _sync_controls()

        timer = ui.timer(0.4, _tick)
        dialog.on("hide", lambda: timer.cancel())

        def _close():
            timer.cancel()
            dialog.close()

        sched_table.on("rowDblclick", lambda e: _open_game_pgn(session, e.args[1]))
        _sync_controls()
        _refresh_tables()
    dialog.open()


async def _open_game_pgn(session, row):
    from webui.views import show_pgn_viewer
    gid = row.get("db_id")
    if gid:
        await widgets.with_loader(lambda: show_pgn_viewer(session, gid),
                                  "Loading game replay…")
    else:
        ui.notify("Game not finished yet.", type="info")


def _standings_table(t):
    swiss = t.format == Tournament.FORMAT_SWISS
    columns = [
        {"name": "rank",   "label": "#",      "field": "rank",  "align": "center"},
        {"name": "player", "label": "Player", "field": "player", "align": "left"},
        {"name": "score",  "label": "Score",  "field": "score", "align": "center",
         "sortable": True},
        {"name": "wdl",    "label": "W/D/L",  "field": "wdl",   "align": "center"},
    ]
    if swiss:
        columns.append({"name": "buch", "label": "Buchholz", "field": "buch",
                        "align": "center"})
    table = ui.table(columns=columns, rows=[], row_key="player",
                     pagination=0).classes("w-full arena-log")
    table.add_slot("body-cell-rank", _RANK_MEDAL_SLOT)
    return table


def _fill_standings(table, t):
    rows = []
    for i, p in enumerate(t.get_standings(), 1):
        rows.append({
            "rank": i, "player": p.name, "score": p.score,
            "wdl": f"{p.wins}/{p.draws}/{p.losses}",
            "buch": f"{p.buchholz:.1f}",
        })
    table.rows = rows
    table.update()


def _schedule_table():
    columns = [
        {"name": "badge",  "label": "",       "field": "badge", "align": "center",
         "style": "width: 80px"},
        {"name": "round",  "label": "Rd",     "field": "round", "align": "center"},
        {"name": "white",  "label": "White",  "field": "white", "align": "left"},
        {"name": "black",  "label": "Black",  "field": "black", "align": "left"},
        {"name": "result", "label": "Result", "field": "result", "align": "center"},
        {"name": "reason", "label": "Reason", "field": "reason", "align": "left"},
    ]
    table = ui.table(columns=columns, rows=[], row_key="gid",
                     pagination=15).classes("w-full arena-log")
    table.add_slot("body-cell-badge", _STATUS_BADGE_SLOT)
    return table


def _fill_schedule(table, t):
    badge_map = {"pending": "upcoming", "running": "running", "done": "finished"}
    table.rows = [
        {
            "gid": g.id, "badge": badge_map.get(g.status, "upcoming"),
            "round": g.round_num, "white": g.white.name, "black": g.black.name,
            "result": g.result or "—", "reason": g.reason or "",
            "db_id": getattr(g, "db_game_id", None),
        }
        for g in t.all_games
    ]
    table.update()


def _bracket_text(t):
    """Simple text bracket for knockout tournaments."""
    lines = []
    for rnd in sorted(t._ko_round_games):
        lines.append(f'<b style="color:#E94560">Round {rnd}</b>')
        for g in t._ko_round_games[rnd]:
            res = g.result or "…"
            lines.append(
                f'&nbsp;&nbsp;{g.white.name} vs {g.black.name}'
                f'  <span style="color:#00BFFF">{res}</span>')
    if t.winner:
        lines.append(f'<b style="color:#FFD700">Winner: {t.winner.name}</b>')
    return "<br>".join(lines) or "Bracket not generated yet."


# ═══════════════════════════════════════════════════════════
#  Historical tournament view (from DB)
# ═══════════════════════════════════════════════════════════

def show_tournament_history(session, tournament_id, name):
    rows = session.db.get_tournament_games(tournament_id=tournament_id)
    if not rows:
        ui.notify("No games found for this tournament.", type="info")
        return

    # Rebuild simple standings from results
    scores: dict = {}

    def rec(player, pts):
        d = scores.setdefault(player, {"score": 0.0, "w": 0, "d": 0, "l": 0})
        d["score"] += pts
        if pts == 1.0:
            d["w"] += 1
        elif pts == 0.5:
            d["d"] += 1
        else:
            d["l"] += 1

    for r in rows:
        if r["result"] == "1-0":
            rec(r["white_engine"], 1.0); rec(r["black_engine"], 0.0)
        elif r["result"] == "0-1":
            rec(r["white_engine"], 0.0); rec(r["black_engine"], 1.0)
        elif r["result"] == "1/2-1/2":
            rec(r["white_engine"], 0.5); rec(r["black_engine"], 0.5)

    standings = sorted(scores.items(), key=lambda x: -x[1]["score"])
    fmt = rows[0]["format"]

    with ui.dialog().props("maximized") as dialog, ui.card().classes(
            "arena-panel w-full h-full flex flex-col"):
        with ui.row().classes("w-full items-center gap-2"):
            ui.element("img").props('src="/assets/ui/st_finished.png"') \
                .style("height: 20px; width: auto;")
            ui.label(name).classes("text-xl font-bold text-primary")
            ui.label(f"{fmt}  ·  {len(rows)} games  ·  {rows[0]['date']}") \
                .classes("text-xs text-gray-500")

        with ui.row().classes("w-full flex-grow no-wrap gap-4 min-h-0"):
            with ui.column().classes("w-[38%] min-h-0 overflow-auto"):
                ui.label("FINAL STANDINGS").classes("arena-heading")
                stand_cols = [
                    {"name": "rank",   "label": "#",      "field": "rank",
                     "align": "center"},
                    {"name": "player", "label": "Player", "field": "player",
                     "align": "left"},
                    {"name": "score",  "label": "Score",  "field": "score",
                     "align": "center"},
                    {"name": "wdl",    "label": "W/D/L",  "field": "wdl",
                     "align": "center"},
                ]
                st = ui.table(columns=stand_cols, rows=[
                    {"rank": i, "player": p, "score": d["score"],
                     "wdl": f"{d['w']}/{d['d']}/{d['l']}"}
                    for i, (p, d) in enumerate(standings, 1)
                ], row_key="player", pagination=0) \
                    .classes("w-full flex-grow arena-log")
                st.add_slot("body-cell-rank", _RANK_MEDAL_SLOT)

            with ui.column().classes("flex-grow min-w-0 min-h-0 overflow-auto"):
                ui.label("GAMES — double-click to replay") \
                    .classes("arena-heading")
                game_cols = [
                    {"name": "round",  "label": "Rd",     "field": "round",
                     "align": "center"},
                    {"name": "white",  "label": "White",  "field": "white",
                     "align": "left"},
                    {"name": "black",  "label": "Black",  "field": "black",
                     "align": "left"},
                    {"name": "result", "label": "Result", "field": "result",
                     "align": "center"},
                    {"name": "opening", "label": "Opening", "field": "opening",
                     "align": "left"},
                ]
                gt = ui.table(columns=game_cols, rows=[
                    {"gid": r["game_id"], "round": r["round_num"],
                     "white": r["white_engine"], "black": r["black_engine"],
                     "result": r["result"], "opening": r["opening"] or ""}
                    for r in rows
                ], row_key="gid", pagination=12) \
                    .classes("w-full flex-grow arena-log")

                async def open_pgn(e):
                    from webui.views import show_pgn_viewer
                    gid = e.args[1].get("gid")
                    if gid:
                        await widgets.with_loader(
                            lambda: show_pgn_viewer(session, gid),
                            "Loading game replay…")
                gt.on("rowDblclick", open_pgn)

        def export_all():
            pgns = [r["pgn"] for r in rows if r["pgn"]]
            if not pgns:
                ui.notify("No PGN data.", type="info")
                return
            safe = "".join(c if c.isalnum() else "_" for c in name)[:40]
            ui.download.content("\n\n".join(pgns), f"{safe}.pgn")

        with ui.row().classes("w-full justify-end gap-2 dlg-foot"):
            widgets.icon_button("Export all PGN", "ic_export",
                                on_click=export_all, secondary=True)
            ui.button("Close", on_click=dialog.close) \
                .props("flat color=grey no-caps")
    dialog.open()
