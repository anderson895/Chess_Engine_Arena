# ═══════════════════════════════════════════════════════════
#  constants.py — App-wide constants and configuration
# ═══════════════════════════════════════════════════════════

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

UNICODE = {
    'K': '♔', 'Q': '♕', 'R': '♖', 'B': '♗', 'N': '♘', 'P': '♙',
    'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟',
}
PIECE_VALUES = {'p': 1, 'n': 3, 'b': 3, 'r': 5, 'q': 9, 'k': 0}

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
    "Brilliant": "#1BECA0",
    "Best":      "#5BC0EB",
    "Excellent": "#7FFF00",
    "Great":     "#A8D8A8",
    "Good":      "#FFDD57",
    "Mistake":   "#FFA500",
    "Blunder":   "#FF4444",
}

# ── Rank tiers ────────────────────────────────────────────
RANK_TIERS = [
    (2900, "💻 Super Computer",  "#FF0000"),
    (2700, "🌟 Super GM",        "#FFE600"),
    (2400, "🏆 GM",              "#57FF35"),
    (2000, "📘 IM",              "#42FF8A"),
    (1800, "🎯 FM",              "#4274FF"),
    (1600, "📝 Candidate",       "#CF87EB"),
    (1400, "🔰 Beta",            "#AAAAAA"),
    (   0, "❓ Unrated",          "#DBDBDB"),
]

# ── Piece movement directions ─────────────────────────────
ROOK_D   = [(1, 0), (-1, 0), (0, 1), (0, -1)]
BISHOP_D = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
QUEEN_D  = ROOK_D + BISHOP_D
KNIGHT_D = [(2,1),(2,-1),(-2,1),(-2,-1),(1,2),(1,-2),(-1,2),(-1,-2)]
KING_D   = ROOK_D + BISHOP_D
