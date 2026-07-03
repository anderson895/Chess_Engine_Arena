# ═══════════════════════════════════════════════════════════
#  webui/views.py — Rankings, Statistics, Opening stats,
#  Game History and PGN replay viewer
# ═══════════════════════════════════════════════════════════

import asyncio
import re

from nicegui import ui, run

from core.board import Board
from core.constants import RANK_TIERS, QUALITY_COLORS
from core.elo import compute_elo_history, compute_elo_ratings
from core.utils import normalize_engine_name, get_tier, classify_move_quality
from webui import widgets
from webui.board import BoardView, EvalBar
from webui.theme import COLOR_GOLD, COLOR_SILVER, COLOR_BLUE, COLOR_RED

_TIER_CELL_SLOT = """
<q-td :props="props">
  <span :style="{color: props.row.tier_col}">{{ props.row.tier }}</span>
</q-td>
"""

_RANK_CELL_SLOT = """
<q-td :props="props" class="text-center">
  <img v-if="props.row.rank <= 3"
       :src="'/assets/ui/medal_' + props.row.rank + '.png'"
       style="height: 26px; width: auto; vertical-align: middle;" />
  <span v-else>#{{ props.row.rank }}</span>
</q-td>
"""


# ═══════════════════════════════════════════════════════════
#  Rankings & Statistics (merged view)
# ═══════════════════════════════════════════════════════════

