# ═══════════════════════════════════════════════════════════
#  webui/widgets.py — Shared sprite-icon widget helpers
#
#  All icons come from assets/ui/*.png (sliced from Chess_packs.png)
#  so the UI never depends on emoji rendering.
# ═══════════════════════════════════════════════════════════

import asyncio
import inspect

from nicegui import ui


async def with_loader(builder, message="Loading…"):
    """
    Show a spinner overlay while *builder* constructs a slow dialog/view.

    The overlay is flushed to the client before the (possibly blocking)
    build runs, so the user immediately sees that something is processing.
    """
    overlay = ui.dialog().props("persistent")
    with overlay, ui.card().classes("arena-panel items-center gap-3 p-6"):
        ui.spinner(size="44px", color="primary")
        ui.label(message).classes("text-sm text-gray-400")
    overlay.open()
    try:
        await asyncio.sleep(0.06)   # let the spinner reach the browser first
        result = builder()
        if inspect.isawaitable(result):
            result = await result
        return result
    finally:
        overlay.close()


class PlayerBar:
    """
    A player's row above or below a board, as on chess.com: avatar, name,
    rating, head-to-head record and material lead on the left, the clock
    on the right. The main board, the tournament window and the Game
    Review all use it.
    """

    def __init__(self):
        with ui.row().classes("player-bar w-full no-wrap items-center") as row:
            self.row = row
            self.avatar = ui.element("div").classes("pb-avatar")
            with self.avatar:
                self.img = ui.element("img")
            with ui.column().classes("gap-0 min-w-0"):
                with ui.row().classes("items-baseline gap-2 no-wrap"):
                    self.name = ui.label("").classes("pb-name ellipsis")
                    self.rating = ui.label("").classes("pb-rating")
                with ui.row().classes("items-center gap-2 no-wrap"):
                    self.material = ui.label("").classes("pb-material")
                    # Our own W/D/L markup (h2h_html), never typed text
                    self.h2h = ui.html("", sanitize=False).classes("pb-h2h")
            self.clock = ui.label("").classes("pb-clock")
            self.clock.set_visibility(False)
        self._src = None

    def show(self, side, name, rating="", rating_color=None, h2h="",
             winner=False):
        """
        Who sits here: *side* 'w' or 'b' (the avatar's king), the name, a
        rating line in *rating_color*, head-to-head HTML (h2h_html), and
        whether they won the game shown.
        """
        from webui.theme import piece_src
        src = piece_src(side + "K")
        if src != self._src:
            self.img.props(f'src="{src}"')
            self._src = src
        self.name.set_text(name)
        self.rating.set_text(rating)
        self.rating.style(replace=f"color: {rating_color}" if rating_color else "")
        self.h2h.set_content(h2h)
        if winner:
            self.avatar.classes(add="winner")
        else:
            self.avatar.classes(remove="winner")

    def set_material(self, lead):
        """Material ahead of the opponent, in pawns ('+2'), or nothing."""
        self.material.set_text(f"+{lead}" if lead > 0 else "")

    def set_clock(self, text, low=False):
        """The clock; an empty *text* hides it (a clockless game)."""
        self.clock.set_visibility(bool(text))
        self.clock.set_text(text)
        if low:
            self.clock.classes(add="low")
        else:
            self.clock.classes(remove="low")

    def set_active(self, active):
        """Light up the clock of the side to move."""
        if active:
            self.row.classes(add="active")
        else:
            self.row.classes(remove="active")


def h2h_html(wins, draws, losses):
    """Colored 'xW xD xL' head-to-head record, '' when never matched."""
    from webui.theme import COLOR_GREEN, COLOR_MUTED, COLOR_RED
    if wins + draws + losses == 0:
        return ""
    return (f'<span style="color:{COLOR_GREEN}">{wins}W</span> '
            f'<span style="color:{COLOR_MUTED}">{draws}D</span> '
            f'<span style="color:{COLOR_RED}">{losses}L</span>')


class PanelTabs:
    """
    Tabs across the top of a panel, as on chess.com: a sprite icon over
    each label. Every tab owns a column that shows while the tab is
    picked; all of them stay built, so a hidden one can still be updated.

    tabs: [(key, label, icon_name)], the first one picked at the start.
    """

    def __init__(self, tabs):
        self._heads = {}
        self._pages = {}
        with ui.element("div").classes("panel-tabs w-full"):
            for key, label, icon_name in tabs:
                with ui.element("div").classes("panel-tab") as head:
                    ui.element("img").props(f'src="/assets/ui/{icon_name}.png"')
                    ui.label(label)
                head.on("click", lambda k=key: self.select(k))
                self._heads[key] = head
        for key, _, _ in tabs:
            self._pages[key] = ui.column().classes(
                "w-full flex-grow min-h-0 gap-0 no-wrap")
        self.current = None
        self.select(tabs[0][0])

    def page(self, key):
        """The column a tab shows — build its content inside it."""
        return self._pages[key]

    def select(self, key):
        if key == self.current:
            return
        self.current = key
        for k, head in self._heads.items():
            if k == key:
                head.classes(add="active")
            else:
                head.classes(remove="active")
            self._pages[k].set_visibility(k == key)


def icon(name, size=16, cls=""):
    """Inline sprite icon <img> from /assets/ui/<name>.png."""
    return ui.element("img").props(f'src="/assets/ui/{name}.png"') \
        .style(f"height: {size}px; width: auto;") \
        .classes(f"pointer-events-none {cls}".strip())


def piece(code, size=18):
    """Inline chess-piece sprite in the active design, e.g. piece('wK')."""
    from webui.theme import piece_src
    return ui.element("img").props(f'src="{piece_src(code)}"') \
        .style(f"height: {size}px; width: auto;") \
        .classes("pointer-events-none")


def heading(icon_name, text, size=20, text_cls="text-xl font-bold arena-title"):
    """Dialog/section heading: sprite icon + label in a row."""
    with ui.row().classes("items-center gap-2 no-wrap"):
        icon(icon_name, size)
        lbl = ui.label(text).classes(text_cls)
    return lbl


def hint(text):
    """Small info hint line with the info icon."""
    with ui.row().classes("items-center gap-1 no-wrap"):
        icon("ic_info", 13)
        lbl = ui.label(text).classes("text-xs text-gray-500")
    return lbl


def icon_button(text, icon_name=None, on_click=None,
                secondary=False, flat=False, dense=False, classes=""):
    """Button with an optional sprite icon before the label."""
    btn = ui.button(on_click=on_click)
    props = []
    if flat:
        props.append("flat color=grey")
    elif secondary:
        props.append("color=secondary")
    if dense:
        props.append("dense")
    props.append("no-caps")
    btn.props(" ".join(props))
    if classes:
        btn.classes(classes)
    with btn:
        with ui.row().classes("items-center justify-center gap-2 no-wrap"):
            if icon_name:
                icon(icon_name, 15)
            ui.label(text).classes("text-sm font-medium")
    return btn


def search_input(placeholder="Search…", **kwargs):
    """Input with a sprite search icon; debounced so each keystroke
    doesn't trigger a full re-query."""
    inp = ui.input(placeholder=placeholder, **kwargs) \
        .props("dense clearable debounce=400")
    with inp.add_slot("prepend"):
        icon("ic_search", 15)
    return inp
