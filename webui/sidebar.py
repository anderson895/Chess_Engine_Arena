# ═══════════════════════════════════════════════════════════
#  webui/sidebar.py — The navigation down the left edge
#
#  Laid out like chess.com's left bar: the logo on top, one row per
#  screen (a sprite icon and its name), and quieter rows for settings at
#  the bottom.
# ═══════════════════════════════════════════════════════════

from nicegui import ui


class SidebarItem:
    """One row of the sidebar; badges can be placed inside .row."""

    def __init__(self, label, icon_name, on_click=None, tooltip=None,
                 current=False):
        with ui.element("div").classes("side-item") as row:
            self.row = row
            ui.element("img").props(f'src="/assets/ui/{icon_name}.png"')
            self.label = ui.label(label)
        if current:
            row.classes(add="current")
        if on_click:
            row.on("click", on_click)
        if tooltip:
            row.tooltip(tooltip)

    def set_text(self, text):
        self.label.set_text(text)


class Sidebar:
    """The page's left drawer: logo, screens, and settings at the foot."""

    def __init__(self, title, logo="/assets/pieces/wN.png", width=180):
        # breakpoint 0: always docked, never an overlay on narrow windows
        self.drawer = ui.left_drawer(value=True, fixed=True, bordered=False) \
            .props(f":width={width} :breakpoint=0").classes("p-0")
        with self.drawer:
            with ui.column().classes("w-full h-full gap-0 no-wrap"):
                with ui.element("div").classes("side-logo"):
                    ui.element("img").props(f'src="{logo}"')
                    ui.label(title)
                self._main = ui.column().classes("w-full gap-0")
                ui.space()
                self._foot = ui.column().classes("side-foot w-full gap-0 pb-3")

    def item(self, label, icon_name, on_click=None, *, tooltip=None,
             current=False, footer=False):
        """Add a row (to the foot with *footer*) and return it."""
        with self._foot if footer else self._main:
            return SidebarItem(label, icon_name, on_click, tooltip, current)