def show_rankings(session):
    with ui.dialog().props("maximized") as dialog, ui.card().classes(
            "arena-panel w-full h-full flex flex-col"):
        widgets.heading("ic_trophy", "RANKINGS & STATISTICS")
        ui.label("Elo ratings and W/D/L from all recorded games — "
                 "Bullet/Blitz/Rapid/Classic columns show each engine's "
                 "Elo rating per time control") \
            .classes("text-xs text-gray-500")

        with ui.row().classes("gap-2 flex-wrap"):
            for threshold, label, color in RANK_TIERS:
                txt = f"{label} ≥{threshold}" if threshold > 0 else label
                ui.label(txt).classes("text-xs").style(f"color: {color}")

        search = widgets.search_input("Filter engines, tiers or openings…") \
            .classes("w-full")

        columns = [
            {"name": "rank",    "label": "#",     "field": "rank",  "align": "center", "sortable": True},
            {"name": "engine",  "label": "Engine", "field": "engine", "align": "left",  "sortable": True},
            {"name": "elo",     "label": "Elo",   "field": "elo",   "align": "center", "sortable": True},
            {"name": "tier",    "label": "Tier",  "field": "tier",  "align": "left"},
            {"name": "matches", "label": "Games", "field": "matches", "align": "center", "sortable": True},
            {"name": "wins",    "label": "W",     "field": "wins",  "align": "center"},
            {"name": "draws",   "label": "D",     "field": "draws", "align": "center"},
            {"name": "loses",   "label": "L",     "field": "loses", "align": "center"},
            {"name": "wr",      "label": "WR%",   "field": "wr",    "align": "center", "sortable": True},
            {"name": "bullet",  "label": "Bullet", "field": "bullet", "align": "center"},
            {"name": "blitz",   "label": "Blitz",  "field": "blitz",  "align": "center"},
            {"name": "rapid",   "label": "Rapid",  "field": "rapid",  "align": "center"},
            {"name": "classic", "label": "Classic", "field": "classic", "align": "center"},
            {"name": "top_opening", "label": "Top Opening",
             "field": "top_opening", "align": "left", "sortable": True},
            {"name": "actions", "label": "History", "field": "engine",
             "align": "center"},
        ]
        table = ui.table(columns=columns, rows=[], row_key="engine",
                         pagination=20).classes("w-full flex-grow arena-log")
        table.add_slot("body-cell-tier", _TIER_CELL_SLOT)
        table.add_slot("body-cell-rank", _RANK_CELL_SLOT)
        table.add_slot("body-cell-actions", """
<q-td :props="props" class="text-center">
  <q-btn dense flat size="sm" icon="history" color="secondary"
         @click="$parent.$emit('games', props.row)">
    <q-tooltip>Game history</q-tooltip>
  </q-btn>
  <q-btn dense flat size="sm" icon="show_chart" color="primary"
         @click="$parent.$emit('elo', props.row)">
    <q-tooltip>Elo history</q-tooltip>
  </q-btn>
</q-td>
""")

        def refresh():
            ratings, _, _ = session.elo_data()
            stats_map = {s["engine"]: s for s in session.db.get_engine_stats()}
            top_map = session.db.get_top_openings()
            # Per-time-control Elo: bucket games by TC prefix and run an
            # independent Elo computation over each bucket.
            tc_games = {}
            for white, black, result, tc in session.db.get_all_games_for_elo_tc():
                key = (tc or "Classic").split(" ")[0].split("(")[0].lower()
                tc_games.setdefault(key, []).append((white, black, result))
            tc_ratings = {key: compute_elo_ratings(games)
                          for key, games in tc_games.items()}

            def tc_rating(engine, key):
                elo = tc_ratings.get(key, {}).get(engine)
                return str(elo) if elo is not None else "—"

            rows = []
            ordered = sorted(ratings.items(), key=lambda x: x[1], reverse=True)
            for i, (engine, elo) in enumerate(ordered, 1):
                s = stats_map.get(engine, {})
                tier_lbl, tier_col = get_tier(elo)
                top = top_map.get(engine)
                rows.append({
                    "rank": i, "engine": engine, "elo": elo,
                    "tier": tier_lbl, "tier_col": tier_col,
                    "matches": s.get("matches", 0), "wins": s.get("wins", 0),
                    "draws": s.get("draws", 0), "loses": s.get("loses", 0),
                    "wr": f"{s.get('win_rate', 0.0):.1f}",
                    "bullet":  tc_rating(engine, "bullet"),
                    "blitz":   tc_rating(engine, "blitz"),
                    "rapid":   tc_rating(engine, "rapid"),
                    "classic": tc_rating(engine, "classic"),
                    "top_opening": (f"{top['opening']} ({top['games']}×)"
                                    if top else "—"),
                })
            q = (search.value or "").lower()
            if q:
                rows = [r for r in rows
                        if q in r["engine"].lower() or q in r["tier"].lower()
                        or q in r["top_opening"].lower()]
            table.rows = rows
            table.update()

        search.on_value_change(lambda e: refresh())
        table.on("rowDblclick",
                 lambda e: widgets.with_loader(
                     lambda: show_elo_history(session, e.args[1]["engine"]),
                     "Loading Elo history…"))
        table.on("games",
                 lambda e: widgets.with_loader(
                     lambda: show_game_history(
                         session, filter_engine=e.args["engine"]),
                     "Loading game history…"))
        table.on("elo",
                 lambda e: widgets.with_loader(
                     lambda: show_elo_history(session, e.args["engine"]),
                     "Loading Elo history…"))

        with ui.row().classes("w-full justify-end gap-2 dlg-foot"):
            widgets.icon_button("All Openings", "ic_book", secondary=True,
                                on_click=lambda: show_opening_stats(session))
            widgets.icon_button("Refresh", "ic_refresh", on_click=refresh,
                                secondary=True)
            ui.button("Close", on_click=dialog.close) \
                .props("flat color=grey no-caps")
        refresh()
    dialog.open()


# ═══════════════════════════════════════════════════════════
#  Elo history chart
# ═══════════════════════════════════════════════════════════

