# ═══════════════════════════════════════════════════════════
#  webui/dialogs.py — Modal dialogs (promotion, stop, openings,
#  game over)
# ═══════════════════════════════════════════════════════════

import random

from nicegui import ui

from core.utils import normalize_engine_name, get_tier
from core.constants import QUALITY_COLORS
from webui import widgets
from webui.theme import COLOR_BLUE, piece_src


# ═══════════════════════════════════════════════════════════
#  Promotion picker
# ═══════════════════════════════════════════════════════════

async def ask_promotion(color):
    """Modal piece picker. Returns 'q' / 'r' / 'b' / 'n' (default 'q')."""
    pieces = [("q", "Queen"), ("r", "Rook"), ("b", "Bishop"), ("n", "Knight")]
    with ui.dialog() as dialog, ui.card().classes("arena-panel items-center"):
        ui.label("Choose promotion piece").classes("text-lg font-bold")
        with ui.row():
            for p, name in pieces:
                with ui.column().classes("items-center"):
                    with ui.button(on_click=lambda p=p: dialog.submit(p)) \
                            .props("flat"):
                        ui.element("img").props(
                            f'src="{piece_src(color + p.upper())}"') \
                            .style("height: 56px; width: auto;")
                    ui.label(name).classes("text-xs text-gray-500")
    result = await dialog
    return result or "q"


# ═══════════════════════════════════════════════════════════
#  Stop-game result dialog
# ═══════════════════════════════════════════════════════════

REASON_OPTIONS = {
    "1-0":     ["White wins", "White wins on time", "Black resigned",
                "Black forfeits", "Illegal move by Black"],
    "0-1":     ["Black wins", "Black wins on time", "White resigned",
                "White forfeits", "Illegal move by White"],
    "1/2-1/2": ["Draw by agreement", "Stalemate", "Draw by repetition",
                "Draw by 50-move rule", "Draw by insufficient material"],
    "*":       ["Game aborted", "No result", "Stopped by user"],
}


async def ask_stop_result(white_name, black_name):
    """
    Let the user pick the result before stopping a game.

    Returns (result, reason) or (None, None) when cancelled.
    """
    state = {"result": None}

    with ui.dialog() as dialog, ui.card().classes("arena-panel w-[480px]"):
        widgets.heading("ic_stop", "STOP GAME")
        ui.label("Select the result to record before stopping:") \
            .classes("text-sm")

        reason_select = None
        result_buttons = {}

        def pick(res):
            state["result"] = res
            for r, btn in result_buttons.items():
                btn.props(f"color={'primary' if r == res else 'secondary'}")
            opts = REASON_OPTIONS.get(res, ["Stopped by user"])
            reason_select.set_options(opts, value=opts[0])
            reason_select.enable()
            confirm_btn.enable()

        entries = [
            ("1-0",     f"{normalize_engine_name(white_name)} wins (White)"),
            ("0-1",     f"{normalize_engine_name(black_name)} wins (Black)"),
            ("1/2-1/2", "Draw (½–½)"),
            ("*",       "No result / Abort"),
        ]
        with ui.column().classes("w-full gap-1"):
            for res, label in entries:
                b = ui.button(label, on_click=lambda r=res: pick(r)) \
                    .props("color=secondary align=left no-caps") \
                    .classes("w-full")
                result_buttons[res] = b

        reason_select = ui.select([], label="Reason").classes("w-full")
        reason_select.disable()

        with ui.row().classes("w-full justify-end gap-2 mt-2 dlg-foot"):
            ui.button("Cancel", on_click=lambda: dialog.submit(None)) \
                .props("color=secondary no-caps")
            confirm_btn = ui.button(
                "Confirm & Stop",
                on_click=lambda: dialog.submit(
                    (state["result"], reason_select.value or "Stopped by user")))
            confirm_btn.props("no-caps")
            confirm_btn.disable()

    result = await dialog
    if not result:
        return None, None
    return result


# ═══════════════════════════════════════════════════════════
#  Opening picker
# ═══════════════════════════════════════════════════════════

