# ═══════════════════════════════════════════════════════════
#  webui/masters.py — Masters Database browser
#
#  Real human games (GM / IM / titled and rated players) pulled from
#  Lichess broadcasts, Chess.com, TWIC or a local PGN file.
#  Read-only reference material: kept out of the engine Elo pipeline.
# ═══════════════════════════════════════════════════════════

import os
import shutil
import time

from nicegui import run, ui

from data.masters import MastersDB
from webui import widgets
from webui.theme import COLOR_BLUE, COLOR_GOLD, COLOR_MUTED, COLOR_SILVER
from webui.views import show_pgn_viewer

MAX_ROWS = 500          # SQL LIMIT — a million-game database never floods the UI

# Player/event pickers query the database per keystroke rather than
# preloading every distinct name, of which there are tens of thousands.
PICKER_LIMIT = 25
PICKER_DEBOUNCE = 300   # ms; NiceGUI defaults this to 0, which is a query
                        # per character

# Auto-sync: pull newly relayed OTB games in the background after startup.
AUTO_SYNC_KEY = "auto_sync"
LAST_SYNC_KEY = "last_sync"
SYNC_EVERY_HOURS = 12   # a full broadcast sweep is hundreds of requests
SYNC_TOURS = 8          # tournaments per automatic run, newest first
SYNC_DELAY_S = 4.0      # let the app become interactive first

# Hard ceiling so an automatic sync can never fill the disk. Stored PGN
# averages ~1.5 KB per game after annotations are stripped, so the default
# is roughly 300 MB of games.
MAX_GAMES_KEY = "max_games"
DEFAULT_MAX_GAMES = 200_000

RESULT_LABELS = {"1-0": "1-0", "0-1": "0-1", "1/2-1/2": "½-½", "*": "*"}

SORT_LABELS = {
    "date_desc":  "Newest first",
    "date_asc":   "Oldest first",
    "elo_desc":   "Highest rated",
    "moves_desc": "Longest games",
}

# Titles render as a small gold prefix, the player name as a filter link.
_PLAYER_SLOT = """
<q-td :props="props" class="text-left">
  <span v-if="props.row.%(t)s" class="mg-title">{{ props.row.%(t)s }}</span>
  <span class="mg-player" @click="$parent.$emit('player', props.row.%(n)s)">
    {{ props.row.%(n)s }}</span>
</q-td>
"""

_RESULT_SLOT = """
<q-td :props="props" class="text-center">
  <span class="mg-res" :style="{color: props.row.res_col}"
        @click="$parent.$emit('result', props.row.res_raw)">
    {{ props.row.res }}</span>
</q-td>
"""

_OPENING_SLOT = """
<q-td :props="props" class="text-left">
  <span class="mg-player" @click="$parent.$emit('opening', props.row.eco)">
    {{ props.row.opening }}</span>
</q-td>
"""

_EVENT_SLOT = """
<q-td :props="props" class="text-left">
  <span class="mg-player" @click="$parent.$emit('event', props.row.event)">
    {{ props.row.event }}</span>
</q-td>
"""

_ACTIONS_SLOT = """
<q-td :props="props" class="text-center no-wrap">
  <q-btn dense flat size="sm" icon="play_arrow" color="secondary"
         @click="$parent.$emit('replay', props.row)">
    <q-tooltip>Replay game</q-tooltip>
  </q-btn>
  <q-btn dense flat size="sm" icon="download" color="secondary"
         @click="$parent.$emit('pgn', props.row)">
    <q-tooltip>Download PGN</q-tooltip>
  </q-btn>
  <q-btn dense flat size="sm" icon="delete" color="negative"
         @click="$parent.$emit('del', props.row)">
    <q-tooltip>Remove from database</q-tooltip>
  </q-btn>
</q-td>
"""

# Plain CSS for ui.add_css: a <style> block inside ui.html() lands in a div
# and never applied, which ran the title into the name as "IMArca".
_CSS = f"""
.mg-title {{
    color: {COLOR_GOLD};
    font-size: 10px;
    font-weight: 700;
    vertical-align: 1px;
    margin-right: 5px;
}}
.mg-player, .mg-res {{
    cursor: pointer;
    text-decoration: underline;
    text-decoration-color: rgba(255,255,255,.25);
}}
.mg-player:hover, .mg-res:hover {{ color: {COLOR_BLUE}; }}
"""


def _mdb(session):
    """One MastersDB per session, created on first use."""
    db = getattr(session, "_masters_db", None)
    if db is None:
        db = MastersDB()
        session._masters_db = db
    return db


def _result_color(result):
    return {"1-0": COLOR_GOLD, "0-1": COLOR_SILVER,
            "1/2-1/2": COLOR_BLUE}.get(result, COLOR_MUTED)


def _mb(n):
    return f"{n / (1024 * 1024):.1f} MB"


# ═══════════════════════════════════════════════════════════
#  Background auto-sync
# ═══════════════════════════════════════════════════════════

def _hours_since_sync(db):
    stamp = db.get_meta(LAST_SYNC_KEY)
    if not stamp:
        return None
    try:
        return (time.time() - float(stamp)) / 3600.0
    except ValueError:
        return None


def auto_sync_enabled(db):
    return db.get_meta(AUTO_SYNC_KEY, "0") == "1"