def show_elo_history(session, engine_name):
    games = session.db.get_all_games_for_elo()
    history = compute_elo_history(games, engine_name)
    if not history:
        ui.notify(f"No games found for {engine_name}", type="info")
        return

    elos = [e for _, e in history]
    final_elo = elos[-1]
    tier_lbl, tier_col = get_tier(final_elo)

    with ui.dialog() as dialog, ui.card().classes(
            "arena-panel w-[780px] max-w-full"):
        widgets.heading("ic_chart",
                        f"Elo History — {normalize_engine_name(engine_name)}",
                        text_cls="text-lg font-bold text-primary")
        ui.label(f"Current: {final_elo}  ·  {tier_lbl}") \
            .classes("font-bold").style(f"color: {tier_col}")

        ui.echart({
            "backgroundColor": "transparent",
            "grid": {"left": 50, "right": 20, "top": 20, "bottom": 35},
            "tooltip": {"trigger": "axis"},
            "xAxis": {
                "type": "category",
                "data": [g for g, _ in history],
                "name": "Game #",
                "axisLine": {"lineStyle": {"color": "#666"}},
            },
            "yAxis": {
                "type": "value",
                "min": max(0, min(elos) - 50),
                "max": max(elos) + 50,
                "axisLine": {"lineStyle": {"color": "#666"}},
                "splitLine": {"lineStyle": {"color": "#222"}},
            },
            "series": [{
                "type": "line",
                "data": elos,
                "smooth": True,
                "symbolSize": 6,
                "lineStyle": {"color": tier_col, "width": 2},
                "itemStyle": {"color": tier_col},
                "areaStyle": {"opacity": 0.12, "color": tier_col},
            }],
        }).classes("w-full h-[360px]")

        if len(elos) > 1:
            change = elos[-1] - elos[0]
            with ui.row().classes("w-full justify-around"):
                for label, val, col in [
                    ("Peak", str(max(elos)), COLOR_GOLD),
                    ("Lowest", str(min(elos)), "#FF6B6B"),
                    ("Change", f"{change:+d}",
                     "#00FF80" if change >= 0 else COLOR_RED),
                    ("Games", str(len(elos)), "#EAEAEA"),
                ]:
                    with ui.column().classes("items-center gap-0"):
                        ui.label(label).classes("text-xs text-gray-500")
                        ui.label(val).classes("text-lg font-bold") \
                            .style(f"color: {col}")

        ui.button("Close", on_click=dialog.close) \
            .props("flat color=grey no-caps").classes("self-end dlg-foot")
    dialog.open()


# ═══════════════════════════════════════════════════════════
#  Opening statistics
# ═══════════════════════════════════════════════════════════

def show_opening_stats(session, engine_name=None):
    if engine_name:
        data = session.db.get_opening_stats(engine_name)
        title = f"Opening Stats — {normalize_engine_name(engine_name)}"
    else:
        data = session.db.get_opening_stats_all()
        title = "Opening Stats — All Engines"

    columns = [
        {"name": "opening", "label": "Opening", "field": "opening",
         "align": "left", "sortable": True},
        {"name": "games",   "label": "Games",   "field": "games",
         "align": "center", "sortable": True},
        {"name": "wins",    "label": "W",       "field": "wins",  "align": "center"},
        {"name": "draws",   "label": "D",       "field": "draws", "align": "center"},
        {"name": "losses",  "label": "L",       "field": "losses", "align": "center"},
        {"name": "wr",      "label": "WR%",     "field": "wr",
         "align": "center", "sortable": True},
        {"name": "bar",     "label": "",        "field": "bar", "align": "left",
         "classes": "mono"},
    ]

    def rows_for(rows):
        max_games = rows[0]["games"] if rows else 1
        out = []
        for r in rows:
            filled = int(r["games"] / max_games * 20) if max_games else 0
            out.append({**r, "wr": f"{r['win_rate']:.1f}",
                        "bar": "█" * filled + "░" * (20 - filled)})
        return out

    with ui.dialog() as dialog, ui.card().classes(
            "arena-panel w-[940px] max-w-full h-[640px] flex flex-col"):
        widgets.heading("ic_book", title)
        with ui.tabs().classes("w-full") as tabs:
            tab_w = ui.tab("As White")
            tab_b = ui.tab("As Black")
        with ui.tab_panels(tabs, value=tab_w).classes("w-full flex-grow"):
            for tab, key in [(tab_w, "as_white"), (tab_b, "as_black")]:
                with ui.tab_panel(tab):
                    rows = data.get(key, [])
                    if rows:
                        ui.table(columns=columns, rows=rows_for(rows),
                                 row_key="opening", pagination=12) \
                            .classes("w-full arena-log")
                    else:
                        ui.label("No games recorded yet.") \
                            .classes("text-gray-500 p-8")
        ui.button("Close", on_click=dialog.close) \
            .props("flat color=grey no-caps").classes("self-end dlg-foot")
    dialog.open()


# ═══════════════════════════════════════════════════════════
#  Game history
# ═══════════════════════════════════════════════════════════

_RESULT_CELL_SLOT = """
<q-td :props="props">
  <span :style="{color: props.row.result_col}">{{ props.value }}</span>
</q-td>
"""


