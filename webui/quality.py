# ═══════════════════════════════════════════════════════════
#  webui/quality.py — How a move classification looks
#
#  One source for the badge of every class (Brilliant "!!", Best star,
#  Blunder "??", …), so the live game, the tournament window, the
#  game-over summary and the review screen all draw them the same way.
#  The badges are inline SVG drawn here — no emoji, no image files.
# ═══════════════════════════════════════════════════════════

from html import escape
from urllib.parse import quote

from nicegui import ui

from core.constants import QUALITY_COLORS, QUALITY_SYMBOLS

# Short explanations shown on hover in the review table
QUALITY_TIPS = {
    "Brilliant":  "A good sacrifice — the best move, and hard to find",
    "Great":      "The only good move — every other move loses ground",
    "Book":       "Opening theory",
    "Best":       "The engine's top choice",
    "Excellent":  "Almost as good as the best move",
    "Good":       "A solid move, though a better one was there",
    "Inaccuracy": "Gives away a little of the position",
    "Mistake":    "Gives away a lot of the position",
    "Miss":       "Fails to punish the opponent's mistake",
    "Blunder":    "Throws the position away",
    "Forced":     "The only legal move",
}

_WHITE = "#ffffff"

# Glyphs drawn on a 100×100 canvas, centred on (50, 50)
_SHAPES = {
    "Best": (f'<polygon fill="{_WHITE}" points="50,20 58.8,38 78.5,40.7 64.3,54.6 '
             f'67.6,74.3 50,65 32.4,74.3 35.7,54.6 21.5,40.7 41.2,38"/>'),
    "Excellent": (f'<path fill="{_WHITE}" d="M26 47h11v29H26z M41 76h23c3.6 0 6.3-2.4 '
                  f'7-5.6l4.4-18.6c.9-4.2-2.2-7.8-6.4-7.8H56l2.3-10.4c.9-4.3-2.2'
                  f'-8.3-6.6-8.3h-1.3L41 46.5z"/>'),
    "Good": (f'<polyline fill="none" stroke="{_WHITE}" stroke-width="11" '
             f'stroke-linecap="round" stroke-linejoin="round" '
             f'points="28,52 44,67 72,35"/>'),
    "Book": (f'<path fill="{_WHITE}" d="M22 30c10-4 19-3 26 3v41c-7-6-16-7-26-3z '
             f'M78 30c-10-4-19-3-26 3v41c7-6 16-7 26-3z"/>'),
    "Miss": (f'<path fill="none" stroke="{_WHITE}" stroke-width="11" '
             f'stroke-linecap="round" d="M32 32L68 68M68 32L32 68"/>'),
    "Forced": (f'<path fill="none" stroke="{_WHITE}" stroke-width="10" '
               f'stroke-linecap="round" stroke-linejoin="round" '
               f'd="M26 50h44M54 33l17 17-17 17"/>'),
}


def icon_body(cls):
    """The badge of *cls* as SVG elements on a 0..100 canvas ('' if unknown)."""
    color = QUALITY_COLORS.get(cls)
    if not color:
        return ""
    disc = (f'<circle cx="50" cy="52" r="47" fill="rgba(0,0,0,0.28)"/>'
            f'<circle cx="50" cy="50" r="47" fill="{color}"/>')
    glyph = _SHAPES.get(cls)
    if glyph is None:
        text = QUALITY_SYMBOLS.get(cls, "")
        size = 62 if len(text) == 1 else 50
        glyph = (f'<text x="50" y="51" fill="{_WHITE}" font-size="{size}" '
                 f'font-family="Arial Black, Arial, sans-serif" font-weight="900" '
                 f'text-anchor="middle" dominant-baseline="central" '
                 f'letter-spacing="-3">{text}</text>')
    return disc + glyph


def icon_svg(cls, size=18):
    """A standalone badge, *size* pixels square ('' for no class)."""
    body = icon_body(cls)
    if not body:
        return ""
    # Not "q-icon": that is Quasar's own class, which sizes to 1em
    return (f'<svg class="quality-icon" width="{size}" height="{size}" '
            f'viewBox="0 0 100 100" style="flex: none">{body}</svg>')


def label_html(cls, size=20, text_cls=""):
    """Badge plus the class name in its colour — the live-game label."""
    if not cls:
        return ""
    color = QUALITY_COLORS.get(cls, "#EAEAEA")
    return (f'<span style="display:inline-flex;align-items:center;gap:6px">'
            f'{icon_svg(cls, size)}'
            f'<span class="{escape(text_cls)}" style="color:{color};font-weight:700">'
            f'{escape(cls)}</span></span>')


class MoveVerdict:
    """
    The line under a live board grading the move just played — its badge,
    the class in its colour and the move ("Brilliant  5. Nxe5"). The main
    board and the tournament window both use it, so they read alike.
    """

    def __init__(self, size=20):
        self.size = size
        with ui.row().classes("w-full justify-center items-center gap-2 "
                              "min-h-[28px]"):
            # Our own SVG badge and the class name — no user text in it
            self.badge = ui.html("", sanitize=False)
            self.move = ui.label("").classes("text-xs text-gray-400")

    def show(self, review):
        """Show a core.review.MoveReview, or clear the line for None."""
        if review is None or not review.cls:
            self.badge.set_content("")
            self.move.set_text("")
            return
        self.badge.set_content(label_html(review.cls, self.size))
        self.move.set_text(review.numbered_san)


def icon_css():
    """
    CSS classes ``qi qi-<class>`` showing each badge as a background image —
    for long move lists, where repeating the inline SVG on every move would
    send hundreds of copies of the same few drawings.
    """
    rules = []
    for cls in QUALITY_COLORS:
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
               f'{icon_body(cls)}</svg>')
        rules.append(f'.qi-{cls.lower()} {{ background-image: '
                     f'url("data:image/svg+xml,{quote(svg)}"); }}')
    return "\n".join(rules)


def tint_css(alpha=0.5):
    """
    CSS tinting the from/to squares of a classified move in its colour.
    An inset shadow paints over the square's own colour but under the
    piece, so it needs no stacking tricks.
    """
    rules = []
    for cls, color in QUALITY_COLORS.items():
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        rules.append(f".board-sq.q-{cls.lower()} {{ box-shadow: inset 0 0 0 100vmax "
                     f"rgba({r},{g},{b},{alpha}); }}")
    return "\n".join(rules)
