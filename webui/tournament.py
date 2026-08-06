# ═══════════════════════════════════════════════════════════
#  webui/tournament.py — Phase 2: Tournament UI (NiceGUI)
#
#  Reuses the UI-free tournament logic from tournament/manager.py
#  (Tournament, pairing algorithms, TournamentRunner). The runner
#  executes on its own thread; TournamentSession bridges it to the
#  NiceGUI event loop via a lock-protected snapshot + polling timer.
# ═══════════════════════════════════════════════════════════

import json
import os
import threading
import time
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

# The engine's standing in the games database, not in this tournament
_ELO_SLOT = """
<q-td :props="props" class="text-left">
  <span class="text-xs" :style="{ color: props.row.elo_color }">
    {{ props.row.elo }}
  </span>
</q-td>
"""

_DROP_SLOT = """
<q-td :props="props" class="text-center">
  <q-btn v-if="props.row.can_drop" dense flat round size="sm"
         icon="close" color="negative"
         @click="$parent.$emit('drop', props.row)">
    <q-tooltip>Remove from the tournament</q-tooltip>
  </q-btn>
</q-td>
"""


def _fmt_clock(ms):
    """mm:ss for a clock value in milliseconds (never negative)."""
    s = max(0, int(ms / 1000))
    return f"{s // 60}:{s % 60:02d}"


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

        # Current-game banner/clock snapshot
        self.white_name = ""
        self.black_name = ""
        _, base, _ = TIME_CONTROLS.get(
            getattr(tournament, "time_control", "classic"),
            TIME_CONTROLS["classic"])
        self.use_clock = base is not None          # Classic → no clocks
        self.wtime_ms = self.btime_ms = (base or 0) * 60000
        self.turn = "w"                            # side thinking right now
        self.clock_at = time.time()                # when the snapshot was taken

        self.board_dirty = True
        self.tables_dirty = True

    # ── Runner callbacks (worker thread!) ─────────────────

    def _cb_game_start(self, game):
        with self.lock:
            self.game_label = f"Round {game.round_num}"
            self.white_name = game.white.name
            self.black_name = game.black.name
            _, base, _ = TIME_CONTROLS.get(
                getattr(self.t, "time_control", "classic"),
                TIME_CONTROLS["classic"])
            self.wtime_ms = self.btime_ms = (base or 0) * 60000
            self.turn = "w"
            self.clock_at = time.time()
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
            self.use_clock = getattr(game, "use_clock", self.use_clock)
            self.wtime_ms = getattr(game, "wtime_ms", self.wtime_ms)
            self.btime_ms = getattr(game, "btime_ms", self.btime_ms)
            self.turn = board.turn        # side to move = thinking next
            self.clock_at = time.time()
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
        self.snapshot()

    def _cb_round_end(self, rnd):
        with self.lock:
            self.tables_dirty = True
        self.snapshot()

    def _cb_tournament_end(self, t):
        with self.lock:
            self.state = "finished"
            self.tables_dirty = True
            self.board_dirty = True
        self.snapshot()

    # ── Resume ────────────────────────────────────────────

    def snapshot(self):
        """
        Persist the resume point. Runs on the runner thread after every
        game, so it must never raise: losing a snapshot costs the resume
        point, not the tournament that is playing.
        """
        try:
            if self.t.finished:
                # Nothing left to resume; the games themselves stay in
                # tournament_games, which is what the list reads for
                # finished events
                self.db.delete_tournament_state(self.t.tournament_id)
                return
            self.db.save_tournament_state(
                self.t.tournament_id, self.t.name, self.t.format, self.state,
                json.dumps(self.t.to_dict(), separators=(",", ":")))
        except Exception as e:
            print(f"[TournamentSession] snapshot failed: {e}")

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
        self.snapshot()

    def pause(self):
        if self.runner and self.state == "running":
            self.runner.pause()
            self.state = "paused"
            self.status_msg = "Paused"
            self.snapshot()

    def stop(self):
        if self.runner:
            self.runner.stop()
        if self.state != "finished":
            self.state = "stopped"
        self.snapshot()

    def adjudicate(self, result):
        """End the current game with a user-decided result; play continues."""
        if self.runner and self.state in ("running", "paused"):
            self.runner.adjudicate(result)
            self.state = "running"     # adjudicating releases a pause

    def add_player(self, path):
        """Enter an engine into a Swiss event in progress. (ok, message)."""
        name = normalize_engine_name(
            os.path.splitext(os.path.basename(path))[0])
        ok, msg = self.t.add_player(TournamentPlayer(name, path))
        if ok:
            with self.lock:
                self.tables_dirty = True
            self.snapshot()
        return ok, msg

    def remove_player(self, name):
        """Drop a player from a tournament that has not started yet."""
        ok, msg = self.t.remove_player(name)
        if ok:
            with self.lock:
                self.tables_dirty = True
            self.snapshot()
        return ok, msg

    def set_rounds(self, count):
        """Change the length of a Swiss event."""
        ok, msg = self.t.set_rounds(count)
        if ok:
            with self.lock:
                self.tables_dirty = True
            self.snapshot()
        return ok, msg