def show_game_history(session, filter_engine=None):
    norm_filter = normalize_engine_name(filter_engine) if filter_engine else None

    with ui.dialog() as dialog, ui.card().classes(
            "arena-panel w-[1060px] max-w-full h-[680px] flex flex-col"):
        with ui.row().classes("w-full items-center"):
            widgets.heading("ic_calendar", "GAME HISTORY")
            if norm_filter:
                ui.label(f"· {norm_filter}").style(f"color: {COLOR_GOLD}")
                ui.button("Clear filter",
                          on_click=lambda: (dialog.close(),
                                            show_game_history(session))) \
                    .props("dense color=secondary no-caps")

        with ui.row().classes("w-full items-center gap-4"):
            source = ui.radio(
                {"all": "All", "regular": "Regular", "tournament": "Tournament"},
                value="all").props("inline dense")
            search = widgets.search_input(
                "Search engine, result, reason, date…").classes("flex-grow")

        columns = [
            {"name": "id",     "label": "ID",     "field": "id",     "align": "center", "sortable": True},
            {"name": "date",   "label": "Date",   "field": "date",   "align": "center"},
            {"name": "time",   "label": "Time",   "field": "time",   "align": "center"},
            {"name": "white",  "label": "White",  "field": "white",  "align": "left"},
            {"name": "black",  "label": "Black",  "field": "black",  "align": "left"},
            {"name": "result", "label": "Result", "field": "result", "align": "center"},
            {"name": "tc",     "label": "Time Control", "field": "tc", "align": "center", "sortable": True},
            {"name": "reason", "label": "Reason", "field": "reason", "align": "left"},
            {"name": "moves",  "label": "Moves",  "field": "moves",  "align": "center"},
            {"name": "dur",    "label": "Duration", "field": "dur",  "align": "center"},
        ]
        table = ui.table(columns=columns, rows=[], row_key="id",
                         pagination=15).classes("w-full flex-grow arena-log")
        table.add_slot("body-cell-result", _RESULT_CELL_SLOT)

        games_cache = []
        MAX_ROWS = 300   # SQL LIMIT — huge databases never flood the query

        def refresh():
            nonlocal games_cache
            src = source.value if source.value != "all" else None
            games_cache = session.db.get_all_games(
                filter_engine=filter_engine,
                search_query=search.value or "",
                source_filter=src,
                limit=MAX_ROWS)
            total = session.db.count_games(
                filter_engine=filter_engine,
                search_query=search.value or "",
                source_filter=src)
            count_lbl.set_text(
                f"Showing latest {len(games_cache)} of {total} — "
                f"use search to narrow" if total > len(games_cache)
                else f"{len(games_cache)} game(s)")
            rows = []
            for g in games_cache:
                gid, white, black, result, reason, date, time_str, moves, dur = g[:9]
                src_tag = g[9] if len(g) > 9 else "regular"
                tc = g[10] if len(g) > 10 else ""
                if result == "1/2-1/2":
                    col = COLOR_BLUE
                elif result == "1-0":
                    col = (COLOR_RED if norm_filter and
                           normalize_engine_name(black) == norm_filter
                           else COLOR_GOLD)
                elif result == "0-1":
                    col = (COLOR_RED if norm_filter and
                           normalize_engine_name(white) == norm_filter
                           else COLOR_SILVER)
                else:
                    col = "#888"
                rows.append({
                    "id": gid, "date": date, "time": time_str,
                    "white": white, "black": black,
                    "result": result, "result_col": col,
                    "tc": tc or "—",
                    "reason": ("[T] " if src_tag == "tournament" else "") + (reason or ""),
                    "moves": moves or 0,
                    "dur": f"{dur // 60}m {dur % 60}s" if dur else "—",
                })
            table.rows = rows
            table.update()

        source.on_value_change(lambda e: refresh())
        search.on_value_change(lambda e: refresh())
        table.on("rowDblclick",
                 lambda e: widgets.with_loader(
                     lambda: show_pgn_viewer(session, e.args[1]["id"],
                                             games_cache),
                     "Loading game replay…"))

        with ui.row().classes("w-full items-center"):
            widgets.hint("Double-click a row to replay the game · "
                         "[T] = tournament game")
            ui.space()
            count_lbl = ui.label("").classes("text-xs text-gray-500")
        with ui.row().classes("w-full justify-end gap-2 dlg-foot"):
            widgets.icon_button("Refresh", "ic_refresh", on_click=refresh,
                                secondary=True)
            ui.button("Close", on_click=dialog.close) \
                .props("flat color=grey no-caps")
        refresh()
    dialog.open()


