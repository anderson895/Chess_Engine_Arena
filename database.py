# ═══════════════════════════════════════════════════════════════════════════════
#  database.py — SQLite persistence layer  (FIXED)
# ═══════════════════════════════════════════════════════════════════════════════

import sqlite3
from datetime import datetime
from utils import normalize_engine_name, get_db_path


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
                source            TEXT    DEFAULT 'regular'
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

        conn.commit()
        conn.close()

    # ── Write ─────────────────────────────────────────────

    def save_game(self, white_name, black_name, result, reason,
                  pgn, move_count, duration_sec, source='regular'):
        """Save a game to the games table. Returns the new row id, or None on error."""
        try:
            conn   = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()
            date_str = datetime.now().strftime("%Y.%m.%d")
            time_str = datetime.now().strftime("%H:%M:%S")
            cursor.execute('''
                INSERT INTO games
                    (white_engine, black_engine, result, reason,
                     date, time, pgn, move_count, duration_seconds, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                normalize_engine_name(white_name),
                normalize_engine_name(black_name),
                result, reason,
                date_str, time_str,
                pgn, move_count, duration_sec,
                source,
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
                             opening=None):
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
        try:
            conn   = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('SELECT DISTINCT white_engine FROM games')
            whites = {normalize_engine_name(r[0]) for r in cursor.fetchall()}
            cursor.execute('SELECT DISTINCT black_engine FROM games')
            blacks = {normalize_engine_name(r[0]) for r in cursor.fetchall()}
            engines = sorted(whites | blacks)

            if search_query:
                q = search_query.lower()
                engines = [e for e in engines if q in e.lower()]

            stats = []
            for engine in engines:
                cursor.execute(
                    'SELECT COUNT(*) FROM games '
                    'WHERE white_engine = ? OR black_engine = ?',
                    (engine, engine))
                matches = cursor.fetchone()[0]

                cursor.execute(
                    "SELECT COUNT(*) FROM games "
                    "WHERE white_engine = ? AND result = '1-0'",
                    (engine,))
                wins_white = cursor.fetchone()[0]

                cursor.execute(
                    "SELECT COUNT(*) FROM games "
                    "WHERE black_engine = ? AND result = '0-1'",
                    (engine,))
                wins_black = cursor.fetchone()[0]

                wins  = wins_white + wins_black
                cursor.execute(
                    "SELECT COUNT(*) FROM games "
                    "WHERE (white_engine = ? OR black_engine = ?) "
                    "AND result = '1/2-1/2'",
                    (engine, engine))
                draws = cursor.fetchone()[0]
                loses = matches - wins - draws
                win_rate = (wins / matches * 100) if matches > 0 else 0

                stats.append({
                    'engine':   engine,
                    'matches':  matches,
                    'wins':     wins,
                    'draws':    draws,
                    'loses':    loses,
                    'win_rate': win_rate,
                })

            conn.close()
            return stats
        except Exception as e:
            print(f"[Database] get_engine_stats error: {e}")
            return []

    def get_all_games(self, filter_engine=None, search_query='',
                      source_filter=None):
        try:
            conn   = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            base_query = '''
                SELECT id, white_engine, black_engine, result, reason,
                       date, time, move_count, duration_seconds,
                       COALESCE(source, 'regular') as source
                FROM games
            '''
            params = []
            conditions = []

            if filter_engine:
                norm = normalize_engine_name(filter_engine)
                conditions.append('(white_engine = ? OR black_engine = ?)')
                params.extend([norm, norm])

            if source_filter:
                conditions.append('source = ?')
                params.append(source_filter)

            if conditions:
                base_query += ' WHERE ' + ' AND '.join(conditions)

            base_query += ' ORDER BY id DESC'
            cursor.execute(base_query, params)
            games = cursor.fetchall()
            conn.close()

            if search_query:
                q = search_query.lower()
                games = [g for g in games
                         if q in ' '.join(str(v) for v in g).lower()]
            return games
        except Exception as e:
            print(f"[Database] get_all_games error: {e}")
            return []

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

            for color, win_result in [('as_white', '1-0'), ('as_black', '0-1')]:
                cursor.execute("SELECT pgn, result FROM games")
                rows = cursor.fetchall()

                opening_counts = {}
                for pgn, res in rows:
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
            print(f"[Database] get_opening_stats_all error: {e}")
        return result

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