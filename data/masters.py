# ═══════════════════════════════════════════════════════════════════════════════
#  masters.py — Human / master game database (real players: GM, IM, WGM, …)
#
#  Kept in its own table, deliberately separate from `games`:
#  human results must never leak into the engine Elo ratings or rankings.
# ═══════════════════════════════════════════════════════════════════════════════

import csv
import hashlib
import os
import re
import sqlite3

from core.utils import get_base_path, get_db_path


# ── PGN parsing ────────────────────────────────────────────────

_TAG_RE = re.compile(r'^\[([A-Za-z0-9_]+)\s+"(.*)"\]\s*$')

# Everything that is not an actual move: move numbers, results, NAGs.
_NUMBER_RE = re.compile(r'\d+\.(\.\.)?')
_NAG_RE = re.compile(r'\$\d+')
_RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}

TITLES = ("GM", "IM", "FM", "CM", "WGM", "WIM", "WFM", "WCM", "NM", "LM")


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
    return [t for t in s.split() if t not in _RESULTS and t not in ('.', '')]


def count_plies(movetext):
    return len(strip_movetext(movetext))


def _norm_name(name):
    """Normalise a player name for dedupe: 'Carlsen, Magnus' == 'carlsen,magnus'."""
    return re.sub(r'[^a-z]', '', (name or '').lower())


def _norm_date(value):
    """PGN 'YYYY.MM.DD' → 'YYYY-MM-DD'. Unknown fields become '?'."""
    v = (value or '').strip().replace('/', '.')
    parts = v.split('.')
    if len(parts) >= 3:
        y, m, d = parts[0], parts[1], parts[2]
        if y.isdigit():
            m = m if m.isdigit() else '??'
            d = d if d.isdigit() else '??'
            return f"{int(y):04d}-{m:0>2}-{d:0>2}"
    return ''


def _clean_name(name):
    """
    Normalise a player name to 'Surname, Rest'.

    PGN Mentor writes 'Carlsen,M' with no space; Lichess relays write
    'Carlsen, Magnus'. Storing one shape means the search only has to
    handle one shape.
    """
    n = re.sub(r'\s+', ' ', (name or '').strip())
    return re.sub(r'\s*,\s*', ', ', n)


def _split_title(name):
    """
    Split a leading/trailing title off a player name.

    Handles both 'GM Carlsen, Magnus' and plain 'Carlsen, Magnus'.
    Returns (title, clean_name).
    """
    n = (name or '').strip()
    for t in TITLES:
        if n.upper().startswith(t + ' '):
            return t, n[len(t) + 1:].strip()
    return '', n


def opening_from_eco_url(url):
    """
    Derive an opening name from a Chess.com ECOUrl.

    Chess.com omits the [Opening] tag but links the opening instead:
    .../openings/Sicilian-Defense-Najdorf-Variation → 'Sicilian Defense
    Najdorf Variation'. Move suffixes ('...-4.Nxd4') are dropped.
    """
    if not url:
        return ''
    slug = url.rstrip('/').rsplit('/', 1)[-1]
    parts = [p for p in slug.split('-')
             if p and not re.match(r'^\d+\.', p) and not re.match(r'^\d+$', p)]
    return " ".join(parts).strip()


_ECO_NAMES = None


def eco_name(code):
    """
    Fall back to the opening family name for an ECO code.

    Older collections (PGN Mentor, TWIC) tag ECO but not [Opening]. The
    shortest line under a code is its most general form, which is the right
    label when the exact variation is unknown.
    """
    global _ECO_NAMES
    if _ECO_NAMES is None:
        _ECO_NAMES = {}
        for base in (get_base_path(), os.getcwd()):
            path = os.path.join(base, "openings", "openings_sheet.csv")
            if not os.path.isfile(path):
                continue
            try:
                with open(path, newline="", encoding="utf-8") as fh:
                    best = {}
                    for row in csv.DictReader(fh):
                        c = (row.get("ECO") or "").strip().upper()
                        name = (row.get("name") or "").strip()
                        # Some rows name a line after its own code ("B72");
                        # that is not a label, it is the code again.
                        if not c or not name or name.split(';')[0].strip() == c:
                            continue
                        plies = len((row.get("moves") or "").split())
                        if c not in best or plies < best[c][0]:
                            best[c] = (plies, name)
                    _ECO_NAMES = {c: n for c, (_, n) in best.items()}
                break
            except Exception as e:
                print(f"[MastersDB] eco_name: could not read {path}: {e}")

    name = _ECO_NAMES.get((code or '').strip().upper(), '')
    # The CSV repeats the code inside some names ("King's Pawn Opening; B00").
    return name.split(';')[0].strip()


