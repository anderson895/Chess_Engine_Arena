# ═══════════════════════════════════════════════════════════
#  utils.py — Utility functions shared across modules
# ═══════════════════════════════════════════════════════════

import os
import sys
from core.constants import RANK_TIERS, QUALITY_COLORS


def get_base_path():
    """
    Get the base path for resources, handling PyInstaller bundles.
    
    When running from source: returns the project root directory
    When running as PyInstaller exe: returns the directory containing the exe
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable (PyInstaller)
        return os.path.dirname(sys.executable)
    else:
        # Running from source - go up from core/ to project root
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_path(relative_path):
    """
    Get absolute path to a resource, works for dev and PyInstaller builds.
    
    Parameters
    ----------
    relative_path : str
        Path relative to project root (e.g., "engines/gfruit.exe")
    
    Returns
    -------
    str : Absolute path to the resource
    """
    return os.path.join(get_base_path(), relative_path)


def valid(r, c):
    """Return True if (r, c) is a valid board coordinate."""
    return 0 <= r < 8 and 0 <= c < 8


def normalize_engine_name(name):
    """Strip color suffixes so the same engine is always one record."""
    if not name:
        return ''
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
    if rating is not None:
        for threshold, label, color in RANK_TIERS:
            if rating >= threshold:
                return label, color
    return "Novice", "#90EE90"


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

    # Clamp mate scores (±30000) so "already winning → still winning"
    # doesn't register as a huge swing.
    cp_before = max(-1000, min(1000, cp_before))
    cp_after  = max(-1000, min(1000, cp_after))

    if is_white_moving:
        loss = cp_before - cp_after
    else:
        loss = cp_after - cp_before

    # Thresholds roughly follow the cp-loss scale used by popular sites
    # (inaccuracy ≈ 50–100, mistake ≈ 100–300, blunder ≈ 300+). Short
    # analysis searches carry noise, so small swings must stay "good".
    if   loss <= -30:  return "Brilliant"
    elif loss <=   5:  return "Best"
    elif loss <=  20:  return "Excellent"
    elif loss <=  40:  return "Great"
    elif loss <=  90:  return "Good"
    elif loss <= 150:  return "Inaccuracy"
    elif loss <= 300:  return "Mistake"
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
