# ═══════════════════════════════════════════════════════════
#  utils.py — Utility functions shared across modules
# ═══════════════════════════════════════════════════════════

import os
import sys
from core.constants import RANK_TIERS, START_FEN


def get_base_path():
    """
    Get the base path for resources, handling PyInstaller bundles.
    
    - Onefile PyInstaller build: returns the temp extraction folder (_MEIPASS)
    - Onedir PyInstaller build / frozen fallback: returns exe's folder
    - Running from source: returns the project root directory
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller onefile mode extracts data files here at runtime
        if hasattr(sys, '_MEIPASS'):
            return sys._MEIPASS
        # Fallback for onedir builds
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


# ── Where a game starts ───────────────────────────────────
# A game can start from any position, not just the standard one. These
# two answer the questions every part of the app asks about that start —
# the engine command, the PGN, the move numbers and the review cache — so
# they all agree. They work on the FEN text alone: core.board imports this
# module, so nothing here may need a Board.

def custom_start(fen):
    """
    The FEN of a game's start position when it is not the standard one,
    else None. A FEN of the standard position is the standard start,
    whatever its move counters say.
    """
    fields = (fen or "").split()
    if not fields or fields[:4] == START_FEN.split()[:4]:
        return None
    return " ".join(fields)


def start_ply(fen):
    """
    How many plies a game had run when it reached *fen*: 0 for the
    standard start, else (move number - 1) x 2, plus one when Black is to
    move. Move numbers and whose move it is are counted on from there.
    """
    fields = (fen or "").split()
    if len(fields) < 2:
        return 0
    try:
        fullmove = max(1, int(fields[5])) if len(fields) > 5 else 1
    except ValueError:
        fullmove = 1
    return (fullmove - 1) * 2 + (1 if fields[1] == "b" else 0)


def normalize_engine_name(name):
    """Strip color suffixes so the same engine is always one record."""
    if not name:
        return ''
    for suffix in [' (White)', ' (Black)', ' (white)', ' (black)',
                   '(White)', '(Black)', '(white)', '(black)']:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
    return name.strip()


def _db_dir():
    """The per-user data directory, created on first use."""
    db_dir = os.path.join(os.path.expanduser("~"), ".chess_arena")
    os.makedirs(db_dir, exist_ok=True)
    return db_dir


def get_db_path():
    """Return the path to the engine SQLite database, creating the directory."""
    return os.path.join(_db_dir(), "chess_arena.db")


def get_masters_db_path():
    """
    Return the path to the human-games database.

    Deliberately a separate file from the engine database. The masters
    collection is republished wholesale and runs to hundreds of megabytes,
    while engine games, tournaments and Elo history are personal and small.
    Splitting them means updating the collection never rewrites the user's
    own results, and a published snapshot carries no private games.
    """
    return os.path.join(_db_dir(), "masters.db")


def get_reviews_db_path():
    """
    Return the path to the game-review analysis cache.

    A cache, not a record: every row can be recomputed by analysing the
    game again, so like masters.db it stays out of the published snapshot.
    """
    return os.path.join(_db_dir(), "reviews.db")


def file_sha1(path):
    """Hex SHA-1 of a file's contents, or '' if it cannot be read."""
    import hashlib
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


# Below this the clock shows tenths and the warning sounds. Ten seconds is
# where a chess clock stops being a number you glance at and starts being
# the thing you are playing against, and it is what every online board uses.
LOW_TIME_MS = 10_000


def fmt_clock(ms):
    """
    m:ss for a clock value in milliseconds, m:ss.t under ten seconds.

    Truncates rather than rounds, the way a chess clock does: 0:00.0 has
    to mean "under a tenth left", never "a tenth already past".
    """
    ms = max(0, int(ms))
    s = ms // 1000
    if ms < LOW_TIME_MS:
        return f"{s // 60}:{s % 60:02d}.{ms % 1000 // 100}"
    return f"{s // 60}:{s % 60:02d}"


def low_time_warning(ms, was_low):
    """
    Whether a clock at *ms* has just crossed into its last ten seconds.

    Returns (warn, low) — *warn* is True only on the poll that crosses the
    line, and *low* is the state to hand back next time. Clocks are polled,
    so the crossing has to be remembered; without it the warning would
    sound on every poll for ten seconds.

    A clock back above the line has been reset by an increment or a new
    game and can warn again. Otherwise one game spent under ten seconds
    would silence every game after it.
    """
    low = ms < LOW_TIME_MS
    return (low and not was_low), low


def get_tier(rating):
    """Return the (label, color) tier tuple for a given Elo rating."""
    if rating is not None:
        for threshold, label, color in RANK_TIERS:
            if rating >= threshold:
                return label, color
    # No rating is not the bottom tier: it means too few games to say
    return "Provisional", "#777"


def build_pgn(white, black, moves, result, date, opening_name=None,
              start_fen=None):
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
    start_fen : str | None
        The position the game started from, when not the standard one: the
        PGN then carries SetUp and FEN tags, and its moves are numbered on
        from that position ("20... Rxd4 21. Qe2").

    Returns
    -------
    str — the complete PGN text.
    """
    start_fen = custom_start(start_fen)
    setup_tags = f'[SetUp "1"]\n[FEN "{start_fen}"]\n' if start_fen else ''
    opening_tag = f'[Opening "{opening_name}"]\n' if opening_name else ''
    hdr = (
        f'[Event "Engine Match"]\n[Site "Chess Engine Arena"]\n'
        f'[Date "{date}"]\n[Round "1"]\n[White "{white}"]\n'
        f'[Black "{black}"]\n[Result "{result}"]\n{setup_tags}{opening_tag}\n'
    )
    body = ''
    ply0 = start_ply(start_fen)
    sans = [m[1] for m in moves]
    for i, san in enumerate(sans):
        ply = ply0 + i + 1                   # odd: a White move
        if ply % 2:
            body += f"{(ply + 1) // 2}. "
        elif i == 0:
            body += f"{ply // 2}... "        # the game starts with Black's move
        body += san + ' '
        if (i + 1) % 10 == 0:
            body += '\n'
    return hdr + body + result
