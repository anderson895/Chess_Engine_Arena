# ═══════════════════════════════════════════════════════════
#  webui/theme.py — Shared colors, CSS and Quasar dark theme
#
#  The web UI follows chess.com's dark look: warm greys, white text and
#  one green for the main action. core.constants keeps the old arena
#  colours, which the legacy Tk windows still read.
# ═══════════════════════════════════════════════════════════

from nicegui import ui

from core.constants import LIGHT_SQ, DARK_SQ
from webui.quality import icon_css, tint_css

# ── Palette ───────────────────────────────────────────────
BG_PAGE      = "#312E2B"     # page
BG_PANEL     = "#262522"     # panels, cards, dialogs
BG_HEAD      = "#21201D"     # sidebar, panel headers, inactive tabs
BG_RAISED    = "#3C3A37"     # secondary buttons, inputs, hovered rows
BG_LOG       = "#1F1E1B"     # logs and wells
TEXT_1       = "#FFFFFF"
TEXT_2       = "#BDBAB7"
TEXT_3       = "#989795"
GREEN        = "#81B64C"     # the main action
GREEN_HOVER  = "#A3D160"
GREEN_SHADOW = "#45753C"

# Semantic aliases used across the web UI
COLOR_MUTED   = TEXT_3
COLOR_FAINT   = "#5D5B57"
COLOR_GOLD    = "#FFD700"    # medals and podiums
COLOR_SILVER  = "#C8C8C8"
COLOR_BLUE    = TEXT_2       # secondary information (openings, status)
COLOR_GREEN   = GREEN
COLOR_ORANGE  = "#FFA459"
COLOR_RED     = "#FA412D"

FONT_STACK = ('"Segoe UI", system-ui, -apple-system, Roboto, Helvetica, '
              'Arial, sans-serif')

# ── Selectable piece designs (folder under assets/ → label) ──
PIECE_SETS = {
    "pieces":   "Classic",
    "pieces_1": "Golden Oak",
    "pieces_2": "Fantasy",
    "pieces_3": "Marble",
}
_piece_state = {"folder": "pieces"}


def piece_folder():
    return _piece_state["folder"]


def set_piece_folder(folder):
    if folder in PIECE_SETS:
        _piece_state["folder"] = folder


def piece_src(code):
    """URL of a piece sprite in the active design, e.g. piece_src('wK')."""
    return f"/assets/{piece_folder()}/{code}.png"


# ── Selectable board styles (key → label, light sq, dark sq) ─
BOARD_THEMES = {
    "green":   ("Green",   "#EBECD0", "#739552"),    # default, as on chess.com
    "walnut":  ("Walnut",  LIGHT_SQ,  DARK_SQ),
    "blue":    ("Blue",    "#DEE3E6", "#8CA2AD"),
    "slate":   ("Slate",   "#CACDD1", "#5F6B77"),
    "coral":   ("Coral",   "#F1E9DD", "#B37360"),
    "midnight": ("Midnight", "#7A8494", "#3D4757"),
}
_board_state = {"theme": "green"}


def board_theme():
    return _board_state["theme"]


def set_board_theme(key):
    if key in BOARD_THEMES:
        _board_state["theme"] = key


def board_colors():
    _, light, dark = BOARD_THEMES[_board_state["theme"]]
    return light, dark