def restore_tournaments(session):
    """
    Bring unfinished tournaments back into ACTIVE from their snapshots.

    Restored events are left paused whatever they were doing when the app
    went away: engines are not relaunched behind the user's back, and a
    machine that lost power mid-game should not silently resume playing.
    Press Start to carry on — the interrupted game is replayed from the
    beginning of that pairing, since only completed games are recorded.

    Safe to call more than once; anything already live is left alone.
    """
    restored = 0
    for row in session.db.get_resumable_tournaments():
        tid = row["tournament_id"]
        if tid in ACTIVE:
            continue
        try:
            data = json.loads(row["state"])
            book = (session.opening_book
                    if getattr(session.opening_book, "loaded", False)
                    else None)
            t = Tournament.from_dict(data, opening_book=book)
        except Exception as e:
            print(f"[tournament] could not restore {tid}: {e}")
            continue
        tsess = TournamentSession(t, session.db)
        tsess.state = "paused" if t.started else "ready"
        tsess.status_msg = ("Resumed — press Start to continue"
                            if t.started else "Ready — press Start")
        ACTIVE[tid] = tsess
        restored += 1
    return restored


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

        list_search = widgets.search_input(
            "Search name, format, status, date…").classes("w-full")

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
                         pagination=12) \
            .classes("w-full flex-grow arena-log dlg-table")
        table.add_slot("body-cell-badge", _STATUS_BADGE_SLOT)

        def refresh():
            # Anything unfinished from a previous run reappears here
            restore_tournaments(session)
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
            all_rows[:] = rows
            _apply_filter()

        all_rows = []

        def _apply_filter():
            table.rows = [r for r in all_rows
                          if _match(r, list_search.value or "",
                                    ("name", "format", "info", "date"))]
            table.update()

        list_search.on_value_change(lambda e: _apply_filter())

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
            # Default to the regular game's pace so a Classic tournament
            # plays at the same speed a Classic single game does
            movetime_in = ui.number(label="Move time (ms)",
                                    value=session.movetime_ms,
                                    min=100, max=60000, step=100) \
                .props("dense").classes("w-32")
            delay_in = ui.number(label="Move delay (s)", value=session.delay_s,
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

            resetting = False   # guards the clear-selection value change

            def add_player(path=None):
                p = path or eng_sel.value
                if not p or not os.path.isfile(p):
                    ui.notify("Select a valid engine first.", type="warning")
                    return
                name = normalize_engine_name(
                    os.path.splitext(os.path.basename(p))[0])
                if any(os.path.normcase(r["path"]) == os.path.normcase(p)
                       or r["name"] == name for r in roster):
                    ui.notify(f"{name} is already in the tournament.",
                              type="warning")
                    return
                roster.append({"name": name, "path": p})
                roster_ui.refresh()

            def on_pick(e):
                # Picking an engine adds it straight away; the box is then
                # cleared so the same engine can be picked again.
                nonlocal resetting
                if resetting or not e.value:
                    resetting = False
                    return
                add_player(e.value)
                resetting = True
                eng_sel.set_value(None)

            eng_sel.on_value_change(on_pick)

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
                    rank_txt, rank_col = session.rank_line(r["name"])
                    ui.label(rank_txt).classes("text-xs no-wrap") \
                        .style(f"color: {rank_col}")
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
            if len(roster) < 2:
                ui.notify("Add at least 2 players.", type="warning")
                return
            if len(names) != len(roster):
                # Renaming a row by hand can still collide
                ui.notify("Duplicate player names — each engine must be "
                          "unique.", type="warning")
                return
            players = [TournamentPlayer(r["name"], r["path"]) for r in roster]
            t = Tournament(
                name=(name_in.value or "Tournament").strip(),
                fmt=fmt.value,
                players=players,
                rounds=int(rounds_in.value or 5),
                movetime_ms=int(movetime_in.value or session.movetime_ms),
                time_control=tc_sel.value or "classic",
                double_rr=bool(double_rr.value),
                delay=float(delay_in.value or session.delay_s),
                analyzer_path=session.analyzer_path,
                opening_book=session.opening_book
                if session.opening_book.loaded else None,
            )
            tsess = TournamentSession(t, session.db)
            ACTIVE[t.tournament_id] = tsess
            tsess.snapshot()      # survives a close before it is ever started
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
    # Imported here rather than at module scope: main_page imports this
    # module, so a top-level import would be circular
    from webui.main_page import _discover_engines, pick_file

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
            decide_btn = ui.button(
                "Decide Result", on_click=lambda: _open_decide()) \
                .props("no-caps color=secondary") \
                .tooltip("Stop the current game and set its result yourself")
            add_btn = ui.button(
                "Add Player", on_click=lambda: _open_add()) \
                .props("no-caps color=secondary") \
                .tooltip("Enter another engine — it starts on zero and is "
                         "paired from the next round")
            rounds_in = ui.number(label="Rounds", value=t.rounds,
                                  min=1, max=99, step=1,
                                  on_change=lambda e: _set_rounds(e.value)) \
                .props("dense").classes("w-24") \
                .tooltip("Swiss length — cannot go below the round already "
                         "under way")
            stop_btn = widgets.icon_button(
                "Stop", "ic_stop", secondary=True,
                on_click=lambda: (tsess.stop(), _sync_controls()))
            ui.button("Close", on_click=lambda: _close()) \
                .props("flat color=grey no-caps")

        with ui.row().classes("w-full flex-grow no-wrap gap-4 min-h-0"):

            # ── Left: live board (Black on top, White below) ──
            with ui.column().classes("w-[46%] items-center gap-1 min-w-0"):
                game_lbl = ui.label(tsess.game_label) \
                    .classes("font-bold text-center w-full")
                opening_lbl = ui.label("").classes("text-xs italic") \
                    .style(f"color: {COLOR_BLUE}")

                black_banner, black_name_lbl, black_rank_lbl, \
                    black_clock_lbl, black_h2h_lbl = widgets.banner(COLOR_SILVER)

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

                white_banner, white_name_lbl, white_rank_lbl, \
                    white_clock_lbl, white_h2h_lbl = widgets.banner(COLOR_GOLD)

            # ── Right: standings / schedule / bracket ─────
            with ui.column().classes("flex-grow min-w-0"):
                # One box for both tables: the terms that make sense in a
                # tournament — an engine name, a round, a result — read the
                # same either way
                table_search = widgets.search_input(
                    "Search engine, round, result, reason…") \
                    .classes("w-full") \
                    .on_value_change(lambda e: _refresh_tables())
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
                        stand_table.on("drop", lambda e: _drop_player(e.args))
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
            decide_btn.set_visibility(tsess.state in ("running", "paused"))
            stop_btn.set_visibility(tsess.state in ("running", "paused"))
            # Only Swiss can absorb a late entrant or change its length,
            # and only until it ends
            swiss_live = (t.format == Tournament.FORMAT_SWISS
                          and tsess.state != "finished")
            add_btn.set_visibility(swiss_live)
            rounds_in.set_visibility(swiss_live)

        # Adjudication dialog: stop the current game, user picks the result
        with ui.dialog() as decide_dlg, ui.card().classes(
                "arena-panel items-center gap-3 p-6"):
            ui.label("DECIDE GAME RESULT").classes("arena-heading")
            decide_lbl = ui.label("").classes("text-sm text-gray-400")
            with ui.row().classes("gap-2 no-wrap"):
                ui.button("1-0  White wins",
                          on_click=lambda: _decide("1-0")).props("no-caps")
                ui.button("½-½  Draw",
                          on_click=lambda: _decide("1/2-1/2")) \
                    .props("no-caps color=secondary")
                ui.button("0-1  Black wins",
                          on_click=lambda: _decide("0-1")).props("no-caps")
            ui.button("Cancel", on_click=decide_dlg.close) \
                .props("flat color=grey no-caps")

        # Late entry: pick an engine, it joins the next round on zero points
        with ui.dialog() as add_dlg, ui.card().classes(
                "arena-panel gap-3 p-6 w-[460px]"):
            ui.label("ADD PLAYER").classes("arena-heading")
            ui.label("The engine starts on zero and is paired from the next "
                     "round. Games already scheduled are left alone.") \
                .classes("text-xs text-gray-500")
            with ui.row().classes("w-full items-center gap-1 no-wrap"):
                add_sel = ui.select({}, label="Engine", with_input=True) \
                    .props("dense options-dense").classes("flex-grow")

                async def _browse_add():
                    p = await pick_file("Select engine",
                                        ("Executables (*.exe;*.bin)",
                                         "All files (*.*)"))
                    if p:
                        _do_add(p)
                ui.button("…", on_click=_browse_add).props("dense") \
                    .tooltip("Browse for an engine")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=add_dlg.close) \
                    .props("flat color=grey no-caps")
                ui.button("Add", on_click=lambda: _do_add(add_sel.value)) \
                    .props("no-caps")

        def _open_add():
            entered = {p.engine_path for p in t.player_list}
            options = {k: v for k, v in _discover_engines().items()
                       if os.path.normcase(k) not in
                       {os.path.normcase(e) for e in entered}}
            add_sel.set_options(options or {"": "— all engines entered —"})
            add_sel.set_value(None)
            add_dlg.open()

        def _do_add(path):
            if not path or not os.path.isfile(path):
                ui.notify("Select a valid engine first.", type="warning")
                return
            ok, msg = tsess.add_player(path)
            ui.notify(msg, type="positive" if ok else "warning")
            if ok:
                add_dlg.close()
                _refresh_tables()

        def _drop_player(payload):
            # A one-argument $emit arrives as the row itself; more than one
            # arrives as a list. Accept either rather than guess.
            if isinstance(payload, list):
                payload = next((a for a in payload if isinstance(a, dict)), {})
            name = (payload or {}).get("player") if isinstance(payload, dict) \
                else payload
            if not name:
                return
            ok, msg = tsess.remove_player(name)
            ui.notify(msg, type="positive" if ok else "warning")
            if ok:
                _refresh_tables()

        def _set_rounds(value):
            if value is None or int(value) == t.rounds:
                return
            ok, msg = tsess.set_rounds(value)
            if not ok:
                ui.notify(msg, type="warning")
                rounds_in.set_value(t.rounds)      # bounce back to the truth
                return
            ui.notify(msg, type="positive")
            _refresh_tables()

        def _open_decide():
            with tsess.lock:
                white, black = tsess.white_name, tsess.black_name
            if not white:
                ui.notify("No game in progress.", type="info")
                return
            decide_lbl.set_text(f"{white}  vs  {black}")
            decide_dlg.open()

        def _decide(result):
            tsess.adjudicate(result)
            decide_dlg.close()
            _sync_controls()

        h2h_state = {"key": None, "w": "", "b": ""}

        def _refresh_banners(force_h2h=False):
            with tsess.lock:
                white, black = tsess.white_name, tsess.black_name
                use_clock = tsess.use_clock
                wtime, btime = tsess.wtime_ms, tsess.btime_ms
                turn, clock_at = tsess.turn, tsess.clock_at
            white_name_lbl.set_text(white or "—")
            black_name_lbl.set_text(black or "—")
            for raw, lbl in ((white, white_rank_lbl), (black, black_rank_lbl)):
                text, color = session.rank_line(raw) if raw else ("", "#555")
                lbl.set_text(text)
                lbl.style(f"color: {color}")
            # Head-to-head of the pairing; rescan only on new game/results
            if force_h2h or h2h_state["key"] != (white, black):
                w_w, dr, b_w = (session.head_to_head(white, black)
                                if white else (0, 0, 0))
                h2h_state.update(key=(white, black),
                                 w=widgets.h2h_html(w_w, dr, b_w),
                                 b=widgets.h2h_html(b_w, dr, w_w))
            white_h2h_lbl.set_content(h2h_state["w"])
            black_h2h_lbl.set_content(h2h_state["b"])
            if use_clock and white:
                # live countdown for the side currently thinking
                if tsess.state == "running":
                    elapsed = (time.time() - clock_at) * 1000
                    if turn == "w":
                        wtime -= elapsed
                    else:
                        btime -= elapsed
                white_clock_lbl.set_text(_fmt_clock(wtime))
                black_clock_lbl.set_text(_fmt_clock(btime))
            else:
                white_clock_lbl.set_text("")
                black_clock_lbl.set_text("")
            if turn == "b":
                black_banner.classes(add="active")
                white_banner.classes(remove="active")
            else:
                white_banner.classes(add="active")
                black_banner.classes(remove="active")

        def _refresh_tables():
            fmt_lbl.set_text(
                f"{t.format}  ·  Round {t.current_round}"
                + (f"/{t.rounds}" if t.format != Tournament.FORMAT_KNOCKOUT
                   else ""))
            query = table_search.value or ""
            _fill_standings(stand_table, t, session, query)
            _fill_schedule(sched_table, t, query)
            if rounds_in.value != t.rounds:
                rounds_in.set_value(t.rounds)
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
            if tables_dirty:
                session.invalidate_stats_caches()   # a game was saved
            _refresh_banners(force_h2h=tables_dirty)
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

        sched_table.on("rowDblclick",
                       lambda e: _open_game_pgn(session, e.args[1],
                                                sched_table.rows))
        _sync_controls()
        _refresh_tables()
    dialog.open()