def _to_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def game_key(date, white, black, result, movetext):
    """Stable dedupe key. Same game from two sources collapses to one row."""
    sig = "|".join([
        date or '',
        _norm_name(white),
        _norm_name(black),
        result or '',
        " ".join(strip_movetext(movetext)[:16]),
    ])
    return hashlib.sha1(sig.encode('utf-8')).hexdigest()


class Unfinished(Exception):
    """Raised for a game with no result — a relay caught mid-play."""


def headers_to_row(tags, movetext, source='pgn', keep_unfinished=False):
    """
    Convert a parsed PGN game into a master_games row dict.

    Returns None when the game is unusable (no players, or no moves), and
    raises Unfinished for a game still in progress. Live relay games carry
    Result "*": they are real moves but not yet a game, they clutter every
    listing, and the next sync re-imports the finished copy anyway.
    """
    white_title, white = _split_title(tags.get('White', ''))
    black_title, black = _split_title(tags.get('Black', ''))
    white, black = _clean_name(white), _clean_name(black)
    if not white or not black:
        return None

    plies = count_plies(movetext)
    if plies < 2:
        return None   # a header-only stub from a not-yet-started broadcast

    white_title = tags.get('WhiteTitle', '') or white_title
    black_title = tags.get('BlackTitle', '') or black_title

    w_elo = _to_int(tags.get('WhiteElo'))
    b_elo = _to_int(tags.get('BlackElo'))
    avg = (w_elo + b_elo) // 2 if (w_elo and b_elo) else (w_elo or b_elo)

    result = tags.get('Result', '*').strip()
    if result not in ('1-0', '0-1', '1/2-1/2') and not keep_unfinished:
        raise Unfinished(f"{white} vs {black}")

    date = _norm_date(tags.get('Date') or tags.get('UTCDate'))
    eco = tags.get('ECO', '').strip()
    opening = (tags.get('Opening', '')
               or opening_from_eco_url(tags.get('ECOUrl', ''))
               or eco_name(eco))

    # Lichess relays that are typed straight into a study carry the study
    # chapter name in [Event] ("Round 4: Adams - Verbytski") and the relay's
    # own URL in [Site]. [BroadcastName] holds the real tournament name.
    event = tags.get('Event', '')
    broadcast = tags.get('BroadcastName', '')
    if broadcast and (not event
                      or re.match(r'^(round|chapter|game)\b', event, re.I)):
        event = broadcast

    site = tags.get('Site', '')
    if site.startswith('http'):
        # The game URL is kept in source_url; a link is not a venue.
        site = tags.get('Place', '') or tags.get('Country', '') or ''

    return {
        'date':          date,
        'white':         white,
        'black':         black,
        'white_title':   white_title,
        'black_title':   black_title,
        'white_elo':     w_elo,
        'black_elo':     b_elo,
        'avg_elo':       avg,
        'result':        result,
        'ply_count':     plies,
        'opening':       opening,
        'eco':           eco,
        'event':         event,
        'site':          site,
        'round':         tags.get('Round', ''),
        'time_control':  tags.get('TimeControl', ''),
        'white_fide_id': tags.get('WhiteFideId', ''),
        'black_fide_id': tags.get('BlackFideId', ''),
        'source':        source,
        'source_url':    tags.get('GameURL', '') or tags.get('Link', ''),
        'pgn':           _rebuild_pgn(tags, movetext),
        'game_key':      game_key(date, white, black, result, movetext),
    }


def strip_annotations(movetext):
    """
    Drop {…} comments from movetext, keeping moves and move numbers.

    Lichess relays annotate every single move with [%clk] and [%eval], which
    is 63% of the stored bytes and nothing this database uses — the replay
    viewer runs its own analyzer. Tags are left alone so reparse() still works.
    """
    s = movetext
    while True:
        new = re.sub(r'\{[^{}]*\}', ' ', s)
        if new == s:
            break
        s = new
    return re.sub(r'\s+', ' ', s).strip()


