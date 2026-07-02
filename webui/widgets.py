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


def icon(name, size=16, cls=""):
    """Inline sprite icon <img> from /assets/ui/<name>.png."""
    return ui.element("img").props(f'src="/assets/ui/{name}.png"') \
        .style(f"height: {size}px; width: auto;") \
        .classes(f"pointer-events-none {cls}".strip())


def piece(code, size=18):
    """Inline chess-piece sprite, e.g. piece('wK')."""
    return ui.element("img").props(f'src="/assets/pieces/{code}.png"') \
        .style(f"height: {size}px; width: auto;") \
        .classes("pointer-events-none")


def heading(icon_name, text, size=20, text_cls="text-xl font-bold text-primary"):
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