async def _open_game_pgn(session, row, siblings=None):
    from webui.views import show_pgn_viewer
    gid = row.get("db_id")
    if gid:
        # Siblings in display order, so Prev/Next game work
        played = [(r["db_id"],) for r in (siblings or []) if r.get("db_id")]
        await widgets.with_loader(
            lambda: show_pgn_viewer(session, gid, played),
            "Loading game replay…")
    else:
        ui.notify("Game not finished yet.", type="info")


def _standings_table(t):
    swiss = t.format == Tournament.FORMAT_SWISS
    columns = [
        {"name": "rank",   "label": "#",      "field": "rank",  "align": "center"},
        {"name": "player", "label": "Player", "field": "player", "align": "left"},
        {"name": "elo",    "label": "Rating", "field": "elo",   "align": "left"},
        {"name": "score",  "label": "Score",  "field": "score", "align": "center",
         "sortable": True},
        {"name": "wdl",    "label": "W/D/L",  "field": "wdl",   "align": "center"},
    ]
    if swiss:
        columns.append({"name": "buch", "label": "Buchholz", "field": "buch",
                        "align": "center"})
    # Drop column, only ever populated before the first round
    columns.append({"name": "drop", "label": "", "field": "drop",
                    "align": "center", "style": "width: 44px"})
    table = ui.table(columns=columns, rows=[], row_key="player",
                     pagination=0).classes("w-full arena-log")
    table.add_slot("body-cell-rank", _RANK_MEDAL_SLOT)
    table.add_slot("body-cell-elo", _ELO_SLOT)
    table.add_slot("body-cell-drop", _DROP_SLOT)
    return table