async def ask_opening_choice(opening_book):
    """
    Pick a starting opening from the book.

    Returns (uci_moves, name):
      (list, str)  — chosen opening
      ([], None)   — explicit normal start
      (None, None) — cancelled
    """
    all_entries = []
    seen = set()
    for seq, eco, name in opening_book._entries:
        key = (eco, name)
        if key not in seen:
            seen.add(key)
            all_entries.append((eco, name, list(seq)))
    all_entries.sort(key=lambda x: x[1])

    state = {"eco": None, "query": ""}

    with ui.dialog() as dialog, \
            ui.card().classes("arena-panel w-[820px] max-w-full h-[640px]"):
        widgets.heading("ic_book", "CHOOSE STARTING OPENING",
                        text_cls="text-lg font-bold text-primary")
        ui.label(f"{len(all_entries)} openings — the game will start "
                 "from the selected line").classes("text-xs text-gray-500")

        # ECO filter chips + search
        with ui.row().classes("w-full items-center gap-1"):
            ui.label("ECO:").classes("text-xs text-gray-500")
            chip_buttons = {}

            def set_eco(letter):
                state["eco"] = letter
                for l, b in chip_buttons.items():
                    b.props(f"color={'primary' if l == letter else 'secondary'}")
                update_rows()

            for letter in [None, "A", "B", "C", "D", "E"]:
                b = ui.button(letter or "All",
                              on_click=lambda l=letter: set_eco(l)) \
                    .props(f"dense color="
                           f"{'primary' if letter is None else 'secondary'}")
                chip_buttons[letter] = b
            search = widgets.search_input("Search openings…") \
                .classes("flex-grow")

        columns = [
            {"name": "eco",   "label": "ECO",   "field": "eco",
             "align": "center", "style": "width: 70px"},
            {"name": "name",  "label": "Name",  "field": "name",
             "align": "left", "sortable": True},
            {"name": "moves", "label": "Moves", "field": "moves",
             "align": "left"},
        ]
        table = ui.table(columns=columns, rows=[], row_key="idx",
                         selection="single", pagination=25) \
            .classes("w-full flex-grow arena-log")
        count_lbl = ui.label("").classes("text-xs text-gray-500")

        def visible_entries():
            q = (state["query"] or "").strip().lower()
            out = []
            for i, (eco, name, seq) in enumerate(all_entries):
                if state["eco"] and not eco.startswith(state["eco"]):
                    continue
                if q and q not in name.lower() and q not in eco.lower():
                    continue
                out.append((i, eco, name, seq))
            return out

        MAX_ROWS = 200   # keep the websocket payload small

        def update_rows():
            vis = visible_entries()
            rows = []
            for idx, eco, name, seq in vis[:MAX_ROWS]:
                preview = " ".join(seq[:6]) + ("…" if len(seq) > 6 else "")
                rows.append({"idx": idx, "eco": eco, "name": name,
                             "moves": preview})
            table.rows = rows
            table.selected = []
            table.update()
            if len(vis) > MAX_ROWS:
                count_lbl.set_text(
                    f"Showing {MAX_ROWS} of {len(vis)} — type to narrow down")
            else:
                count_lbl.set_text(f"{len(vis)} openings shown")

        def on_search(e):
            state["query"] = e.value or ""
            update_rows()
        search.on_value_change(on_search)

        def chosen_entry():
            if not table.selected:
                return None
            idx = table.selected[0]["idx"]
            return all_entries[idx]

        def confirm():
            entry = chosen_entry()
            if not entry:
                ui.notify("Select an opening first.", type="warning")
                return
            eco, name, seq = entry
            dialog.submit((seq, f"{eco} · {name}" if eco else name))

        def pick_random():
            eco, name, seq = random.choice(all_entries)
            dialog.submit((seq, f"{eco} · {name}" if eco else name))

        table.on("rowDblclick", lambda e: (
            table.__setattr__("selected", [e.args[1]]), confirm()))

        with ui.row().classes("w-full justify-between mt-1 dlg-foot"):
            with ui.row().classes("gap-2"):
                widgets.icon_button("Use this opening", "ic_flag",
                                    on_click=confirm)
                ui.button("Random", on_click=pick_random) \
                    .props("color=secondary no-caps")
                ui.button("Normal start",
                          on_click=lambda: dialog.submit(([], None))) \
                    .props("color=secondary no-caps")
            ui.button("Cancel", on_click=lambda: dialog.submit(None)) \
                .props("flat color=grey no-caps")

        update_rows()

    result = await dialog
    if result is None:
        return None, None
    return result


# ═══════════════════════════════════════════════════════════
#  Game-over dialog
# ═══════════════════════════════════════════════════════════

def show_game_over(session, result, reason, winner_name,
                   on_new_game=None, on_rankings=None, on_export=None):
    """Non-blocking game-over dialog with summary and quick actions."""
    is_draw = result == "1/2-1/2"
    if not winner_name or is_draw:
        badge, title = "/assets/ui/badge_swords.png", "DRAW"
        winner_name = None
    else:
        badge, title = "/assets/ui/badge_crown.png", "VICTORY!"

    with ui.dialog() as dialog, \
            ui.card().classes("arena-panel items-center w-[440px]"):
        ui.element("img").props(f'src="{badge}"') \
            .style("height: 72px; width: auto;")
        ui.label(title).classes("text-3xl font-bold text-primary")

        if winner_name:
            clean = normalize_engine_name(winner_name)
            ratings, _, _ = session.elo_data()
            elo = ratings.get(clean)
            ui.label(clean).classes("text-xl font-bold")
            if elo:
                tier_lbl, tier_col = get_tier(elo)
                ui.label(f"Elo: {elo}  ·  {tier_lbl}") \
                    .style(f"color: {tier_col}")

        ui.separator()
        ui.label(f"Result: {result}").classes("text-sm text-gray-400")
        ui.label(reason).classes("text-sm text-gray-500")
        if session.current_opening_name:
            ui.label(session.current_opening_name) \
                .classes("text-xs italic").style(f"color: {COLOR_BLUE}")

        # Move-quality summary (skip Book/Good noise)
        counts = {}
        for _, _, q in session.move_qualities:
            counts[q] = counts.get(q, 0) + 1
        order = list(QUALITY_COLORS.keys())
        summary = "  ".join(
            f"{q}: {n}" for q, n in sorted(
                counts.items(),
                key=lambda x: order.index(x[0]) if x[0] in order else 99)
            if q not in ("Good", "Book"))
        if summary:
            ui.label(f"Move quality: {summary}").classes("text-xs text-gray-400")

        ui.label("⇄ Colors swapped for the next game") \
            .classes("text-xs italic").style(f"color: {COLOR_BLUE}")

        with ui.row().classes("w-full justify-center gap-2 mt-2"):
            if on_new_game:
                ui.button("New Game",
                          on_click=lambda: (dialog.close(), on_new_game()))
            if on_rankings:
                widgets.icon_button("Rankings", "ic_trophy", secondary=True,
                                    on_click=lambda: (dialog.close(),
                                                      on_rankings()))
            if on_export:
                ui.button("Export PGN",
                          on_click=lambda: (dialog.close(), on_export())) \
                    .props("color=secondary")
            ui.button("Close", on_click=dialog.close).props("flat color=grey")
    dialog.open()