def _rebuild_pgn(tags, movetext):
    """Re-emit a clean PGN so the replay viewer always gets valid input."""
    head = "\n".join(f'[{k} "{v}"]' for k, v in tags.items())
    return f"{head}\n\n{strip_annotations(movetext)}\n"


# ── Database ───────────────────────────────────────────────────

_COLUMNS = ('date', 'white', 'black', 'white_title', 'black_title',
            'white_elo', 'black_elo', 'avg_elo', 'result', 'ply_count',
            'opening', 'eco', 'event', 'site', 'round', 'time_control',
            'white_fide_id', 'black_fide_id', 'source', 'source_url',
            'pgn', 'game_key')

SORTS = {
    'date_desc':  'date DESC, id DESC',
    'date_asc':   'date ASC, id ASC',
    'elo_desc':   'avg_elo DESC NULLS LAST, date DESC',
    'moves_desc': 'ply_count DESC, date DESC',
}


class MastersDB:
    """
    SQLite store for real-world human games.

    Shares the file with the engine database (`get_db_path()`) but lives in
    its own table, so nothing here can reach the engine Elo pipeline.
    """

    def __init__(self, db_path=None):
        self.db_path = db_path or get_db_path()
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self):
        conn = self._connect()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS master_games (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                date          TEXT    DEFAULT '',
                white         TEXT    NOT NULL,
                black         TEXT    NOT NULL,
                white_title   TEXT    DEFAULT '',
                black_title   TEXT    DEFAULT '',
                white_elo     INTEGER,
                black_elo     INTEGER,
                avg_elo       INTEGER,
                result        TEXT    DEFAULT '*',
                ply_count     INTEGER DEFAULT 0,
                opening       TEXT    DEFAULT '',
                eco           TEXT    DEFAULT '',
                event         TEXT    DEFAULT '',
                site          TEXT    DEFAULT '',
                round         TEXT    DEFAULT '',
                time_control  TEXT    DEFAULT '',
                white_fide_id TEXT    DEFAULT '',
                black_fide_id TEXT    DEFAULT '',
                source        TEXT    DEFAULT '',
                source_url    TEXT    DEFAULT '',
                pgn           TEXT    NOT NULL,
                game_key      TEXT    UNIQUE
            )
        ''')
        # Small key/value store for importer settings (auto-sync toggle,
        # last-sync timestamp) — no separate config file to keep in sync.
        conn.execute('''
            CREATE TABLE IF NOT EXISTS master_meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        for name, cols in (
            ('idx_mg_date',  'date DESC'),
            ('idx_mg_white', 'white'),
            ('idx_mg_black', 'black'),
            ('idx_mg_eco',   'eco'),
            ('idx_mg_elo',   'avg_elo DESC'),
            ('idx_mg_event', 'event'),
        ):
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS {name} ON master_games ({cols})')
        conn.commit()
        conn.close()

    # ── Settings ───────────────────────────────────────────

    def get_meta(self, key, default=None):
        try:
            conn = self._connect()
            row = conn.execute("SELECT value FROM master_meta WHERE key = ?",
                               (key,)).fetchone()
            conn.close()
            return row[0] if row else default
        except Exception as e:
            print(f"[MastersDB] get_meta error: {e}")
            return default

    def set_meta(self, key, value):
        try:
            conn = self._connect()
            conn.execute(
                "INSERT INTO master_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[MastersDB] set_meta error: {e}")

    # ── Write ──────────────────────────────────────────────

    def import_pgn(self, pgn_text, source='pgn', progress=None):
        """
        Parse and store every game in *pgn_text*.

        Duplicates (same players, date, result and opening moves) are
        skipped via the UNIQUE game_key, so re-running an import is safe.
        Games still in progress are left out entirely.

        Returns (added, skipped, rejected, unfinished).
        """
        games = split_pgn_games(pgn_text)
        rows = []
        rejected = unfinished = 0
        for tags, movetext in games:
            try:
                row = headers_to_row(tags, movetext, source)
            except Unfinished:
                unfinished += 1
                continue
            if row is None:
                rejected += 1
            else:
                rows.append(row)

        if not rows:
            return 0, 0, rejected, unfinished

        placeholders = ", ".join("?" * len(_COLUMNS))
        sql = (f"INSERT OR IGNORE INTO master_games ({', '.join(_COLUMNS)}) "
               f"VALUES ({placeholders})")
        conn = self._connect()
        before = conn.execute("SELECT COUNT(*) FROM master_games").fetchone()[0]
        conn.executemany(sql, [[r[c] for c in _COLUMNS] for r in rows])
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM master_games").fetchone()[0]
        conn.close()

        added = after - before
        skipped = len(rows) - added
        if progress:
            progress(added, skipped, rejected, unfinished)
        return added, skipped, rejected, unfinished

    def reparse(self, source=None, batch=2000):
        """
        Re-derive every metadata column from the stored PGN.

        The full PGN is kept per row, so improvements to the header parsing
        can be applied to games that are already imported without
        re-downloading them. The PGN itself is rewritten too, which is what
        applies annotation stripping to already-stored games.

        game_key is deliberately left alone: it is derived from the bare
        move tokens, so rewriting the PGN cannot change it, and recomputing
        it would risk colliding with an existing row.

        Returns (updated, removed) — rows that no longer pass the import
        rules, such as games saved before results became mandatory, are
        dropped rather than left behind.
        """
        fields = [c for c in _COLUMNS if c != 'game_key']
        sql = (f"UPDATE master_games SET {', '.join(f'{c} = ?' for c in fields)} "
               f"WHERE id = ?")
        conn = self._connect()
        where = " WHERE source = ?" if source else ""
        params = (source,) if source else ()
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM master_games" + where, params)]

        updated = removed = 0
        for start in range(0, len(ids), batch):
            chunk = ids[start:start + batch]
            marks = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT id, pgn, source FROM master_games "
                f"WHERE id IN ({marks})", chunk).fetchall()
            payload, drop = [], []
            for gid, pgn, src in rows:
                games = split_pgn_games(pgn)
                if not games:
                    continue
                tags, movetext = games[0]
                try:
                    row = headers_to_row(tags, movetext, src)
                except Unfinished:
                    drop.append(gid)     # stored before results were required
                    continue
                if row is None:
                    continue
                payload.append([row[c] for c in fields] + [gid])
            conn.executemany(sql, payload)
            if drop:
                # rowcount, not len(drop): the list is what we asked to
                # delete, this is what actually went.
                marks = ",".join("?" * len(drop))
                cur = conn.execute(
                    f"DELETE FROM master_games WHERE id IN ({marks})", drop)
                removed += cur.rowcount
            conn.commit()
            updated += len(payload)
        conn.close()
        return updated, removed

    def backfill_openings(self):
        """
        Fill in blank opening names for rows imported before the ECO
        fallback existed. Idempotent — only touches empty cells.
        """
        conn = self._connect()
        # opening = eco means an earlier pass wrote the code as the label.
        blank = "(COALESCE(opening, '') = '' OR opening = eco)"
        rows = conn.execute(
            f"SELECT DISTINCT eco FROM master_games "
            f"WHERE {blank} AND COALESCE(eco, '') != ''").fetchall()
        updated = 0
        for (code,) in rows:
            name = eco_name(code)
            if not name:
                continue
            cur = conn.execute(
                f"UPDATE master_games SET opening = ? "
                f"WHERE eco = ? AND {blank}", (name, code))
            updated += cur.rowcount
        conn.commit()
        conn.close()
        return updated

    def delete_game(self, game_id):
        try:
            conn = self._connect()
            conn.execute("DELETE FROM master_games WHERE id = ?", (game_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[MastersDB] delete_game error: {e}")
            return False

    def merge_from(self, other_path):
        """
        Copy master_games rows out of another database file.

        Deliberately a merge of one table, not a file swap: a shared
        snapshot also contains whoever produced it engine games and
        tournaments, and overwriting the local database with those would
        destroy the user's own results and Elo history. The UNIQUE
        game_key does the deduplication, so merging twice is a no-op.

        Returns (added, skipped).
        """
        if not os.path.isfile(other_path):
            raise FileNotFoundError(other_path)

        conn = self._connect()
        # Quote for SQL: ATTACH takes a literal, not a bound parameter.
        literal = other_path.replace("'", "''")
        conn.execute(f"ATTACH DATABASE '{literal}' AS shared")
        try:
            have = conn.execute(
                "SELECT name FROM shared.sqlite_master "
                "WHERE type='table' AND name='master_games'").fetchone()
            if not have:
                raise ValueError("that database has no master_games table")

            # Match on column name so a snapshot from an older or newer
            # schema still merges instead of failing on column order.
            mine = {r[1] for r in conn.execute("PRAGMA table_info(master_games)")}
            theirs = [r[1] for r in
                      conn.execute("PRAGMA shared.table_info(master_games)")]
            common = [c for c in theirs if c in mine and c != "id"]
            cols = ", ".join(f"[{c}]" for c in common)

            before = conn.execute(
                "SELECT COUNT(*) FROM master_games").fetchone()[0]
            available = conn.execute(
                "SELECT COUNT(*) FROM shared.master_games").fetchone()[0]
            conn.execute(f"INSERT OR IGNORE INTO master_games ({cols}) "
                         f"SELECT {cols} FROM shared.master_games")
            conn.commit()
            after = conn.execute(
                "SELECT COUNT(*) FROM master_games").fetchone()[0]
        finally:
            conn.execute("DETACH DATABASE shared")
            conn.close()

        added = after - before
        return added, available - added

    def size_bytes(self):
        """Bytes the master_games rows occupy, plus the whole DB file."""
        try:
            conn = self._connect()
            pgn_bytes = conn.execute(
                "SELECT COALESCE(SUM(LENGTH(pgn)), 0) FROM master_games"
            ).fetchone()[0]
            conn.close()
        except Exception:
            pgn_bytes = 0
        try:
            file_bytes = os.path.getsize(self.db_path)
        except OSError:
            file_bytes = 0
        return pgn_bytes, file_bytes

    def prune(self, max_games):
        """
        Keep the newest *max_games* rows, dropping the oldest imports.

        This is the backstop that stops an automatic sync from filling the
        disk: it runs after every auto-sync, so the database has a hard
        ceiling regardless of how long the app keeps running.
        """
        max_games = int(max_games)
        if max_games <= 0:
            return 0
        conn = self._connect()
        total = conn.execute("SELECT COUNT(*) FROM master_games").fetchone()[0]
        excess = total - max_games
        if excess <= 0:
            conn.close()
            return 0
        cur = conn.execute(
            "DELETE FROM master_games WHERE id IN ("
            "  SELECT id FROM master_games ORDER BY id ASC LIMIT ?)", (excess,))
        n = cur.rowcount
        conn.commit()
        conn.close()
        return n

    def vacuum(self):
        """Return freed pages to the filesystem. Returns bytes reclaimed."""
        before = self.size_bytes()[1]
        conn = sqlite3.connect(self.db_path, timeout=60,
                               isolation_level=None)   # VACUUM needs autocommit
        conn.execute("VACUUM")
        conn.close()
        return max(0, before - self.size_bytes()[1])

    def purge(self, source=None):
        """Delete every game, or every game from one source. Returns the count."""
        conn = self._connect()
        if source:
            cur = conn.execute("DELETE FROM master_games WHERE source = ?",
                               (source,))
        else:
            cur = conn.execute("DELETE FROM master_games")
        n = cur.rowcount
        conn.commit()
        conn.close()
        return n

    # ── Read ───────────────────────────────────────────────

    # Fields a free-text search looks at, in display order.
    _SEARCH_FIELDS = ('white', 'black', 'event', 'opening', 'eco', 'site')

    @staticmethod
    def _search_clause(search):
        """
        Build the free-text search condition.

        Two things make a naive LIKE useless here:

        - Names are stored surname-first, so "magnus carlsen" never appears
          as a substring of "Carlsen, Magnus". Each word is therefore
          matched independently and ANDed, which makes word order and field
          boundaries irrelevant.
        - PGN Mentor abbreviates first names to an initial ("Carlsen, M"),
          so no amount of word matching finds "magnus". A two-word query is
          additionally tried, both ways round, as "Surname, Initial" — and
          because that pattern is anchored to the start of the name it does
          not fire on unrelated queries like "bangkok open".
        """
        words = search.split()
        per_field = " OR ".join(f"{f} LIKE ?"
                                for f in MastersDB._SEARCH_FIELDS)

        parts, params = [], []
        for word in words:
            parts.append(f"({per_field})")
            params.extend([f"%{word}%"] * len(MastersDB._SEARCH_FIELDS))
        strict = " AND ".join(parts)

        if len(words) != 2:
            return f"({strict})", params

        alias, alias_params = [], []
        for surname, first in ((words[0], words[1]), (words[1], words[0])):
            pattern = f"{surname}, {first[0]}%"
            alias.append("(white LIKE ? OR black LIKE ?)")
            alias_params.extend([pattern, pattern])
        return f"(({strict}) OR {' OR '.join(alias)})", params + alias_params

    @staticmethod
    def _name_clause(text, columns):
        """
        Match a player name across the columns given.

        Same two problems as the free-text search: names are stored
        surname-first, and PGN Mentor abbreviates the first name. So each
        word must appear somewhere, and a two-word name is also tried as
        "Surname, Initial".
        """
        words = text.split()
        parts, params = [], []
        for word in words:
            parts.append("(" + " OR ".join(f"{c} LIKE ?" for c in columns) + ")")
            params.extend([f"%{word}%"] * len(columns))
        clause = " AND ".join(parts)

        if len(words) == 2:
            for surname, first in ((words[0], words[1]), (words[1], words[0])):
                pattern = f"{surname}, {first[0]}%"
                clause += " OR (" + " OR ".join(
                    f"{c} LIKE ?" for c in columns) + ")"
                params.extend([pattern] * len(columns))
        return f"({clause})", params

    @staticmethod
    def _where(search='', player='', result='', eco='', min_elo=None,
               year_from=None, year_to=None, source='', titled_only=False,
               color='', opponent='', event=''):
        """Build the shared WHERE clause + params for every masters query."""
        conds, params = [], []

        if search and search.strip():
            clause, args = MastersDB._search_clause(search)
            conds.append(clause)
            params.extend(args)

        # A specific player, optionally restricted to one colour. 'color'
        # is what makes "Carlsen with White" a single click rather than a
        # search the user has to reason about.
        if player and player.strip():
            columns = {"white": ("white",), "black": ("black",)} \
                .get(color, ("white", "black"))
            clause, args = MastersDB._name_clause(player.strip(), columns)
            conds.append(clause)
            params.extend(args)

        # The opponent goes on the other side of the board from the player.
        if opponent and opponent.strip():
            if color == "white":
                columns = ("black",)
            elif color == "black":
                columns = ("white",)
            else:
                columns = ("white", "black")
            clause, args = MastersDB._name_clause(opponent.strip(), columns)
            conds.append(clause)
            params.extend(args)

        if event and event.strip():
            conds.append("event LIKE ?")
            params.append(f"%{event.strip()}%")

        if result:
            conds.append("result = ?")
            params.append(result)

        if eco and eco.strip():
            conds.append("eco LIKE ?")
            params.append(f"{eco.strip().upper()}%")

        if min_elo:
            conds.append("avg_elo >= ?")
            params.append(int(min_elo))

        # Year bounds compare against the 'YYYY' prefix rather than a full
        # date: historic games are stored as '1970-??-??', and '?' sorts
        # *above* '9', so a '1970-12-31' upper bound would drop them.
        if year_from:
            conds.append("date >= ?")
            params.append(f"{int(year_from):04d}")

        if year_to:
            conds.append("date < ?")
            params.append(f"{int(year_to) + 1:04d}")

        if source:
            conds.append("source = ?")
            params.append(source)

        if titled_only:
            conds.append("(white_title != '' OR black_title != '')")

        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        return where, params

    def query(self, sort='date_desc', limit=500, offset=0, **filters):
        """Fetch matching games as a list of dicts (no PGN — that's loaded lazily)."""
        cols = ('id', 'date', 'white', 'black', 'white_title', 'black_title',
                'white_elo', 'black_elo', 'avg_elo', 'result', 'ply_count',
                'opening', 'eco', 'event', 'site', 'round', 'source',
                'source_url')
        try:
            where, params = self._where(**filters)
            order = SORTS.get(sort, SORTS['date_desc'])
            sql = (f"SELECT {', '.join(cols)} FROM master_games{where} "
                   f"ORDER BY {order} LIMIT ? OFFSET ?")
            conn = self._connect()
            rows = conn.execute(sql, params + [int(limit), int(offset)]).fetchall()
            conn.close()
            return [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            print(f"[MastersDB] query error: {e}")
            return []

    def count(self, **filters):
        try:
            where, params = self._where(**filters)
            conn = self._connect()
            n = conn.execute(
                "SELECT COUNT(*) FROM master_games" + where, params).fetchone()[0]
            conn.close()
            return n
        except Exception as e:
            print(f"[MastersDB] count error: {e}")
            return 0

    def get_pgn(self, game_id):
        try:
            conn = self._connect()
            row = conn.execute("SELECT pgn FROM master_games WHERE id = ?",
                               (game_id,)).fetchone()
            conn.close()
            return row[0] if row else None
        except Exception as e:
            print(f"[MastersDB] get_pgn error: {e}")
            return None

    def stats(self):
        """Headline numbers for the view's status bar."""
        try:
            conn = self._connect()
            total = conn.execute("SELECT COUNT(*) FROM master_games").fetchone()[0]
            if not total:
                conn.close()
                return {'total': 0, 'players': 0, 'events': 0,
                        'oldest': '—', 'newest': '—', 'sources': [],
                        'pgn_bytes': 0, 'file_bytes': 0}
            players = conn.execute(
                "SELECT COUNT(*) FROM (SELECT white AS p FROM master_games "
                "UNION SELECT black FROM master_games)").fetchone()[0]
            events = conn.execute(
                "SELECT COUNT(DISTINCT event) FROM master_games").fetchone()[0]
            span = conn.execute(
                "SELECT MIN(date), MAX(date) FROM master_games "
                "WHERE date != ''").fetchone()
            sources = conn.execute(
                "SELECT source, COUNT(*) FROM master_games "
                "GROUP BY source ORDER BY 2 DESC").fetchall()
            conn.close()
            pgn_bytes, file_bytes = self.size_bytes()
            return {'total': total, 'players': players, 'events': events,
                    'oldest': span[0] or '—', 'newest': span[1] or '—',
                    'sources': sources,
                    'pgn_bytes': pgn_bytes, 'file_bytes': file_bytes}
        except Exception as e:
            print(f"[MastersDB] stats error: {e}")
            return {'total': 0, 'players': 0, 'events': 0,
                    'oldest': '—', 'newest': '—', 'sources': [],
                    'pgn_bytes': 0, 'file_bytes': 0}

    def search_players(self, text='', limit=25):
        """
        Player names for the picker, most-played first.

        Deliberately server-side and small: the database holds tens of
        thousands of distinct players, so shipping them all to the browser
        to be filtered there would be a large payload for a list nobody
        scrolls. With no text this returns the most frequent players, which
        is the useful default.

        Returns (names, total_matches) so the caller can say how much was
        left out.
        """
        try:
            conn = self._connect()
            base = ("SELECT p, COUNT(*) n FROM ("
                    "  SELECT white AS p FROM master_games"
                    "  UNION ALL SELECT black FROM master_games) ")
            params = []
            where = ""
            if text and text.strip():
                clause, args = MastersDB._name_clause(text.strip(), ("p",))
                where = f"WHERE {clause} "
                params = args
            rows = conn.execute(
                f"{base}{where}GROUP BY p ORDER BY n DESC LIMIT ?",
                params + [int(limit)]).fetchall()
            total = conn.execute(
                f"SELECT COUNT(*) FROM ({base}{where}GROUP BY p)",
                params).fetchone()[0]
            conn.close()
            return [r[0] for r in rows], total
        except Exception as e:
            print(f"[MastersDB] search_players error: {e}")
            return [], 0

    def search_events(self, text='', limit=25):
        """Event names for the picker, biggest first. See search_players."""
        try:
            conn = self._connect()
            where = "WHERE COALESCE(event,'') != '' "
            params = []
            if text and text.strip():
                for word in text.split():
                    where += "AND event LIKE ? "
                    params.append(f"%{word}%")
            rows = conn.execute(
                f"SELECT event FROM master_games {where}"
                f"GROUP BY event ORDER BY COUNT(*) DESC LIMIT ?",
                params + [int(limit)]).fetchall()
            total = conn.execute(
                f"SELECT COUNT(*) FROM (SELECT 1 FROM master_games {where}"
                f"GROUP BY event)", params).fetchone()[0]
            conn.close()
            return [r[0] for r in rows], total
        except Exception as e:
            print(f"[MastersDB] search_events error: {e}")
            return [], 0

    def top_players(self, limit=40):
        """Most-represented players, for the quick-filter dropdown."""
        try:
            conn = self._connect()
            rows = conn.execute(
                "SELECT p, COUNT(*) n FROM ("
                "  SELECT white AS p FROM master_games"
                "  UNION ALL SELECT black FROM master_games"
                ") GROUP BY p ORDER BY n DESC LIMIT ?", (int(limit),)).fetchall()
            conn.close()
            return rows
        except Exception as e:
            print(f"[MastersDB] top_players error: {e}")
            return []