def _fill_standings(table, t, session=None, query=""):
    """
    Fill the standings.

    Before the first round the table doubles as the roster: it carries each
    engine's live rating from the games database and a drop button, so the
    field can be trimmed without leaving the tournament window.
    """
    editable = not t.started
    rows = []
    for i, p in enumerate(t.get_standings(), 1):
        elo_txt, elo_col = (session.rank_line(p.name) if session
                            else ("", COLOR_MUTED))
        rows.append({
            "rank": i, "player": p.name, "score": p.score,
            "elo": elo_txt, "elo_color": elo_col,
            "wdl": f"{p.wins}/{p.draws}/{p.losses}",
            "buch": f"{p.buchholz:.1f}",
            "can_drop": editable,
        })
    # Filtering after ranking keeps the # column showing real positions
    table.rows = [r for r in rows
                  if _match(r, query, ("rank", "player", "elo", "wdl"))]
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


def _match(row, query, fields):
    """True if every whitespace-separated term appears in *fields*."""
    if not query:
        return True
    hay = " ".join(str(row.get(f, "")) for f in fields).lower()
    return all(term in hay for term in query.lower().split())


def _fill_schedule(table, t, query=""):
    badge_map = {"pending": "upcoming", "running": "running", "done": "finished"}
    rows = [
        {
            "gid": g.id, "badge": badge_map.get(g.status, "upcoming"),
            "round": g.round_num, "white": g.white.name, "black": g.black.name,
            "result": g.result or "—", "reason": g.reason or "",
            "db_id": getattr(g, "db_game_id", None),
        }
        for g in t.all_games
    ]
    table.rows = [r for r in rows
                  if _match(r, query, ("round", "white", "black",
                                       "result", "reason"))]
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

        # items-stretch: nicegui-row aligns children to flex-start, so these
        # columns would size to their content height and overflow the row
        # instead of handing a bounded height to the tables inside them.
        with ui.row().classes(
                "w-full flex-grow no-wrap gap-4 min-h-0 items-stretch"):
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
                    .classes("w-full flex-grow arena-log dlg-table")
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
                    .classes("w-full flex-grow arena-log dlg-table")

                async def open_pgn(e):
                    from webui.views import show_pgn_viewer
                    gid = e.args[1].get("gid")
                    if gid:
                        # Siblings in display order, so Prev/Next game work
                        siblings = [(r["game_id"],) for r in rows
                                    if r["game_id"]]
                        await widgets.with_loader(
                            lambda: show_pgn_viewer(session, gid, siblings),
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