def _due_for_sync(db):
    if not auto_sync_enabled(db):
        return False
    hours = _hours_since_sync(db)
    return hours is None or hours >= SYNC_EVERY_HOURS


def schedule_auto_sync(session, badge=None):
    """
    Arm the startup sync.

    Runs once, a few seconds after the page is interactive, on a worker
    thread — the app never blocks on the network. The last-sync timestamp
    throttles it, so restarting the app repeatedly does not re-download.
    """
    db = _mdb(session)

    async def go():
        if not _due_for_sync(db):
            return
        from tools import fetch_masters as fm
        cap = int(db.get_meta(MAX_GAMES_KEY, DEFAULT_MAX_GAMES))
        try:
            pgn = await run.io_bound(
                lambda: fm.fetch_broadcasts(1, log=lambda *_: None,
                                            max_tours=SYNC_TOURS))
            added = (await run.io_bound(db.import_pgn, pgn,
                                        "lichess-broadcast"))[0]
            pruned = await run.io_bound(db.prune, cap)
            db.set_meta(LAST_SYNC_KEY, time.time())
        except Exception as e:
            print(f"[masters] auto-sync failed: {e}")
            return
        if added and badge is not None:
            badge.set_text(str(added))
            badge.set_visibility(True)
        if added:
            msg = f"Masters DB: {added} new game(s) synced"
            if pruned:
                msg += f", {pruned} oldest pruned to stay under {cap:,}"
            ui.notify(msg, type="positive")

    ui.timer(SYNC_DELAY_S, go, once=True)


# ═══════════════════════════════════════════════════════════
#  Browser
# ═══════════════════════════════════════════════════════════

