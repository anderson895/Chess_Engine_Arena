# ═══════════════════════════════════════════════════════════════════════════════
#  database.py — SQLite persistence layer  (FIXED)
# ═══════════════════════════════════════════════════════════════════════════════

import sqlite3
from datetime import datetime
from core.utils import normalize_engine_name, get_db_path


class Database:
    """
    Thin wrapper around the SQLite game database.

    All engine names are normalised (color suffixes stripped) before
    storing or querying so that "Stockfish (White)" and "Stockfish (Black)"
    are treated as the same engine.
    """

    def __init__(self, db_path=None):
        self.db_path = db_path or get_db_path()
        self._init_schema()

    # ── Schema ────────────────────────────────────────────

    def _init_schema(self):
        """Create the games and tournament_games tables if they do not exist yet."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        # Main games table (regular + tournament games)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS games (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                white_engine      TEXT    NOT NULL,
                black_engine      TEXT    NOT NULL,
                result            TEXT    NOT NULL,
                reason            TEXT    NOT NULL,
                date              TEXT    NOT NULL,
                time              TEXT    NOT NULL,
                pgn               TEXT    NOT NULL,
                move_count        INTEGER,
                duration_seconds  INTEGER,
                source            TEXT    DEFAULT 'regular',
                time_control      TEXT    DEFAULT ''
            )
        ''')

        # Tournament-specific metadata table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS tournament_games (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id         INTEGER REFERENCES games(id) ON DELETE CASCADE,
                tournament_id   TEXT    NOT NULL,
                tournament_name TEXT    NOT NULL,
                format          TEXT    NOT NULL,
                round_num       INTEGER NOT NULL,
                white_engine    TEXT    NOT NULL,
                black_engine    TEXT    NOT NULL,
                result          TEXT    NOT NULL,
                reason          TEXT    NOT NULL,
                pgn             TEXT    NOT NULL,
                move_count      INTEGER,
                duration_sec    INTEGER,
                opening         TEXT,
                date            TEXT    NOT NULL,
                time            TEXT    NOT NULL
            )
        ''')

        # Add 'source' column to existing games table if missing (migration)
        try:
            conn.execute("ALTER TABLE games ADD COLUMN source TEXT DEFAULT 'regular'")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Add 'time_control' column if missing (migration)
        try:
            conn.execute("ALTER TABLE games ADD COLUMN time_control TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Games recorded before time controls existed were played without
        # a clock — label them 'Classic' (idempotent: only fills blanks)
        conn.execute("UPDATE games SET time_control = 'Classic' "
                     "WHERE COALESCE(time_control, '') = ''")

        # Add 'opening' column if missing (migration) and backfill it from
        # the PGN's [Opening "..."] header (idempotent: only fills blanks)
        try:
            conn.execute("ALTER TABLE games ADD COLUMN opening TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # Column already exists
        conn.execute('''
            UPDATE games SET opening =
                substr(pgn, instr(pgn, '[Opening "') + 10,
                       instr(substr(pgn, instr(pgn, '[Opening "') + 10), '"') - 1)
            WHERE COALESCE(opening, '') = ''
              AND instr(pgn, '[Opening "') > 0
        ''')

        conn.commit()
        conn.close()

    # ── Write ─────────────────────────────────────────────

    def save_game(self, white_name, black_name, result, reason,
                  pgn, move_count, duration_sec, source='regular',
                  time_control='', opening=''):
        """Save a game to the games table. Returns the new row id, or None on
        error.

        Two kinds of game are rejected outright, because recording them
        would pollute the rankings with results that say nothing about
        playing strength:

        - Self-play (same engine on both sides) — unrated, and storing it
          desyncs the history count from the ranking count.
        - Forfeits caused by an engine malfunctioning: returning no move
          (crash or hang) or playing an illegal move. Neither is a game.
        """
        if normalize_engine_name(white_name) == normalize_engine_name(black_name):
            print(f"[Database] refusing to save self-play game: "
                  f"{normalize_engine_name(white_name)}")
            return None
        r = reason or ''
        if 'returned no move' in r or 'Illegal move by' in r:
            print(f"[Database] refusing to save malfunction game: {reason}")
            return None
        try:
            conn   = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()
            date_str = datetime.now().strftime("%Y.%m.%d")
            time_str = datetime.now().strftime("%H:%M:%S")
            cursor.execute('''
                INSERT INTO games
                    (white_engine, black_engine, result, reason,
                     date, time, pgn, move_count, duration_seconds, source,
                     time_control, opening)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                normalize_engine_name(white_name),
                normalize_engine_name(black_name),
                result, reason,
                date_str, time_str,
                pgn, move_count, duration_sec,
                source,
                time_control or '',
                opening or '',
            ))
            conn.commit()
            game_id = cursor.lastrowid
            conn.close()
            return game_id
        except Exception as e:
            print(f"[Database] save_game error: {e}")
            return None

    def save_tournament_game(self, tournament_id, tournament_name, fmt,
                             round_num, white_name, black_name, result,
                             reason, pgn, move_count, duration_sec,
                             opening=None, time_control=''):
        try:
            # 1. Save to main games table so Elo / stats pick it up
            game_id = self.save_game(
                white_name   = white_name,
                black_name   = black_name,
                result       = result,
                reason       = reason,
                pgn          = pgn,
                move_count   = move_count,
                duration_sec = duration_sec,
                source       = 'tournament',
                time_control = time_control,
                opening      = opening or '',
            )
            if game_id is None:
                return None, None

            # 2. Save tournament metadata
            conn   = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()
            now      = datetime.now()
            date_str = now.strftime("%Y.%m.%d")
            time_str = now.strftime("%H:%M:%S")
            cursor.execute('''
                INSERT INTO tournament_games
                    (game_id, tournament_id, tournament_name, format,
                     round_num, white_engine, black_engine, result, reason,
                     pgn, move_count, duration_sec, opening, date, time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                game_id,
                tournament_id,
                tournament_name,
                fmt,
                round_num,
                normalize_engine_name(white_name),
                normalize_engine_name(black_name),
                result,
                reason,
                pgn,
                move_count,
                duration_sec,
                opening or '',
                date_str,
                time_str,
            ))
            conn.commit()
            t_game_id = cursor.lastrowid
            conn.close()
            return game_id, t_game_id

        except Exception as e:
            print(f"[Database] save_tournament_game error: {e}")
            return None, None

    def rename_engine(self, old_name, new_name):
        """
        Rename an engine everywhere: games, tournament_games and the
        [White]/[Black] tags inside stored PGN text.

        Returns the number of game rows that referenced the engine,
        or -1 on error.
        """
        import re
        old = normalize_engine_name(old_name)
        new = normalize_engine_name(new_name)
        if not old or not new or old == new:
            return 0
        try:
            conn   = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()

            count = cursor.execute(
                "SELECT COUNT(*) FROM games "
                "WHERE white_engine = ? OR black_engine = ?",
                (old, old)).fetchone()[0]

            for table in ("games", "tournament_games"):
                cursor.execute(
                    f"UPDATE {table} SET white_engine = ? WHERE white_engine = ?",
                    (new, old))
                cursor.execute(
                    f"UPDATE {table} SET black_engine = ? WHERE black_engine = ?",
                    (new, old))

                # Rewrite PGN [White]/[Black] tags (values may still carry
                # color suffixes, so compare normalized)
                def _fix_pgn(pgn):
                    def repl(m):
                        if normalize_engine_name(m.group(2)) == old:
                            return f'[{m.group(1)} "{new}"]'
                        return m.group(0)
                    return re.sub(r'\[(White|Black)\s+"([^"]*)"\]',
                                  repl, pgn or '')

                id_col = "id"
                for gid, pgn in cursor.execute(
                        f"SELECT {id_col}, pgn FROM {table}").fetchall():
                    fixed = _fix_pgn(pgn)
                    if fixed != pgn:
                        cursor.execute(
                            f"UPDATE {table} SET pgn = ? WHERE {id_col} = ?",
                            (fixed, gid))

            conn.commit()
            conn.close()
            return count
        except Exception as e:
            print(f"[Database] rename_engine error: {e}")
            return -1

    def delete_game(self, game_id):
        """Delete a game (and its tournament metadata). Returns True on success."""
        try:
            conn   = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM tournament_games WHERE game_id = ?", (game_id,))
            cursor.execute("DELETE FROM games WHERE id = ?", (game_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return deleted
        except Exception as e:
            print(f"[Database] delete_game error: {e}")
            return False

    # ── Read ──────────────────────────────────────────────

    def get_all_games_for_elo(self):
        try:
            conn   = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT white_engine, black_engine, result "
                "FROM games ORDER BY id ASC")
            rows = cursor.fetchall()
            conn.close()
            return rows
        except Exception as e:
            print(f"[Database] get_all_games_for_elo error: {e}")
            return []

    def get_engine_stats(self, search_query=''):
        """
        Aggregate W/D/L stats per engine in a single pass over the games
        table (the previous version issued 4 queries per engine).

        Notes
        -----
        - Engine names are normalised in Python so legacy rows that were
          stored with color suffixes still aggregate correctly.
        - Games without a decisive/draw result ('*', aborted) are skipped,
          matching how Elo is computed.
        """
        try:
            conn   = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT white_engine, black_engine, result FROM games')
            rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            print(f"[Database] get_engine_stats error: {e}")
            return []

        agg = {}

        def rec(name):
            return agg.setdefault(
                normalize_engine_name(name),
                {'matches': 0, 'wins': 0, 'draws': 0, 'loses': 0})

        for white, black, result in rows:
            if result not in ('1-0', '0-1', '1/2-1/2'):
                continue   # aborted / unfinished games don't count
            if normalize_engine_name(white) == normalize_engine_name(black):
                continue   # self-play is unrated (see core.elo)
            w, b = rec(white), rec(black)
            w['matches'] += 1
            b['matches'] += 1
            if result == '1-0':
                w['wins']  += 1
                b['loses'] += 1
            elif result == '0-1':
                b['wins']  += 1
                w['loses'] += 1
            else:
                w['draws'] += 1
                b['draws'] += 1

        engines = sorted(agg)
        if search_query:
            q = search_query.lower()
            engines = [e for e in engines if q in e.lower()]

        return [
            {
                'engine':   engine,
                'win_rate': (agg[engine]['wins'] / agg[engine]['matches'] * 100)
                            if agg[engine]['matches'] else 0.0,
                **agg[engine],
            }
            for engine in engines
        ]

    def get_time_control_stats(self):
        """
        Per-engine W/D/L records grouped by time control.

        Returns
        -------
        dict: {engine: {time_control_label: {'wins', 'draws', 'loses'}}}
        Games saved before time controls existed group under 'Classic'.
        """
        try:
            rows = self.get_all_games_for_elo_tc()
        except Exception as e:
            print(f"[Database] get_time_control_stats error: {e}")
            return {}

        stats = {}
        for white, black, result, tc in rows:
            if result not in ('1-0', '0-1', '1/2-1/2'):
                continue
            if normalize_engine_name(white) == normalize_engine_name(black):
                continue   # self-play is unrated (see core.elo)
            tc = tc or 'Classic'
            for name, win_res in ((white, '1-0'), (black, '0-1')):
                rec = stats.setdefault(
                    normalize_engine_name(name), {}).setdefault(
                    tc, {'wins': 0, 'draws': 0, 'loses': 0})
                if result == '1/2-1/2':
                    rec['draws'] += 1
                elif result == win_res:
                    rec['wins'] += 1
                else:
                    rec['loses'] += 1
        return stats

    def get_all_games_for_elo_tc(self):
        """Elo input rows with time control: (white, black, result, tc),
        ordered oldest-first."""
        try:
            conn   = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT white_engine, black_engine, result, "
                "COALESCE(time_control, '') FROM games ORDER BY id ASC")
            rows = cursor.fetchall()
            conn.close()
            return rows
        except Exception as e:
            print(f"[Database] get_all_games_for_elo_tc error: {e}")
            return []

    @staticmethod
    def _games_where(filter_engine=None, search_query='', source_filter=None):
        """Build the shared WHERE clause + params for game queries."""
        params = []
        conditions = []
        if filter_engine:
            norm = normalize_engine_name(filter_engine)
            conditions.append('(white_engine = ? OR black_engine = ?)')
            params.extend([norm, norm])
        if source_filter:
            conditions.append("COALESCE(source, 'regular') = ?")
            params.append(source_filter)
        if search_query and search_query.strip():
            q = f'%{search_query.strip()}%'
            conditions.append(
                '(white_engine LIKE ? OR black_engine LIKE ? OR result LIKE ? '
                'OR reason LIKE ? OR date LIKE ? '
                "OR COALESCE(opening, '') LIKE ?)")
            params.extend([q] * 6)
        where = (' WHERE ' + ' AND '.join(conditions)) if conditions else ''
        return where, params

    def get_all_games(self, filter_engine=None, search_query='',
                      source_filter=None, limit=None):
        """
        Fetch games newest-first. Search runs in SQL and *limit* caps the
        result set so huge databases never flood the query or the UI.
        """
        try:
            conn   = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            where, params = self._games_where(
                filter_engine, search_query, source_filter)
            query = ('''
                SELECT id, white_engine, black_engine, result, reason,
                       date, time, move_count, duration_seconds,
                       COALESCE(source, 'regular') as source,
                       COALESCE(time_control, '') as time_control,
                       COALESCE(opening, '') as opening
                FROM games''' + where + ' ORDER BY id DESC')
            if limit:
                query += ' LIMIT ?'
                params = params + [int(limit)]
            cursor.execute(query, params)
            games = cursor.fetchall()
            conn.close()
            return games
        except Exception as e:
            print(f"[Database] get_all_games error: {e}")
            return []

    def count_games(self, filter_engine=None, search_query='',
                    source_filter=None):
        """Total games matching the same filters as get_all_games."""
        try:
            conn   = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            where, params = self._games_where(
                filter_engine, search_query, source_filter)
            cursor.execute('SELECT COUNT(*) FROM games' + where, params)
            n = cursor.fetchone()[0]
            conn.close()
            return n
        except Exception as e:
            print(f"[Database] count_games error: {e}")
            return 0

    def get_game_pgn(self, game_id):
        """
        Fetch the PGN text for a specific game by its database id.

        Returns
        -------
        str | None
        """
        try:
            conn   = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT pgn FROM games WHERE id = ?', (game_id,))
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else None
        except Exception as e:
            print(f"[Database] get_game_pgn error: {e}")
            return None

    def get_tournament_games(self, tournament_id=None, tournament_name=None):
        """
        Fetch tournament game rows with metadata.

        Parameters
        ----------
        tournament_id   : str | None  — filter by exact tournament id
        tournament_name : str | None  — filter by tournament name (substring)

        Returns
        -------
        list of dicts with all tournament_games columns
        """
        try:
            conn   = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query  = 'SELECT * FROM tournament_games'
            params = []
            conditions = []

            if tournament_id:
                conditions.append('tournament_id = ?')
                params.append(tournament_id)
            if tournament_name:
                conditions.append('tournament_name LIKE ?')
                params.append(f'%{tournament_name}%')

            if conditions:
                query += ' WHERE ' + ' AND '.join(conditions)
            query += ' ORDER BY id ASC'

            cursor.execute(query, params)
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            print(f"[Database] get_tournament_games error: {e}")
            return []

    def get_opening_stats(self, engine_name, top_n=10):
        """
        Return the most common openings used by an engine as White and as Black.

        Parameters
        ----------
        engine_name : str   — engine name (color suffixes stripped automatically)
        top_n       : int   — how many top openings to return per color

        Returns
        -------
        dict with keys 'as_white' and 'as_black', each a list of dicts:
            {opening, games, wins, draws, losses, win_rate}
        Opening name is extracted from the PGN [Opening "..."] tag.
        Games without an Opening tag are grouped as "Unknown / No Opening".
        """
        import re
        norm = normalize_engine_name(engine_name)
        result = {'as_white': [], 'as_black': []}

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            for color, col_self, col_opp, win_result in [
                ('as_white', 'white_engine', 'black_engine', '1-0'),
                ('as_black',  'black_engine', 'white_engine', '0-1'),
            ]:
                cursor.execute(
                    f"SELECT pgn, result FROM games WHERE {col_self} = ?",
                    (norm,))
                rows = cursor.fetchall()

                opening_counts = {}
                for pgn, res in rows:
                    # Extract [Opening "..."] tag from PGN header
                    m = re.search(r'\[Opening\s+"([^"]+)"\]', pgn or '')
                    opening = m.group(1).strip() if m else "Unknown / No Opening"
                    if opening not in opening_counts:
                        opening_counts[opening] = {'games': 0, 'wins': 0,
                                                   'draws': 0, 'losses': 0}
                    d = opening_counts[opening]
                    d['games'] += 1
                    if res == win_result:
                        d['wins'] += 1
                    elif res == '1/2-1/2':
                        d['draws'] += 1
                    else:
                        d['losses'] += 1

                sorted_openings = sorted(
                    opening_counts.items(),
                    key=lambda x: x[1]['games'],
                    reverse=True)[:top_n]

                result[color] = [
                    {
                        'opening':  name,
                        'games':    d['games'],
                        'wins':     d['wins'],
                        'draws':    d['draws'],
                        'losses':   d['losses'],
                        'win_rate': round(d['wins'] / d['games'] * 100, 1)
                                    if d['games'] > 0 else 0.0,
                    }
                    for name, d in sorted_openings
                ]

            conn.close()
        except Exception as e:
            print(f"[Database] get_opening_stats error: {e}")

        return result

    def get_opening_stats_all(self, top_n=10):
        """
        Aggregate opening statistics across ALL engines.

        Returns
        -------
        dict with keys 'as_white' and 'as_black', same format as get_opening_stats.
        """
        import re
        result = {'as_white': [], 'as_black': []}
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT pgn, result FROM games")
            rows = cursor.fetchall()
            conn.close()

            # Parse the Opening tag once per game, then aggregate per color.
            parsed = []
            for pgn, res in rows:
                m = re.search(r'\[Opening\s+"([^"]+)"\]', pgn or '')
                opening = m.group(1).strip() if m else "Unknown / No Opening"
                parsed.append((opening, res))

            for color, win_result in [('as_white', '1-0'), ('as_black', '0-1')]:
                opening_counts = {}
                for opening, res in parsed:
                    d = opening_counts.setdefault(
                        opening, {'games': 0, 'wins': 0, 'draws': 0, 'losses': 0})
                    d['games'] += 1
                    if res == win_result:
                        d['wins'] += 1
                    elif res == '1/2-1/2':
                        d['draws'] += 1
                    else:
                        d['losses'] += 1

                sorted_openings = sorted(
                    opening_counts.items(),
                    key=lambda x: x[1]['games'],
                    reverse=True)[:top_n]

                result[color] = [
                    {
                        'opening':  name,
                        'games':    d['games'],
                        'wins':     d['wins'],
                        'draws':    d['draws'],
                        'losses':   d['losses'],
                        'win_rate': round(d['wins'] / d['games'] * 100, 1)
                                    if d['games'] > 0 else 0.0,
                    }
                    for name, d in sorted_openings
                ]
        except Exception as e:
            print(f"[Database] get_opening_stats_all error: {e}")
        return result

    def get_top_openings(self):
        """
        Return each engine's most-played opening (both colors combined).

        Returns
        -------
        dict: {engine_name: {'opening': str, 'games': int}}
        Games without an [Opening "..."] tag are ignored, so an engine that
        never played a book line simply has no entry.
        """
        import re
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                'SELECT white_engine, black_engine, pgn FROM games')
            rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            print(f"[Database] get_top_openings error: {e}")
            return {}

        counts = {}   # engine -> {opening: games}
        for white, black, pgn in rows:
            m = re.search(r'\[Opening\s+"([^"]+)"\]', pgn or '')
            if not m:
                continue
            opening = m.group(1).strip()
            for name in (white, black):
                eng = normalize_engine_name(name)
                per = counts.setdefault(eng, {})
                per[opening] = per.get(opening, 0) + 1

        return {
            eng: {'opening': top[0], 'games': top[1]}
            for eng, per in counts.items()
            for top in [max(per.items(), key=lambda x: x[1])]
        }

    def get_tournament_list(self):
        """
        Return a summary list of all tournaments stored in the database.

        Returns
        -------
        list of dicts:
            tournament_id, tournament_name, format, game_count,
            date (of first game)

        FIX: ORDER BY uses MIN(date) DESC so newest-first ordering is correct
             even when rowid ordering differs from date ordering.
        """
        try:
            conn   = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT tournament_id,
                       tournament_name,
                       format,
                       COUNT(*)  AS game_count,
                       MIN(date) AS date
                FROM tournament_games
                GROUP BY tournament_id
                ORDER BY MAX(id) DESC
            ''')
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            print(f"[Database] get_tournament_list error: {e}")
            return []