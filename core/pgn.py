# ═══════════════════════════════════════════════════════════
#  pgn.py — Reading PGN text
#
#  One reader for every place a stored game is turned back into moves:
#  the review screen, the masters importer and the maintenance tools.
#  Moves are resolved strictly — the first token that is not a legal
#  move ends the game there, rather than being skipped and shifting
#  every later move onto the wrong side.
# ═══════════════════════════════════════════════════════════

import re

from core.board import Board, parse_uci
from core.utils import custom_start

_TAG_RE = re.compile(r'^\[([A-Za-z0-9_]+)\s+"(.*)"\]\s*$')

# Everything that is not an actual move: move numbers, results, NAGs.
_NUMBER_RE = re.compile(r'\d+\.(\.\.)?')
_NAG_RE = re.compile(r'\$\d+')
RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}

_MOVE_NUMBER_TOKEN = re.compile(r'^\d+\.+$')            # "1."  "12..."
_UCI_RE = re.compile(r'^[a-h][1-8][a-h][1-8][qrbn]?$')


def split_pgn_games(text):
    """
    Split a multi-game PGN into (tags: dict, movetext: str) pairs.

    Robust against the quirks of real-world exports: CRLF, BOM, missing
    blank line between header and movetext, and games that run straight
    into the next [Event "..."] with no separator.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    games = []
    tags = {}
    moves = []
    seen_moves = False

    def flush():
        if tags or moves:
            games.append((dict(tags), " ".join(moves).strip()))

    for raw in text.split("\n"):
        line = raw.strip()
        m = _TAG_RE.match(line)
        if m:
            # A tag after movetext means the previous game ended.
            if seen_moves:
                flush()
                tags, moves, seen_moves = {}, [], False
            tags[m.group(1)] = m.group(2)
        elif line:
            moves.append(line)
            seen_moves = True
    flush()
    return [(t, mv) for t, mv in games if t or mv]


def strip_movetext(movetext):
    """Reduce movetext to bare SAN tokens: no comments, variations or NAGs."""
    s = movetext
    # Comments {...} — may nest in practice only via braces, so loop.
    while True:
        new = re.sub(r'\{[^{}]*\}', ' ', s)
        if new == s:
            break
        s = new
    # Recursive annotation variations (...)
    while True:
        new = re.sub(r'\([^()]*\)', ' ', s)
        if new == s:
            break
        s = new
    s = _NAG_RE.sub(' ', s)
    s = _NUMBER_RE.sub(' ', s)
    s = s.replace('...', ' ')
    return [t for t in s.split() if t not in RESULTS and t not in ('.', '')]


def tokens_to_uci(tokens, limit=None, strict=False, start_fen=None):
    """
    UCI moves for move tokens played from the start position — or from
    *start_fen*, for a game set up from a position. Tokens may be SAN
    (``Nf3``) or UCI (``g1f3``); move numbers are skipped.

    The first token that is not a legal move ends the game there — or,
    with *strict*, rejects the whole list (None), for sources such as the
    opening book where a half-read line would be wrong. *limit* stops
    after that many plies.
    """
    board = Board.from_fen(start_fen) if start_fen else Board()
    out = []
    for tok in tokens:
        if limit is not None and len(out) >= limit:
            break
        if _MOVE_NUMBER_TOKEN.match(tok):
            continue
        uci = board.san_to_uci(tok) or _legal_uci(board, tok)
        if uci is None:
            if strict:
                return None
            break
        board = board.play_raw(uci)
        out.append(uci)
    return out


def _legal_uci(board, tok):
    """*tok* if it is a legal move in UCI notation, else None."""
    tok = tok.lower()
    if not _UCI_RE.match(tok):
        return None
    return tok if parse_uci(tok) in board.legal_moves() else None


# Variant tags of games that are ordinary chess, whatever their start
_STANDARD_VARIANTS = {"", "standard", "chess", "from position"}


def _tag_start(tags):
    """
    The start position a game's FEN tag names, as the board reads it; None
    for the standard start. Raises ValueError for a start that cannot be
    played here: a FEN that cannot be read, or another variant (Chess960
    castles in ways this board does not know).
    """
    variant = (tags.get("Variant") or "").strip()
    if variant.lower() not in _STANDARD_VARIANTS:
        raise ValueError(f"{variant} games are not supported")
    if (tags.get("SetUp") or "").strip() == "0":
        return None
    fen = (tags.get("FEN") or "").strip()
    if not fen:
        return None
    try:
        return custom_start(Board.parse_fen(fen).to_fen())
    except ValueError as e:
        raise ValueError(f"Its starting position can't be read ({e})") from None


def start_fen_of(tags):
    """
    Where a PGN game starts, from its tags: the FEN of a game set up from
    a position, else None — also for a start that cannot be played here
    (start_problem), whose game read_game() returns without moves.
    """
    try:
        return _tag_start(tags)
    except ValueError:
        return None


def start_problem(tags):
    """Why a PGN game's start cannot be played here, or None."""
    try:
        _tag_start(tags)
    except ValueError as e:
        return str(e)
    return None


def read_game(pgn, limit=None):
    """
    The first game of a PGN text as (tags, uci_moves), the moves played
    from the position its FEN tag names (start_fen_of) if it has one.

    *limit* stops after that many plies — enough for naming an opening
    without resolving a 400-ply endgame.
    """
    games = split_pgn_games(pgn or "")
    if not games:
        return {}, []
    tags, movetext = games[0]
    try:
        start = _tag_start(tags)
    except ValueError:
        return tags, []             # a start position we cannot set up
    return tags, tokens_to_uci(strip_movetext(movetext), limit,
                               start_fen=start)


def set_tag(pgn, name, value):
    """
    The PGN with tag *name* set to *value*: replaced where it exists,
    otherwise added after the Seven Tag Roster (or the last tag).
    """
    line = f'[{name} "{value}"]'
    pattern = re.compile(rf'^\[{re.escape(name)}\s+"[^"]*"\][ \t]*$', re.M)
    if pattern.search(pgn):
        return pattern.sub(lambda _m: line, pgn, count=1)
    tags = list(re.finditer(r'^\[[A-Za-z0-9_]+\s+"[^"]*"\][ \t]*$', pgn, re.M))
    if not tags:
        return f"{line}\n{pgn}"
    anchor = next((m for m in tags if m.group(0).startswith('[Result ')), tags[-1])
    return pgn[:anchor.end()] + "\n" + line + pgn[anchor.end():]