def show_masters_db(session):
    db = _mdb(session)

    with ui.dialog().props("maximized") as dialog, ui.card().classes(
            "arena-panel w-full h-full flex flex-col"):
        ui.add_css(_CSS)

        with ui.row().classes("w-full items-center"):
            widgets.heading("ic_user", "MASTERS DATABASE")
            ui.label("Real games by titled and rated human players") \
                .classes("text-xs text-gray-500")
            ui.space()
            widgets.icon_button(
                "Import games", "ic_download", secondary=True, dense=True,
                on_click=lambda: show_import_dialog(session, on_done=refresh))

        # ── Filter bar ────────────────────────────────────
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            search = widgets.search_input(
                "Search player, event, opening, ECO, site…") \
                .classes("flex-grow")
            result_sel = ui.select(
                {"": "Any result", "1-0": "1-0 White wins",
                 "0-1": "0-1 Black wins", "1/2-1/2": "½-½ Draw"},
                value="").props("dense outlined").classes("w-40")
            sort_sel = ui.select(SORT_LABELS, value="date_desc") \
                .props("dense outlined").classes("w-40")

        # Player-centric row: the question a chess database is usually
        # asked is "show me this person's games", not "search everything".
        def lookup_select(label):
            with ui.column().classes("flex-grow gap-0 min-w-0"):
                sel = ui.select([], label=label, with_input=True,
                                new_value_mode="add-unique", value=None,
                                clearable=True) \
                    .props(f"dense outlined input-debounce={PICKER_DEBOUNCE}") \
                    .classes("w-full")
                hint = ui.label("").classes("text-[10px] text-gray-500 pl-2")
            return sel, hint

        with ui.row().classes("w-full items-start gap-3 no-wrap"):
            player_sel, player_hint = lookup_select("Player")
            color_sel = ui.select({"": "Either colour", "white": "as White",
                                   "black": "as Black"}, value="") \
                .props("dense outlined").classes("w-40")
            opponent_sel, opponent_hint = lookup_select("Opponent")
            event_sel, event_hint = lookup_select("Event")

        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            eco_inp = ui.input(placeholder="ECO (e.g. B90)") \
                .props("dense outlined clearable debounce=400").classes("w-36")
            elo_inp = ui.number(placeholder="Min avg Elo", min=0, max=3000,
                                step=50, format="%d") \
                .props("dense outlined clearable debounce=400").classes("w-36")
            year_from = ui.number(placeholder="Year from", min=1475, max=2100,
                                  step=1, format="%d") \
                .props("dense outlined clearable debounce=400").classes("w-32")
            year_to = ui.number(placeholder="Year to", min=1475, max=2100,
                                step=1, format="%d") \
                .props("dense outlined clearable debounce=400").classes("w-32")
            source_sel = ui.select({"": "All sources"}, value="") \
                .props("dense outlined").classes("w-44")
            titled_sw = ui.switch("Titled only", value=False).props("dense")
            ui.space()
            widgets.icon_button("Reset filters", "ic_filter", flat=True,
                                dense=True, on_click=lambda: reset())

        columns = [
            {"name": "date",    "label": "Date",    "field": "date",    "align": "center", "sortable": True},
            {"name": "white",   "label": "White",   "field": "white",   "align": "left",   "sortable": True},
            {"name": "black",   "label": "Black",   "field": "black",   "align": "left",   "sortable": True},
            {"name": "welo",    "label": "W ELO",   "field": "welo",    "align": "center", "sortable": True},
            {"name": "belo",    "label": "B ELO",   "field": "belo",    "align": "center", "sortable": True},
            {"name": "avelo",   "label": "Av ELO",  "field": "avelo",   "align": "center", "sortable": True},
            {"name": "result",  "label": "Res",     "field": "res",     "align": "center"},
            {"name": "moves",   "label": "# Mvs",   "field": "moves",   "align": "center", "sortable": True},
            {"name": "opening", "label": "Opening", "field": "opening", "align": "left",   "sortable": True},
            {"name": "eco",     "label": "ECO",     "field": "eco",     "align": "center", "sortable": True},
            {"name": "event",   "label": "Event",   "field": "event",   "align": "left",   "sortable": True},
            {"name": "site",    "label": "Site",    "field": "site",    "align": "left"},
            {"name": "round",   "label": "Round",   "field": "round",   "align": "center"},
            {"name": "actions", "label": "", "field": "id", "align": "center"},
        ]
        table = ui.table(columns=columns, rows=[], row_key="id",
                         pagination={"rowsPerPage": 25}) \
            .classes("w-full flex-grow arena-log dlg-table")
        table.add_slot("body-cell-white",
                       _PLAYER_SLOT % {"t": "wtitle", "n": "white"})
        table.add_slot("body-cell-black",
                       _PLAYER_SLOT % {"t": "btitle", "n": "black"})
        table.add_slot("body-cell-result", _RESULT_SLOT)
        table.add_slot("body-cell-opening", _OPENING_SLOT)
        table.add_slot("body-cell-event", _EVENT_SLOT)
        table.add_slot("body-cell-actions", _ACTIONS_SLOT)

        # Replaces the table when nothing matches. Quasar's own "No data
        # available" row reads as an empty database, when in practice it is
        # almost always one filter too many.
        empty = ui.column().classes(
            "w-full flex-grow items-center justify-center gap-3 text-center")
        empty.set_visibility(False)
        with empty:
            widgets.icon("ic_filter", 44, cls="opacity-40")
            empty_msg = ui.label("").classes("text-base text-gray-300")
            empty_detail = ui.label("").classes("text-xs text-gray-500")
            widgets.icon_button("Clear all filters", "ic_refresh",
                                secondary=True, dense=True,
                                on_click=lambda: reset())

        with ui.row().classes("w-full items-center"):
            widgets.hint("Double-click a row to replay · click a name, result "
                         "or opening to filter by it")
            ui.space()
            count_lbl = ui.label("").classes("text-xs text-gray-500")

        with ui.row().classes("w-full items-center gap-2 dlg-foot"):
            widgets.icon_button(
                "Storage & maintenance", "ic_database", flat=True, dense=True,
                on_click=lambda: show_maintenance_dialog(session,
                                                         on_done=refresh))
            ui.space()
            widgets.icon_button("Export results", "ic_export", secondary=True,
                                dense=True, on_click=lambda: export_pgn())
            widgets.icon_button("Refresh", "ic_refresh", secondary=True,
                                dense=True, on_click=lambda: refresh())
            ui.button("Close", on_click=dialog.close) \
                .props("flat color=grey no-caps")

        rows_cache = []
        refreshing = {"on": False}

        # ── Data ──────────────────────────────────────────

        def filters():
            return {
                "search":      search.value or "",
                "player":      player_sel.value or "",
                "color":       color_sel.value or "",
                "opponent":    opponent_sel.value or "",
                "event":       event_sel.value or "",
                "result":      result_sel.value or "",
                "eco":         eco_inp.value or "",
                "min_elo":     int(elo_inp.value) if elo_inp.value else None,
                "year_from":   int(year_from.value) if year_from.value else None,
                "year_to":     int(year_to.value) if year_to.value else None,
                "source":      source_sel.value or "",
                "titled_only": bool(titled_sw.value),
            }

        def _lookup(select, fetch, hint_label, noun):
            """
            Make a picker query the database as the user types.

            The alternative — shipping every distinct name to the browser and
            filtering there — means a payload of tens of thousands of strings
            before the dialog can even open. Instead each keystroke asks for
            at most PICKER_LIMIT matches, and the hint says how many more
            exist so a truncated list never looks like the whole answer.
            """
            def load(text=""):
                names, total = fetch(text, PICKER_LIMIT)
                keep = select.value
                if keep and keep not in names:
                    names = names + [keep]
                select.set_options(names)
                # Always say "names", never a bare count: this sits directly
                # under a filter whose result is a number of games, and
                # "7 match(es)" reads as seven games rather than seven
                # people called something like Arca.
                if total > PICKER_LIMIT:
                    hint_label.set_text(f"showing {PICKER_LIMIT} of "
                                        f"{total:,} {noun} — keep typing")
                else:
                    hint_label.set_text(f"{total} {noun}"
                                        + (" to choose from" if not text
                                           else " match the text"))

            select.on("input-value", lambda e: load(e.args or ""))
            return load

        loaders = [
            _lookup(player_sel, db.search_players, player_hint, "players"),
            _lookup(opponent_sel, db.search_players, opponent_hint, "players"),
            _lookup(event_sel, db.search_events, event_hint, "events"),
        ]

        picker_sig = {"n": -1}

        def _fill_pickers():
            """Reseed the pickers' default lists when the game count moves."""
            total = db.count()
            if picker_sig["n"] == total:
                return
            picker_sig["n"] = total
            for load in loaders:
                load("")

        def refresh():
            nonlocal rows_cache
            # reset() and the source dropdown rebuild both write to controls
            # that are wired to refresh(); without this they re-enter.
            if refreshing["on"]:
                return
            refreshing["on"] = True
            try:
                _refresh()
            finally:
                refreshing["on"] = False

        def _refresh():
            nonlocal rows_cache
            f = filters()
            rows_cache = db.query(sort=sort_sel.value, limit=MAX_ROWS, **f)
            total = db.count(**f)

            stats = db.stats()
            opts = {"": "All sources"}
            opts.update({src: f"{src or '(none)'} ({n:,})"
                         for src, n in stats["sources"]})
            source_sel.set_options(opts, value=source_sel.value
                                   if source_sel.value in opts else "")
            _fill_pickers()

            _update_empty_state(f, total, stats)

            if not stats["total"]:
                count_lbl.set_text("Database empty — use Import games to fill it")
            else:
                head = (f"Showing {len(rows_cache):,} of {total:,} matches"
                        if total > len(rows_cache) else f"{total:,} match(es)")
                cap = int(db.get_meta(MAX_GAMES_KEY, DEFAULT_MAX_GAMES))
                count_lbl.set_text(
                    f"{head}  ·  {stats['total']:,} / {cap:,} games, "
                    f"{stats['players']:,} players, "
                    f"{stats['oldest']} → {stats['newest']}  ·  "
                    f"{_mb(stats['file_bytes'])} on disk")

            table.rows = [{
                "id":      g["id"],
                "date":    g["date"] or "—",
                "white":   g["white"],
                "black":   g["black"],
                "wtitle":  g["white_title"] or "",
                "btitle":  g["black_title"] or "",
                "welo":    g["white_elo"] or "—",
                "belo":    g["black_elo"] or "—",
                "avelo":   g["avg_elo"] or "—",
                "res":     RESULT_LABELS.get(g["result"], g["result"]),
                "res_raw": g["result"],
                "res_col": _result_color(g["result"]),
                # PGN counts plies; chess databases show full moves.
                "moves":   (g["ply_count"] + 1) // 2,
                "opening": g["opening"] or "—",
                "eco":     g["eco"] or "—",
                "event":   g["event"] or "—",
                "site":    g["site"] or "—",
                "round":   g["round"] or "—",
            } for g in rows_cache]
            table.update()

        # Human-readable name for each filter, for the empty-state message
        FILTER_LABELS = {
            "search": "search", "player": "player", "color": "colour",
            "opponent": "opponent", "event": "event", "result": "result",
            "eco": "ECO", "min_elo": "min Elo", "year_from": "year from",
            "year_to": "year to", "source": "source",
            "titled_only": "titled only",
        }

        def _update_empty_state(f, total, stats):
            """
            Explain a zero-result view.

            "No data available" on its own reads as an empty database, when
            in practice it is almost always one filter too many — most often
            'Titled only' against a source whose PGN carries no title tags.
            """
            show = not total and bool(stats["total"])
            empty.set_visibility(show)
            table.set_visibility(not show)
            if not show:
                return

            active = [FILTER_LABELS[k] for k, v in f.items() if v]
            empty_msg.set_text(
                f"No games match these {len(active)} filters."
                if len(active) > 1 else "No games match this filter.")

            # 'Titled only' is the usual culprit: PGN Mentor collections
            # carry no title tags at all, so the switch hides them wholesale.
            hint = ""
            if f.get("titled_only"):
                without_titled = dict(f, titled_only=None)
                if db.count(**without_titled):
                    src = f.get("source")
                    where = f"'{src}'" if src else "this selection"
                    hint = (f"No game in {where} carries a title tag — "
                            f"'Titled only' is hiding "
                            f"{db.count(**without_titled):,} match(es).")

            if not hint:
                # Name every filter that is holding results back, tightest
                # first, so the one worth dropping is obvious.
                blockers = []
                for key, value in f.items():
                    if not value:
                        continue
                    n = db.count(**dict(f, **{key: None}))
                    if n:
                        blockers.append((n, FILTER_LABELS[key]))
                blockers.sort()
                hint = " · ".join(f"without {name}: {n:,}"
                                  for n, name in blockers[:3])

            empty_detail.set_text(
                hint or f"Active: {', '.join(active)}. "
                        f"The database holds {stats['total']:,} games.")
            empty.set_visibility(True)

        def reset():
            refreshing["on"] = True          # one query, not one per control
            try:
                search.set_value("")
                player_sel.set_value(None)
                color_sel.set_value("")
                opponent_sel.set_value(None)
                event_sel.set_value(None)
                result_sel.set_value("")
                eco_inp.set_value(None)
                elo_inp.set_value(None)
                year_from.set_value(None)
                year_to.set_value(None)
                source_sel.set_value("")
                titled_sw.set_value(False)
                sort_sel.set_value("date_desc")
            finally:
                refreshing["on"] = False
            refresh()

        for control in (search, player_sel, color_sel, opponent_sel,
                        event_sel, result_sel, sort_sel, eco_inp, elo_inp,
                        year_from, year_to, source_sel, titled_sw):
            control.on_value_change(lambda e: refresh())

        # ── Row interactions ──────────────────────────────

        def replay(game_id):
            # A (id,) tuple list is all show_pgn_viewer needs for prev/next.
            return widgets.with_loader(
                lambda: show_pgn_viewer(session, game_id,
                                        [(g["id"],) for g in rows_cache],
                                        pgn_loader=db.get_pgn),
                "Loading game replay…")

        def set_filter(control, value):
            """Set one filter without the double query set_value would cause."""
            refreshing["on"] = True
            try:
                control.set_value(value)
            finally:
                refreshing["on"] = False
            refresh()

        table.on("rowDblclick", lambda e: replay(e.args[1]["id"]))
        table.on("replay", lambda e: replay(e.args["id"]))
        # Clicking a name fills the Player picker, not the free-text box —
        # that is what makes it show exactly that person's games.
        table.on("player", lambda e: set_filter(player_sel, e.args))
        table.on("result", lambda e: set_filter(result_sel, e.args))
        table.on("event", lambda e: set_filter(event_sel, e.args))
        table.on("opening", lambda e: set_filter(
            eco_inp, e.args if e.args != "—" else None))

        def download_one(row):
            pgn = db.get_pgn(row["id"])
            if not pgn:
                ui.notify("PGN not found.", type="negative")
                return
            name = f"{row['white']}_vs_{row['black']}".replace(" ", "_") \
                .replace(",", "")
            ui.download.content(pgn, f"{name}.pgn")
        table.on("pgn", lambda e: download_one(e.args))

        def on_delete(e):
            row = e.args
            with ui.dialog() as dlg, ui.card().classes(
                    "arena-panel w-[460px] max-w-full gap-3 p-5"):
                widgets.heading("ic_power", "REMOVE GAME",
                                text_cls="text-lg font-bold text-primary")
                ui.label(f"{row['white']} vs {row['black']} · {row['res']} · "
                         f"{row['date']}").classes("text-sm mono")
                widgets.hint("Only removes it from the masters database. "
                             "Engine ratings are unaffected.")
                with ui.row().classes("w-full justify-end gap-2 mt-1 dlg-foot"):
                    ui.button("Cancel", on_click=dlg.close) \
                        .props("flat color=grey no-caps")

                    def do_delete():
                        db.delete_game(row["id"])
                        dlg.close()
                        ui.notify("Removed", type="positive")
                        refresh()
                    ui.button("Remove", on_click=do_delete) \
                        .props("color=negative no-caps")
            dlg.open()
        table.on("del", on_delete)

        def export_pgn():
            if not rows_cache:
                ui.notify("Nothing to export.", type="warning")
                return
            pgns = [db.get_pgn(g["id"]) for g in rows_cache]
            ui.download.content("\n\n".join(p for p in pgns if p),
                                "masters_export.pgn")
            ui.notify(f"Exporting {len(pgns)} game(s)", type="positive")

        refresh()
    dialog.open()