# ═══════════════════════════════════════════════════════════
#  PGN replay viewer
# ═══════════════════════════════════════════════════════════

def parse_pgn_moves(pgn):
    """Extract UCI moves from a PGN text using the Board SAN builder."""
    body_lines = [l.strip() for l in pgn.split("\n")
                  if l.strip() and not l.strip().startswith("[")]
    text = " ".join(body_lines)
    for tok in ["1-0", "0-1", "1/2-1/2", "*"]:
        text = text.replace(tok, "")
    text = re.sub(r"\d+\.", "", text)

    board = Board()
    uci_moves = []
    for san in text.split():
        try:
            legal = board.legal_moves()
            for fr, fc, tr, tc, promo in legal:
                test = board._build_san(fr, fc, tr, tc, promo, legal)
                if (test.replace("+", "").replace("#", "")
                        == san.replace("+", "").replace("#", "")):
                    uci = f"{chr(ord('a') + fc)}{8 - fr}{chr(ord('a') + tc)}{8 - tr}"
                    if promo:
                        uci += promo
                    uci_moves.append(uci)
                    board.apply_uci(uci)
                    break
        except Exception as e:
            print(f"[parse_pgn_moves] error on {san}: {e}")
    return uci_moves


def show_pgn_viewer(session, game_id, all_games=None):
    pgn = session.db.get_game_pgn(game_id)
    if not pgn:
        ui.notify("Could not load PGN.", type="negative")
        return

    all_games = all_games or []
    ids = [g[0] for g in all_games]
    idx = ids.index(game_id) if game_id in ids else None

    moves = parse_pgn_moves(pgn)
    replay = Board()
    pos = {"i": 0}

    def state():
        last = moves[pos["i"] - 1] if pos["i"] > 0 else None
        return {"board": replay, "last_move": last,
                "selected": None, "legal_dests": set(), "check_sq": None}

    def goto(i):
        i = max(0, min(len(moves), i))
        replay.reset()
        for m in moves[:i]:
            try:
                replay.apply_uci(m)
            except Exception:
                break
        pos["i"] = i
        board_view.refresh()
        update_label()
        asyncio.create_task(analyze_current())

    with ui.dialog() as dialog, ui.card().classes(
            "arena-panel w-[1000px] max-w-full h-[720px] flex flex-col"):
        header = re.search(r'\[White\s+"([^"]+)"\]', pgn)
        white = header.group(1) if header else "?"
        header = re.search(r'\[Black\s+"([^"]+)"\]', pgn)
        black = header.group(1) if header else "?"
        header = re.search(r'\[Result\s+"([^"]+)"\]', pgn)
        result = header.group(1) if header else "*"

        async def _nav_game(delta):
            dialog.close()
            await widgets.with_loader(
                lambda: show_pgn_viewer(session, ids[idx + delta], all_games),
                "Loading game replay…")

        with ui.row().classes("w-full items-center justify-between"):
            prev_btn = widgets.icon_button(
                "Prev game", "ic_play_rev", secondary=True, dense=True,
                on_click=lambda: _nav_game(-1))
            if idx is None or idx <= 0:
                prev_btn.disable()
            ui.label(f"Game #{game_id}   ·   {white} vs {black}   ·   {result}") \
                .classes("font-bold text-primary")
            next_btn = widgets.icon_button(
                "Next game", "ic_play", secondary=True, dense=True,
                on_click=lambda: _nav_game(1))
            if idx is None or idx >= len(ids) - 1:
                next_btn.disable()

        with ui.row().classes("w-full flex-grow no-wrap gap-4"):
            with ui.column().classes("w-1/2 items-center"):
                with ui.row().classes("w-full no-wrap gap-2 justify-center "
                                      "items-stretch"):
                    with ui.column().classes("gap-0 py-1 self-stretch"):
                        eval_bar = EvalBar()
                    with ui.element("div").classes("flex-grow min-w-0"):
                        board_view = BoardView(state)
                move_label = ui.label("Start position") \
                    .classes("font-bold text-primary")
                with ui.row().classes("items-center gap-3"):
                    eval_lbl = ui.label("").classes("mono text-sm")
                    quality_lbl = ui.label("").classes("font-bold")
                opening_lbl = ui.label("").classes("text-xs italic") \
                    .style(f"color: {COLOR_BLUE}")
                with ui.row().classes("gap-1"):
                    for icon, action, tip in [
                        ("first_page",    lambda: goto(0),            "Start"),
                        ("chevron_left",  lambda: goto(pos["i"] - 1), "Previous move"),
                        ("chevron_right", lambda: goto(pos["i"] + 1), "Next move"),
                        ("last_page",     lambda: goto(len(moves)),   "End"),
                    ]:
                        ui.button(icon=icon, on_click=action) \
                            .props("dense").tooltip(tip)
                widgets.hint("Keys: ← → move · Home/End start/end")
            with ui.column().classes("w-1/2 h-full"):
                ui.label("PGN").classes("arena-heading")
                ui.textarea(value=pgn).props("readonly autogrow") \
                    .classes("w-full flex-grow arena-log mono text-xs")
                with ui.row().classes("gap-2"):
                    widgets.icon_button("Copy PGN", "ic_export", secondary=True,
                                        dense=True, on_click=lambda: (
                                            ui.clipboard.write(pgn),
                                            ui.notify("PGN copied",
                                                      type="positive")))
                    widgets.icon_button("Download PGN", "ic_download",
                                        secondary=True, dense=True,
                                        on_click=lambda: ui.download.content(
                                            pgn, f"game_{game_id}.pgn"))

        def update_label():
            i, total = pos["i"], len(moves)
            if i == 0:
                move_label.set_text("Start position")
            elif i <= total:
                side = "White" if i % 2 == 1 else "Black"
                move_label.set_text(f"Move {(i + 1) // 2}: {side} — {moves[i - 1]}")
            if session.opening_book.loaded:
                eco, name = session.opening_book.lookup(replay.uci_moves_list())
                opening_lbl.set_text(
                    (f"{eco} · {name}" if eco else name) if name else "")

        # ── Analyzer: eval bar + move quality while navigating ─
        evals = {}              # ply index → cp (White POV), cached
        anal_token = {"n": 0}   # drops stale results on fast navigation

        async def analyze_current():
            if not (session.analyzer and session.analyzer.alive):
                eval_lbl.set_text("No analyzer loaded")
                return
            i = pos["i"]
            anal_token["n"] += 1
            tok = anal_token["n"]
            eval_lbl.set_text("Analyzing…")

            # Evaluate previous + current position (quality needs both)
            for j in (i - 1, i):
                if j >= 0 and j not in evals:
                    moves_str = " ".join(moves[:j])
                    async with session._analyzer_alock:
                        res = await run.io_bound(
                            session.analyzer.eval_position, moves_str, 200)
                    if res and res[0] is not None:
                        evals[j] = res[0]
            if tok != anal_token["n"]:
                return          # user already navigated elsewhere

            cp = evals.get(i)
            if cp is None:
                eval_lbl.set_text("—")
                return
            eval_bar.set_cp(cp)
            eval_lbl.set_text(f"Eval: {cp / 100:+.2f}")

            if i == 0:
                quality_lbl.set_text("")
            elif (session.opening_book.loaded and
                    session.opening_book.in_book(replay.uci_moves_list())):
                quality_lbl.set_text("Book")
                quality_lbl.style(f"color: {QUALITY_COLORS.get('Book', '#EAEAEA')}")
            elif (i - 1) in evals:
                was_white = (i % 2 == 1)
                q = classify_move_quality(evals[i - 1], cp, was_white)
                quality_lbl.set_text(q or "")
                quality_lbl.style(
                    f"color: {QUALITY_COLORS.get(q, '#EAEAEA')}")
            else:
                quality_lbl.set_text("")

        def on_key(e):
            if not e.action.keydown:
                return
            if e.key.arrow_left:
                goto(pos["i"] - 1)
            elif e.key.arrow_right:
                goto(pos["i"] + 1)
            elif e.key.name == "Home":
                goto(0)
            elif e.key.name == "End":
                goto(len(moves))
        ui.keyboard(on_key=on_key)

        ui.button("Close", on_click=dialog.close) \
            .props("flat color=grey no-caps").classes("self-end dlg-foot")
        update_label()
        asyncio.create_task(analyze_current())
    dialog.open()
