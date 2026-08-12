# ═══════════════════════════════════════════════════════════
#  constants.py — App-wide constants and configuration
# ═══════════════════════════════════════════════════════════

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

UNICODE = {
    'K': '♔', 'Q': '♕', 'R': '♖', 'B': '♗', 'N': '♘', 'P': '♙',
    'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟',
}
PIECE_VALUES = {'p': 1, 'n': 3, 'b': 3, 'r': 5, 'q': 9, 'k': 0}

# ── Time controls ─────────────────────────────────────────
# key → (label, base minutes, increment seconds). Clocked presets use
# "go wtime/btime winc/binc" so engines manage their own time and lose
# on time when the clock runs out. "Classic" has no clock (base is
# None): engines get a fixed think time per move and never lose on time.
# Rapid (10+5) was dropped: two engines with ten minutes each turn one
# game into most of an hour and a tournament into a week. The handful
# already played at it stay in the history and keep their own rating
# bucket; there is just no way to start another.
TIME_CONTROLS = {
    "bullet":  ("Bullet (1+0)",  1.0, 0.0),
    "blitz":   ("Blitz (3+2)",   3.0, 2.0),
    "classic": ("Classic",       None, None),
}

# ── Board colours ─────────────────────────────────────────
LIGHT_SQ = "#F0D9B5"
DARK_SQ  = "#B58863"
LAST_FROM = "#CDD26A"
LAST_TO   = "#AAB44F"
CHECK_SQ  = "#FF4444"

# ── UI colours ────────────────────────────────────────────
BG       = "#1A1A2E"
PANEL_BG = "#16213E"
ACCENT   = "#E94560"
TEXT     = "#EAEAEA"
BTN_BG   = "#0F3460"
BTN_HOV  = "#E94560"
LOG_BG   = "#0D0D1A"
INFO_BG  = "#0A0A18"

# ── Move quality colours ──────────────────────────────────
QUALITY_COLORS = {
    "Book":       "#00BFFF",
    "Brilliant":  "#1BECA0",
    "Best":       "#5BC0EB",
    "Excellent":  "#7FFF00",
    "Great":      "#A8D8A8",
    "Good":       "#FFDD57",
    "Inaccuracy": "#E8C547",
    "Mistake":    "#FFA500",
    "Blunder":    "#FF4444",
}

# ── Rank tiers ────────────────────────────────────────────
# Bands of engine strength, not borrowed human titles. Every engine here
# is far beyond any human, so "GM" said nothing about one and "Super
# Computer" said it of all of them. The thresholds are set against what
# this collection actually spans (see core/scale.py) rather than a scale
# from elsewhere — the old ladder topped out at 2900 and started its
# tiers at 1400, which on a pool averaging 1500 left its four highest
# unreachable and put every engine in the same two bands.
RANK_TIERS = [
    (3000, "Top Engine",  "#FF0000"),
    (2850, "Elite",       "#FFE600"),
    (2700, "Strong",      "#57FF35"),
    (2500, "Established", "#42FF8A"),
    (2300, "Club",        "#4274FF"),
    (2100, "Hobby",       "#CF87EB"),
    (1800, "Legacy",      "#AAAAAA"),
    (   0, "Toy",         "#DBDBDB"),
]

# ── Piece movement directions ─────────────────────────────
ROOK_D   = [(1, 0), (-1, 0), (0, 1), (0, -1)]
BISHOP_D = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
QUEEN_D  = ROOK_D + BISHOP_D
KNIGHT_D = [(2,1),(2,-1),(-2,1),(-2,-1),(1,2),(1,-2),(-1,2),(-1,-2)]
KING_D   = ROOK_D + BISHOP_D