# ═══════════════════════════════════════════════════════════
#  Storage & maintenance
# ═══════════════════════════════════════════════════════════

def show_maintenance_dialog(session, on_done=None):
    db = _mdb(session)

    with ui.dialog() as dialog, ui.card().classes(
            "arena-panel w-[680px] max-w-full flex flex-col gap-3 p-5"):
        widgets.heading("ic_database", "STORAGE & MAINTENANCE")

        size_lbl = ui.label("").classes("text-sm mono")
        detail_lbl = ui.label("").classes("text-xs text-gray-500")

        def refresh_stats():
            s = db.stats()
            cap = int(db.get_meta(MAX_GAMES_KEY, DEFAULT_MAX_GAMES))
            per = (s["pgn_bytes"] / s["total"]) if s["total"] else 0
            size_lbl.set_text(
                f"{s['total']:,} games  ·  {_mb(s['file_bytes'])} on disk  "
                f"·  {per:,.0f} bytes per game")
            projected = per * cap / (1024 * 1024)
            detail_lbl.set_text(
                f"At this rate the {cap:,}-game cap works out to about "
                f"{projected:,.0f} MB. Games beyond the cap are pruned "
                f"oldest-first after every automatic sync.")
            if on_done:
                on_done()

        ui.separator()
        ui.label("AUTOMATIC SYNC").classes("arena-heading")
        auto_sw = ui.switch(
            "Sync new tournament games in the background",
            value=auto_sync_enabled(db)).props("dense")
        hours = _hours_since_sync(db)
        ui.label(
            f"Runs {SYNC_TOURS} tournaments at most, no more than once every "
            f"{SYNC_EVERY_HOURS} hours, a few seconds after startup and on a "
            f"worker thread — the app never waits for it. "
            + (f"Last run {hours:.1f} h ago." if hours is not None
               else "Never run yet.")).classes("text-xs text-gray-500")

        cap_inp = ui.number(
            "Maximum games to keep", min=1000, max=5_000_000, step=10_000,
            format="%d",
            value=int(db.get_meta(MAX_GAMES_KEY, DEFAULT_MAX_GAMES))) \
            .props("dense outlined").classes("w-64")

        def save_settings():
            db.set_meta(AUTO_SYNC_KEY, "1" if auto_sw.value else "0")
            db.set_meta(MAX_GAMES_KEY,
                        int(cap_inp.value or DEFAULT_MAX_GAMES))
            ui.notify("Settings saved", type="positive")
            refresh_stats()
        auto_sw.on_value_change(lambda e: save_settings())
        cap_inp.on_value_change(lambda e: save_settings())

        ui.separator()
        ui.label("SHARED COLLECTION").classes("arena-heading")
        ui.label("Fetch the published snapshot instead of importing every "
                 "source yourself. Only master games are copied in — your "
                 "own engine games, tournaments and ratings are untouched.") \
            .classes("text-xs text-gray-500")
        shared_lbl = ui.label("").classes("text-xs mono")
        shared_bar = ui.linear_progress(value=0, show_value=False) \
            .classes("w-full")
        shared_bar.set_visibility(False)

        async def do_fetch_shared():
            from tools import fetch_masters as fm
            import tempfile

            shared_btn.disable()
            shared_lbl.set_text("Looking for a published snapshot…")
            try:
                found = await run.io_bound(fm.find_shared_db,
                                           log=lambda *_: None)
                if not found:
                    shared_lbl.set_text("No snapshot published yet.")
                    ui.notify("No shared database found.", type="warning")
                    return
                tag, url, size = found
                shared_lbl.set_text(f"Downloading {tag} ({_mb(size)})…")
                shared_bar.set_visibility(True)

                # io_bound runs on a worker thread, so the progress callback
                # cannot touch UI elements directly; stash and poll instead.
                seen = {"n": 0}
                tmp = os.path.join(tempfile.mkdtemp(), "shared.db")
                timer = ui.timer(0.3, lambda: shared_bar.set_value(
                    min(1.0, seen["n"] / size) if size else 0))
                try:
                    await run.io_bound(
                        fm.download_shared_db, tmp, url, size,
                        lambda *_: None,
                        lambda read, _t: seen.__setitem__("n", read))
                finally:
                    timer.deactivate()
                shared_bar.set_value(1.0)

                shared_lbl.set_text("Merging…")
                added, dupes = await run.io_bound(db.merge_from, tmp)
                shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)

                shared_lbl.set_text(
                    f"{tag}: {added:,} new game(s) added, "
                    f"{dupes:,} already present")
                ui.notify(f"Added {added:,} game(s) from {tag}",
                          type="positive" if added else "info")
                refresh_stats()
            except Exception as e:
                shared_lbl.set_text(f"Failed: {e}")
                ui.notify(f"Could not fetch the shared database: {e}",
                          type="negative")
            finally:
                shared_bar.set_visibility(False)
                shared_btn.enable()

        shared_btn = widgets.icon_button(
            "Download shared database", "ic_download", secondary=True,
            dense=True, on_click=do_fetch_shared)

        ui.separator()
        ui.label("MAINTENANCE").classes("arena-heading")
        with ui.row().classes("gap-2 flex-wrap"):

            async def do_prune():
                cap = int(cap_inp.value or DEFAULT_MAX_GAMES)
                n = await run.io_bound(db.prune, cap)
                freed = await run.io_bound(db.vacuum)
                ui.notify(f"Pruned {n:,} game(s), reclaimed {_mb(freed)}",
                          type="positive" if n else "info")
                refresh_stats()

            async def do_reparse():
                n, dropped = await run.io_bound(db.reparse, None)
                msg = f"Re-parsed {n:,} game(s) from stored PGN"
                if dropped:
                    msg += f", removed {dropped:,} unfinished"
                ui.notify(msg, type="positive")
                refresh_stats()

            async def do_backfill():
                n = await run.io_bound(db.backfill_openings)
                ui.notify(f"Filled {n:,} opening name(s)",
                          type="positive" if n else "info")
                refresh_stats()

            async def do_vacuum():
                freed = await run.io_bound(db.vacuum)
                ui.notify(f"Reclaimed {_mb(freed)}", type="positive")
                refresh_stats()

            widgets.icon_button("Prune to cap", "ic_scales", secondary=True,
                                dense=True, on_click=do_prune)
            widgets.icon_button("Compact file", "ic_database", secondary=True,
                                dense=True, on_click=do_vacuum)
            widgets.icon_button("Re-parse metadata", "ic_refresh",
                                secondary=True, dense=True,
                                on_click=do_reparse)
            widgets.icon_button("Fill opening names", "ic_book",
                                secondary=True, dense=True,
                                on_click=do_backfill)

        widgets.hint("Re-parse rebuilds every column from the PGN already "
                     "stored — use it after an importer update, it downloads "
                     "nothing.")

        ui.separator()
        ui.label("DELETE BY SOURCE").classes("arena-heading")
        src_row = ui.row().classes("gap-2 flex-wrap items-center")

        def build_sources():
            src_row.clear()
            with src_row:
                sources = db.stats()["sources"]
                if not sources:
                    ui.label("Nothing imported yet.") \
                        .classes("text-xs text-gray-500")
                    return
                for src, n in sources:
                    _purge_button(src, n)

        def _purge_button(src, n):
            def confirm():
                with ui.dialog() as dlg, ui.card().classes(
                        "arena-panel w-[440px] max-w-full gap-3 p-5"):
                    widgets.heading("ic_power", "DELETE SOURCE",
                                    text_cls="text-lg font-bold text-primary")
                    ui.label(f"Delete all {n:,} games imported from "
                             f"'{src}'?").classes("text-sm")
                    widgets.hint("Engine games and ratings are untouched. "
                                 "You can re-import at any time.")
                    with ui.row().classes("w-full justify-end gap-2 dlg-foot"):
                        ui.button("Cancel", on_click=dlg.close) \
                            .props("flat color=grey no-caps")

                        async def go():
                            dlg.close()
                            removed = await run.io_bound(db.purge, src)
                            freed = await run.io_bound(db.vacuum)
                            ui.notify(f"Deleted {removed:,} game(s), "
                                      f"reclaimed {_mb(freed)}",
                                      type="positive")
                            build_sources()
                            refresh_stats()
                        ui.button("Delete", on_click=go) \
                            .props("color=negative no-caps")
                dlg.open()
            widgets.icon_button(f"{src or '(none)'} · {n:,}", "ic_power",
                                flat=True, dense=True, on_click=confirm)

        build_sources()
        refresh_stats()

        with ui.row().classes("w-full justify-end dlg-foot"):
            ui.button("Close", on_click=dialog.close) \
                .props("flat color=grey no-caps")
    dialog.open()