GLOBAL_CSS = f"""
:root {{
    --bg: {BG_PAGE};
    --panel: {BG_PANEL};
    --head: {BG_HEAD};
    --raised: {BG_RAISED};
    --raised-hover: #4B4847;
    --line: #3C3A37;
    --log: {BG_LOG};
    --text: {TEXT_1};
    --text-2: {TEXT_2};
    --text-3: {TEXT_3};
    --green: {GREEN};
    --green-hover: {GREEN_HOVER};
    --green-shadow: {GREEN_SHADOW};
    --font: {FONT_STACK};
    --light-sq: {BOARD_THEMES["green"][1]};
    --dark-sq: {BOARD_THEMES["green"][2]};
}}
body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
}}
::-webkit-scrollbar {{ width: 8px; height: 8px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: var(--raised-hover); border-radius: 4px; }}

.arena-panel {{
    background: var(--panel);
    border: none;
    border-radius: 8px;
}}
.arena-heading {{
    color: var(--text);
    font-weight: 800;
    letter-spacing: 0.04em;
    font-size: 0.8rem;
}}
.arena-title {{ color: var(--text); }}
.arena-log {{
    background: var(--log);
    border: none;
    border-radius: 6px;
    font-family: Consolas, monospace;
    font-size: 0.8rem;
}}
.mono {{ font-family: Consolas, monospace; }}
.q-separator {{ background: var(--line); }}
/* Tailwind's greys are cool blue-greys; these follow the warm palette.
   Unlayered rules win over Tailwind's utilities layer. */
.text-gray-300, .text-gray-400 {{ color: var(--text-2); }}
.text-gray-500 {{ color: var(--text-3); }}
.text-gray-600 {{ color: #6F6D6A; }}

/* ── Buttons and fields (chess.com: solid, rounded, a ledge below) ── */
.q-btn {{ border-radius: 6px; font-weight: 700; }}
.q-btn.bg-primary:not(.q-btn--flat):not(.q-btn--outline) {{
    box-shadow: 0 3px 0 var(--green-shadow);
}}
.q-btn.bg-secondary:not(.q-btn--flat):not(.q-btn--outline) {{
    box-shadow: 0 3px 0 #2A2826;
}}
.q-field--filled .q-field__control {{
    background: var(--raised);
    border-radius: 6px;
}}
.q-field--filled .q-field__control:before {{ border-bottom: none; }}
.q-field--filled.q-field--focused .q-field__control {{ background: var(--raised-hover); }}

/* The big green call to action (Start Game, Game Review, Start Review,
   Next). These buttons are made with color=None: a Quasar colour class
   would win over any rule here, since Quasar's !important rules sit in
   a cascade layer. */
.cta {{
    background: var(--green) !important;
    color: #FFF !important;
    font-weight: 800 !important;
    font-size: 1.25rem !important;
    border-radius: 10px !important;
    box-shadow: 0 5px 0 var(--green-shadow) !important;
    padding: 8px 0 !important;
}}
.cta:hover {{ background: var(--green-hover) !important; }}

/* ── Sidebar ──────────────────────────────────────────── */
.q-drawer {{ background: var(--head); }}
.side-logo {{
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 14px 16px 18px;
    color: var(--text);
    font-weight: 800;
    font-size: 1.2rem;
    line-height: 1.1;
}}
.side-logo img {{ height: 34px; width: auto; }}
.side-item {{
    position: relative;
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    padding: 10px 16px;
    color: var(--text);
    font-weight: 700;
    font-size: 1rem;
    cursor: pointer;
}}
.side-item:hover {{ background: rgba(0, 0, 0, 0.25); }}
.side-item.current {{ background: rgba(255, 255, 255, 0.07); }}
.side-item img {{ width: 26px; height: 26px; flex: none; }}
.side-foot .side-item {{ color: var(--text-2); font-size: 0.92rem; }}

/* ── Right-hand panel with tabs ───────────────────────── */
.side-panel {{
    background: var(--panel);
    border-radius: 8px;
    overflow: hidden;
}}
.panel-tabs {{ display: flex; background: var(--head); }}
.panel-tab {{
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    padding: 9px 0 7px;
    color: var(--text-3);
    font-weight: 700;
    font-size: 0.85rem;
    cursor: pointer;
}}
.panel-tab:hover {{ color: var(--text-2); }}
.panel-tab.active {{ color: var(--text); background: var(--panel); }}
.panel-tab img {{ width: 22px; height: 22px; opacity: 0.6; }}
.panel-tab.active img {{ opacity: 1; }}
.panel-body {{ padding: 12px 14px; }}
.panel-foot {{ padding: 10px 14px 14px; }}
.arena-status {{
    color: var(--text-2);
    font-size: 0.9rem;
    font-weight: 600;
    min-height: 1.4em;
}}

/* ── Player bars ──────────────────────────────────────── */
.player-bar {{ min-height: 46px; gap: 10px; color: var(--text); }}
.pb-avatar {{
    width: 40px;
    height: 40px;
    flex: none;
    border-radius: 4px;
    background: #E8E6E3;
    display: flex;
    align-items: center;
    justify-content: center;
}}
.pb-avatar img {{ width: 34px; height: 34px; }}
.pb-avatar.winner {{ outline: 3px solid var(--green); }}
.pb-name {{ font-weight: 700; font-size: 1rem; }}
.pb-rating {{ font-size: 0.82rem; color: var(--text-3); }}
.pb-material, .pb-h2h {{ font-size: 0.8rem; color: var(--text-3); }}
.pb-clock {{
    margin-left: auto;
    min-width: 116px;
    padding: 3px 12px;
    border-radius: 4px;
    background: #2B2926;
    color: #8B8987;
    text-align: right;
    font: 700 1.55rem/1.25 Consolas, monospace;
}}
.player-bar.active .pb-clock {{ background: #FFFFFF; color: #312E2B; }}
.pb-clock.low {{ background: #C23A2B !important; color: #FFFFFF !important; }}

/* ── Coach bubble (live game and review) ──────────────── */
.coach {{
    display: flex;
    gap: 10px;
    align-items: flex-start;
}}
.coach > img {{ width: 44px; height: 44px; border-radius: 6px; flex: none; }}
.coach-bubble {{
    position: relative;
    flex: 1;
    background: #FFF;
    color: #312E2B;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 0.92rem;
    line-height: 1.35;
    min-height: 44px;
}}
.coach-bubble::before {{
    content: '';
    position: absolute;
    left: -7px;
    top: 15px;
    border: 7px solid transparent;
    border-left: 0;
    border-right-color: #FFF;
}}
.coach-bubble .title {{ display: flex; align-items: center; gap: 6px; font-weight: 800; }}
.coach-bubble .line {{ color: #6B6966; font-size: 0.82rem; margin-top: 2px; }}
.eval-chip {{
    margin-left: auto;
    border-radius: 4px;
    padding: 0 6px;
    font-family: Consolas, monospace;
    font-size: 0.8rem;
    background: #312E2B;
    color: #FFF;
}}
.eval-chip.white {{ background: #FFF; color: #312E2B; border: 1px solid #CCC; }}

/* ── Move list (live game and review) ─────────────────── */
.move-grid {{
    display: grid;
    grid-template-columns: 40px 1fr 1fr;
    row-gap: 2px;
    padding: 4px 0;
    font-size: 0.95rem;
}}
.move-grid .n, .var-line .n {{ color: var(--text-3); padding-top: 1px; }}
.move-grid .mv, .var-line .mv {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 1px 6px;
    border-radius: 4px;
    cursor: pointer;
    color: var(--text);
    justify-self: start;
    white-space: nowrap;
}}
.move-grid .mv:hover, .var-line .mv:hover {{ background: var(--raised); }}
.move-grid .mv.cur, .var-line .mv.cur {{ background: var(--raised-hover); }}
.move-grid .result {{ grid-column: 1 / -1; color: var(--text-2); font-weight: 800; padding: 4px 0; }}
.opening-line {{ color: var(--text-3); font-size: 0.8rem; }}

/* A side line tried in the review: its moves in one wrapping run */
.var-box {{
    background: var(--log);
    border-left: 3px solid var(--green);
    border-radius: 6px;
    padding: 6px 8px 8px;
}}
.var-head {{ color: var(--text-3); font-size: 0.8rem; }}
.var-line {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 2px 2px;
    font-size: 0.95rem;
}}
.review-actions {{ padding: 2px 14px 6px; }}

/* ── Board ────────────────────────────────────────────── */
.board-grid {{
    position: relative;
    display: grid;
    grid-template-columns: repeat(8, 1fr);
    grid-template-rows: repeat(8, 1fr);
    aspect-ratio: 1 / 1;
    width: 100%;
    /* 100vh minus the status line and both player bars */
    max-width: min(calc(100vh - 170px), 100%);
    margin: 0 auto;
    border-radius: 3px;
    user-select: none;
}}
.board-sq {{
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: clamp(18px, 5.2vmin, 52px);
    line-height: 1;
    cursor: pointer;
}}
.board-sq.light {{ background: var(--light-sq); }}
.board-sq.dark  {{ background: var(--dark-sq); }}
/* Highlights are overlays, so they read the same on every board style */
.board-sq.lfrom, .board-sq.lto, .board-sq.sel {{
    box-shadow: inset 0 0 0 100vmax rgba(255, 255, 51, 0.5);
}}
.board-sq.chk {{
    background-image: radial-gradient(ellipse at center, rgb(255, 0, 0) 0%,
        rgb(231, 0, 0) 25%, rgba(169, 0, 0, 0) 89%, rgba(158, 0, 0, 0) 100%);
}}
.board-sq.dot::after {{
    content: '';
    position: absolute;
    width: 33%;
    height: 33%;
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.14);
}}
.board-sq.ring::after {{
    content: '';
    position: absolute;
    inset: 0;
    border-radius: 50%;
    border: max(4px, 0.7vmin) solid rgba(0, 0, 0, 0.14);
}}
.board-sq .coord {{
    position: absolute;
    font-size: clamp(8px, 1.4vmin, 14px);
    font-weight: 700;
    pointer-events: none;
}}
.board-sq .coord.rank {{ top: 2px; left: 3px; }}
.board-sq .coord.file {{ bottom: 1px; right: 3px; }}
.board-sq.light .coord {{ color: var(--dark-sq); }}
.board-sq.dark  .coord {{ color: var(--light-sq); }}
.board-sq img.pc-img {{
    width: 88%;
    height: 88%;
    object-fit: contain;
    pointer-events: none;
    filter: drop-shadow(1px 2px 2px rgba(0,0,0,0.35));
}}
/* Dragging pieces: a grab cursor on the ones that may move, and the
   dragged copy following the pointer above everything */
.board-grid.draggable {{ touch-action: none; }}
.board-grid.draggable .board-sq.can-drag {{ cursor: grab; }}
.board-sq.drag-over {{ box-shadow: inset 0 0 0 4px rgba(255, 255, 255, 0.7); }}
img.drag-ghost {{
    position: fixed;
    z-index: 9000;
    pointer-events: none;
    object-fit: contain;
    cursor: grabbing;
    filter: drop-shadow(2px 6px 6px rgba(0,0,0,0.55));
}}
/* Badges and arrows sit on one layer over the whole board */
.board-overlay {{
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 4;
}}
{tint_css()}
img.btn-ic {{
    height: 16px;
    width: auto;
    pointer-events: none;
}}

/* ── Eval bar ─────────────────────────────────────────── */
.eval-bar {{
    width: 26px;
    background: #403D39;
    border-radius: 3px;
    position: relative;
    overflow: hidden;
}}
.eval-bar .white-part {{
    position: absolute;
    bottom: 0;
    width: 100%;
    background: #FFFFFF;
    transition: height 0.4s ease;
}}
.eval-bar .mid {{
    position: absolute;
    top: 50%;
    width: 100%;
    border-top: 1px solid rgba(128, 128, 128, 0.35);
}}
.eval-bar .val {{
    position: absolute;
    width: 100%;
    text-align: center;
    font-size: 10px;
    font-weight: 700;
    z-index: 2;
}}
.eval-bar.flipped .white-part {{
    bottom: auto;
    top: 0;
}}

/* ── Tables ───────────────────────────────────────────── */
.q-table__card, .q-table__container {{
    background: var(--panel);
    color: var(--text);
    box-shadow: none;
}}
.q-table thead th {{
    color: var(--text-3);
    font-weight: 700;
    font-size: 0.72rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}}
.q-table th, .q-table td {{ border-color: var(--line); }}
/* Tables sit in the log's well but read in the page font, numbers in
   even columns */
.q-table__container.arena-log {{
    font-family: var(--font);
    font-variant-numeric: tabular-nums;
}}

/* Every modal adapts to the window: clamp + scroll instead of overflow.
   flex-direction/nowrap are forced because Quasar's `.flex` class sets
   flex-wrap: wrap, which would wrap content into side-by-side columns
   once max-height kicks in (header/search left, table right). */
.q-dialog .arena-panel {{
    display: flex !important;
    flex-direction: column !important;
    flex-wrap: nowrap !important;
    max-width: 95vw !important;
    max-height: 92vh !important;
    overflow: auto;
}}

/* A maximized dialog already fills the screen, so the 92vh/95vw clamp above
   would shrink the card below the space Quasar gave it and force the whole
   panel to scroll. */
.q-dialog__inner--maximized .arena-panel {{
    max-width: 100% !important;
    max-height: 100% !important;
    border-radius: 0;
}}

/* A card whose last row is a pinned footer hands its bottom padding over to
   that footer. Keeping it here would leave a bare strip underneath the
   buttons for the scrolling content to show through, and a negative bottom
   margin can't close it — that only pulls later siblings up, it does not
   grow the element itself. */
.q-dialog .arena-panel:has(.dlg-foot) {{
    padding-bottom: 0;
}}

/* Footer button rows stay pinned and visible while the dialog scrolls. The
   side margins widen the row over the card's left/right padding, so the bar
   spans edge to edge. --nicegui-default-padding is what .nicegui-card
   actually uses, so this tracks it rather than hardcoding 16px. */
.q-dialog .arena-panel .dlg-foot {{
    --pad: var(--nicegui-default-padding, 1rem);
    position: sticky;
    bottom: -1px;
    z-index: 5;
    background: var(--panel);
    margin: auto calc(-1 * var(--pad)) 0;
    padding: 6px var(--pad) var(--pad);
    /* w-full would hold the row at the content width and leave the right
       padding bare; the extra 2x pad matches the negative margins. */
    width: calc(100% + 2 * var(--pad)) !important;
    border-radius: 0 0 8px 8px;
}}

/* The PGN box fills the space it is given and scrolls inside, instead of
   stretching the dialog to fit the whole game. */
.pgn-box {{
    display: flex;
    flex-direction: column;
}}
/* q-field__inner is display:block, so the control below it will not pick up
   the height unless this link in the chain becomes a flex column too. */
.pgn-box .q-field__inner {{
    display: flex;
    flex-direction: column;
    min-height: 0;
}}
.pgn-box .q-field__control {{
    flex: 1 1 auto;
    min-height: 0;
}}
.pgn-box .q-field__control-container {{
    height: 100%;
}}
.pgn-box textarea.q-field__native {{
    height: 100% !important;
    min-height: 0;
    resize: none;
    overflow: auto;
}}

/* Tables marked .dlg-table fill the dialog and scroll their own body, so the
   column labels stay put. The body has to be the scroll container: letting
   the panel scroll instead would need the rows unclipped to keep the sticky
   offset, and unclipped rows paint outside the table. min-height:0 is what
   lets a flex child shrink below its content height and actually scroll. */
.q-dialog .arena-panel .dlg-table {{
    display: flex;
    flex-direction: column;
    min-height: 0;
}}
.q-dialog .arena-panel .dlg-table .q-table__middle {{
    flex: 1 1 auto;
    min-height: 0;
    overflow: auto;
}}
.q-dialog .arena-panel .dlg-table thead tr th {{
    position: sticky;
    top: 0;
    z-index: 2;
    background: var(--panel);
    border-bottom: 1px solid var(--line);
}}

/* ── Move-class badges ────────────────────────────────── */
.qi {{
    display: inline-block;
    width: 16px;
    height: 16px;
    flex: none;
    background-size: contain;
    background-repeat: no-repeat;
}}
{icon_css()}

/* ── Game Review screen ───────────────────────────────── */
.review-root {{
    background: var(--bg) !important;
    color: var(--text);
}}
.review-root .board-grid {{
    max-width: min(calc(100vh - 150px), 100%);
}}
.review-panel {{
    background: var(--panel);
    border-radius: 8px;
    overflow: hidden;
}}
.review-head {{ background: var(--head); padding: 10px 12px; }}
.review-title {{
    font-size: 1.3rem;
    font-weight: 800;
    color: var(--text);
    white-space: nowrap;
}}
.review-head .q-btn {{ color: var(--text-2); }}
.review-speed {{ width: 92px; font-size: 0.8rem; }}
.review-coach {{ padding: 12px 14px 4px; }}
.review-graph {{ margin: 6px 14px; border-radius: 4px; overflow: hidden; }}
.review-progress {{ padding: 4px 14px; color: var(--text-3); font-size: 0.82rem; }}
.review-grid {{
    display: grid;
    grid-template-columns: 1fr 76px 44px 76px;
    align-items: center;
    row-gap: 8px;
    padding: 6px 18px 10px;
}}
.review-grid .lbl {{ font-weight: 700; font-size: 1rem; }}
.review-grid .num {{ text-align: center; font-weight: 800; font-size: 1.15rem; }}
.review-grid .mid {{ display: flex; justify-content: center; }}
.review-grid .sep {{ grid-column: 1 / -1; height: 1px; background: var(--line); }}
.review-acc {{
    text-align: center;
    border-radius: 6px;
    padding: 4px 0;
    font-weight: 800;
    font-size: 1.35rem;
}}
.review-acc.w {{ background: #FFF; color: #312E2B; }}
.review-acc.b {{ background: #403D39; color: #FFF; }}
.review-walk {{ padding: 0 14px; }}
.review-foot {{ padding: 10px 14px 14px; background: var(--panel); }}
.nav-row .q-btn:not(.cta) {{ background: var(--raised); color: var(--text); }}
"""


def apply_theme():
    """Apply the chess.com-style dark theme to the current page."""
    ui.dark_mode().enable()
    ui.colors(primary=GREEN, secondary=BG_RAISED, accent=GREEN,
              dark=BG_PANEL, dark_page=BG_PAGE, positive=GREEN,
              negative=COLOR_RED, warning="#F7C631", info="#5D9ECF")
    # Fields are filled, rounded boxes, as on chess.com
    for element in (ui.input, ui.select, ui.number, ui.textarea):
        element.default_props("filled")
    ui.add_css(GLOBAL_CSS)
    light, dark = board_colors()
    ui.add_css(f":root {{ --light-sq: {light}; --dark-sq: {dark}; }}")
    ui.query("body").style(f"background: {BG_PAGE}")


def push_board_colors():
    """Apply the active board style to the connected client immediately."""
    light, dark = board_colors()
    ui.run_javascript(
        f"document.documentElement.style.setProperty('--light-sq', '{light}');"
        f"document.documentElement.style.setProperty('--dark-sq', '{dark}');")
