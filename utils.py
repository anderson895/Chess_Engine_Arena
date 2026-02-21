# ═══════════════════════════════════════════════════════════
#  utils.py — Utility functions shared across modules
# ═══════════════════════════════════════════════════════════

import os
from constants import RANK_TIERS, QUALITY_COLORS


def valid(r, c):
    """Return True if (r, c) is a valid board coordinate."""
    return 0 <= r < 8 and 0 <= c < 8


def normalize_engine_name(name):
    """Strip color suffixes so the same engine is always one record."""
    for suffix in [' (White)', ' (Black)', ' (white)', ' (black)',
                   '(White)', '(Black)', '(white)', '(black)']:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
    return name.strip()


def get_db_path():
    """Return the path to the SQLite database, creating the directory if needed."""
    home = os.path.expanduser("~")
    db_dir = os.path.join(home, ".chess_arena")
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, "chess_arena.db")


def get_tier(rating):
    """Return the (label, color) tier tuple for a given Elo rating."""
    for threshold, label, color in RANK_TIERS:
        if rating >= threshold:
            return label, color
    return "🌱 Novice", "#90EE90"


def classify_move_quality(cp_before, cp_after, is_white_moving):
    """
    Classify a move's quality based on centipawn evaluation before/after.

    Parameters
    ----------
    cp_before : int | None
        Evaluation (from White's perspective) before the move.
    cp_after : int | None
        Evaluation (from White's perspective) after the move.
    is_white_moving : bool
        True if White just moved.

    Returns
    -------
    str | None  — quality label, or None if data unavailable.
    """
    if cp_before is None or cp_after is None:
        return None
    if is_white_moving:
        loss = cp_before - cp_after
    else:
        loss = cp_after - cp_before

    if   loss <= -50:  return "Brilliant"
    elif loss <=   0:  return "Best"
    elif loss <=  10:  return "Excellent"
    elif loss <=  25:  return "Great"
    elif loss <=  50:  return "Good"
    elif loss <= 100:  return "Mistake"
    else:              return "Blunder"


def build_pgn(white, black, moves, result, date, opening_name=None):
    """
    Build a PGN string from the given game data.

    Parameters
    ----------
    white : str
        White player / engine name.
    black : str
        Black player / engine name.
    moves : list of (uci, san, fen) tuples
        Move history as stored in the Board.
    result : str
        PGN result string, e.g. "1-0", "0-1", "1/2-1/2", "*".
    date : str
        Date string in PGN format "YYYY.MM.DD".
    opening_name : str | None
        Optional opening name to include as a PGN tag.

    Returns
    -------
    str — the complete PGN text.
    """
    opening_tag = f'[Opening "{opening_name}"]\n' if opening_name else ''
    hdr = (
        f'[Event "Engine Match"]\n[Site "Chess Engine Arena"]\n'
        f'[Date "{date}"]\n[Round "1"]\n[White "{white}"]\n'
        f'[Black "{black}"]\n[Result "{result}"]\n{opening_tag}\n'
    )
    body = ''
    sans = [m[1] for m in moves]
    for i, san in enumerate(sans):
        if i % 2 == 0:
            body += f"{i // 2 + 1}. "
        body += san + ' '
        if (i + 1) % 10 == 0:
            body += '\n'
    return hdr + body + result