# ═══════════════════════════════════════════════════════════
#  Import dialog
# ═══════════════════════════════════════════════════════════

def show_import_dialog(session, on_done=None):
    from tools import fetch_masters as fm

    db = _mdb(session)

    with ui.dialog() as dialog, ui.card().classes(
            "arena-panel w-[760px] max-w-full flex flex-col gap-3 p-5"):
        widgets.heading("ic_download", "IMPORT HUMAN GAMES")
        ui.label("All sources below are free and need no API key. "
                 "Re-importing is safe — duplicates are skipped.") \
            .classes("text-xs text-gray-500")

        with ui.tabs().classes("w-full") as tabs:
            t_bc = ui.tab("Lichess OTB")
            t_cc = ui.tab("Chess.com")
            t_li = ui.tab("Lichess player")
            t_pm = ui.tab("PGN Mentor")
            t_tw = ui.tab("TWIC")
            t_pg = ui.tab("PGN file")

        log_area = ui.log(max_lines=400).classes(
            "w-full h-40 arena-log mono text-xs")

        def log(msg):
            log_area.push(str(msg))

        busy = {"on": False}

        async def run_import(fetcher, source):
            """Fetch on a worker thread so the UI keeps responding."""
            if busy["on"]:
                ui.notify("An import is already running.", type="warning")
                return
            busy["on"] = True
            go_btn.disable()
            log("Fetching…")
            try:
                lines = []
                pgn = await run.io_bound(lambda: fetcher(lines.append))
                for line in lines:
                    log(line)
                if not pgn or not pgn.strip():
                    log("Nothing fetched.")
                    ui.notify("Nothing fetched — check the name or try again.",
                              type="warning")
                    return
                added, skipped, rejected, live = await run.io_bound(
                    db.import_pgn, pgn, source)
                log(f"→ {added} added, {skipped} duplicates, "
                    f"{rejected} unusable, {live} still in progress")
                ui.notify(f"Imported {added} new game(s)",
                          type="positive" if added else "info")
                if on_done:
                    on_done()
            except Exception as e:
                log(f"ERROR: {e}")
                ui.notify(f"Import failed: {e}", type="negative")
            finally:
                busy["on"] = False
                go_btn.enable()

        with ui.tab_panels(tabs, value=t_bc).classes("w-full"):
            with ui.tab_panel(t_bc):
                ui.label("Official over-the-board tournaments relayed live by "
                         "Lichess — real names, FIDE IDs, Elo and ECO. "
                         "This is the best source for recognised events.") \
                    .classes("text-xs text-gray-400")
                bc_pages = ui.number("Index pages", value=1, min=1, max=20,
                                     step=1, format="%d") \
                    .props("dense outlined")
                bc_tours = ui.number("Max tournaments (each has ~10 rounds)",
                                     value=10, min=1, max=200, step=5,
                                     format="%d").props("dense outlined")

            with ui.tab_panel(t_cc):
                ui.label("Chess.com Published-Data API. Either one account, or "
                         "walk the titled-player directory.") \
                    .classes("text-xs text-gray-400")
                cc_mode = ui.radio({"player": "Single player",
                                    "titled": "By title"},
                                   value="player").props("inline dense")
                cc_user = ui.input("Username", value="hikaru") \
                    .props("dense outlined")
                cc_title = ui.select(["GM", "IM", "FM", "WGM", "WIM", "CM",
                                      "NM"], value="GM", label="Title") \
                    .props("dense outlined")
                cc_players = ui.number("How many players", value=5, min=1,
                                       max=200, step=1, format="%d") \
                    .props("dense outlined")
                cc_months = ui.number("Months back per player", value=2, min=1,
                                      max=60, step=1, format="%d") \
                    .props("dense outlined")
                cc_title.bind_visibility_from(cc_mode, "value",
                                              lambda v: v == "titled")
                cc_players.bind_visibility_from(cc_mode, "value",
                                                lambda v: v == "titled")
                cc_user.bind_visibility_from(cc_mode, "value",
                                             lambda v: v == "player")

            with ui.tab_panel(t_li):
                ui.label("Export the rated games of one Lichess account. "
                         "Titles land in the PGN as [WhiteTitle \"GM\"].") \
                    .classes("text-xs text-gray-400")
                li_user = ui.input("Username", value="DrNykterstein") \
                    .props("dense outlined")
                li_max = ui.number("Max games", value=200, min=1, max=5000,
                                   step=50, format="%d").props("dense outlined")

            with ui.tab_panel(t_pm):
                ui.label("Bulk OTB collections. 'Players' is one whole "
                         "career per file; 'Openings' is every recorded "
                         "master game in a line, across all players — that "
                         "is the route to a database that feels complete.") \
                    .classes("text-xs text-gray-400")
                pm_kind = ui.radio({"players": "By player",
                                    "openings": "By opening"},
                                   value="players").props("inline dense")
                pm_sel = ui.select([], multiple=True, label="Collections",
                                   with_input=True) \
                    .props("dense outlined use-chips").classes("w-full")

                async def load_list():
                    lister = (fm.list_pgnmentor_openings
                              if pm_kind.value == "openings"
                              else fm.list_pgnmentor_players)
                    pm_sel.set_value([])
                    pm_sel.set_options(
                        await run.io_bound(lister, lambda *_: None))
                    ui.notify(f"{len(pm_sel.options)} available", type="info")

                with ui.row().classes("gap-2 items-center"):
                    widgets.icon_button("Load list", "ic_refresh",
                                        secondary=True, dense=True,
                                        on_click=load_list)
                    pm_all = ui.switch("Take everything", value=False) \
                        .props("dense")
                pm_kind.on_value_change(lambda e: load_list())
                widgets.hint("'Take everything' for openings is hundreds of "
                             "MB and takes a while — the cap in Storage & "
                             "maintenance still applies.")

            with ui.tab_panel(t_tw):
                ui.label("The Week in Chess publishes one zipped PGN per week, "
                         "~8-10k games each. Issue 1655 is late July 2026; "
                         "subtract about 52 per year going back.") \
                    .classes("text-xs text-gray-400")
                tw_from = ui.number("From issue", value=1654, min=1, max=3000,
                                    step=1, format="%d").props("dense outlined")
                tw_to = ui.number("To issue", value=1655, min=1, max=3000,
                                  step=1, format="%d").props("dense outlined")

            with ui.tab_panel(t_pg):
                ui.label("Import any PGN you already have — a ChessBase "
                         "export, a downloaded collection, anything.") \
                    .classes("text-xs text-gray-400")
                pgn_box = ui.textarea(placeholder="Paste PGN here…") \
                    .classes("w-full h-32 arena-log mono text-xs")

                async def on_upload(e):
                    text = e.content.read().decode("utf-8", "replace")
                    added, skipped, rejected, live = await run.io_bound(
                        db.import_pgn, text, "pgn")
                    log(f"{e.name}: {added} added, {skipped} duplicates, "
                        f"{rejected} unusable, {live} still in progress")
                    ui.notify(f"Imported {added} new game(s)",
                              type="positive" if added else "info")
                    if on_done:
                        on_done()
                ui.upload(on_upload=on_upload, auto_upload=True,
                          label="…or upload a .pgn file") \
                    .props('accept=".pgn"').classes("w-full")

        def start():
            tab = tabs.value
            if tab == "Lichess OTB":
                pages = int(bc_pages.value or 1)
                tours = int(bc_tours.value or 10)
                return run_import(
                    lambda lg: fm.fetch_broadcasts(pages, log=lg,
                                                   max_tours=tours),
                    "lichess-broadcast")
            if tab == "Chess.com":
                months = int(cc_months.value or 2)
                if cc_mode.value == "titled":
                    title = cc_title.value
                    n = int(cc_players.value or 5)
                    return run_import(
                        lambda lg: fm.fetch_chesscom_titled(title, n, months,
                                                            log=lg),
                        "chesscom")
                user = (cc_user.value or "").strip()
                if not user:
                    ui.notify("Enter a username.", type="warning")
                    return None
                return run_import(
                    lambda lg: fm.fetch_chesscom_player(user, months, log=lg),
                    "chesscom")
            if tab == "Lichess player":
                user = (li_user.value or "").strip()
                if not user:
                    ui.notify("Enter a username.", type="warning")
                    return None
                mx = int(li_max.value or 200)
                return run_import(
                    lambda lg: fm.fetch_lichess_player(user, mx, log=lg),
                    "lichess")
            if tab == "PGN Mentor":
                kind = pm_kind.value
                names = (list(pm_sel.options) if pm_all.value
                         else list(pm_sel.value or []))
                if not names:
                    ui.notify("Pick a collection, or load the list first.",
                              type="warning")
                    return None
                return run_import(
                    lambda lg: fm.fetch_pgnmentor(names, kind=kind, log=lg),
                    "pgnmentor")
            if tab == "TWIC":
                a, b = int(tw_from.value or 1), int(tw_to.value or 1)
                return run_import(lambda lg: fm.fetch_twic(a, b, log=lg), "twic")
            if tab == "PGN file":
                text = pgn_box.value or ""
                if not text.strip():
                    ui.notify("Paste a PGN first, or use the upload button.",
                              type="warning")
                    return None
                return run_import(lambda lg: text, "pgn")
            return None

        with ui.row().classes("w-full justify-end gap-2 dlg-foot"):
            go_btn = widgets.icon_button("Import", "ic_download",
                                         secondary=True, on_click=start)
            ui.button("Close", on_click=dialog.close) \
                .props("flat color=grey no-caps")

    dialog.open()
