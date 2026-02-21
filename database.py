# ═══════════════════════════════════════════════════════════
#  database.py — SQLite persistence layer
# ═══════════════════════════════════════════════════════════

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
        """Create the games table if it does not exist yet."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
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
                duration_seconds  INTEGER
            )
        ''')
        conn.commit()
        conn.close()

    # ── Write ─────────────────────────────────────────────

    def save_game(self, white_name, black_name, result, reason,
                  pgn, move_count, duration_sec):
        """
        Persist one completed game to the database.

        Parameters
        ----------
        white_name : str
        black_name : str
        result     : str  e.g. "1-0", "0-1", "1/2-1/2", "*"
        reason     : str  e.g. "Checkmate"
        pgn        : str  full PGN text
        move_count : int  total half-moves (plies)
        duration_sec : int  game duration in seconds
        """
        try:
            conn   = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()
            date_str = datetime.now().strftime("%Y.%m.%d")
            time_str = datetime.now().strftime("%H:%M:%S")
            cursor.execute('''
                INSERT INTO games
                    (white_engine, black_engine, result, reason,
                     date, time, pgn, move_count, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                normalize_engine_name(white_name),
                normalize_engine_name(black_name),
                result, reason,
                date_str, time_str,
                pgn, move_count, duration_sec,
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Database] save_game error: {e}")

    # ── Read ──────────────────────────────────────────────

    def get_all_games_for_elo(self):
        """
        Return all games ordered oldest-first, for Elo computation.

        Returns
        -------
        list of (white_engine, black_engine, result) tuples
        """
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
        Aggregate win / draw / loss stats per engine.

        Parameters
        ----------
        search_query : str
            Optional substring filter applied to engine names.

        Returns
        -------
        list of dicts with keys:
            engine, matches, wins, draws, loses, win_rate
        """
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

    def get_all_games(self, filter_engine=None, search_query=''):
        """
        Fetch game rows for the history window.

        Parameters
        ----------
        filter_engine : str | None
            If set, only games involving this engine are returned.
        search_query : str
            Optional full-text substring filter.

        Returns
        -------
        list of tuples:
            (id, white_engine, black_engine, result, reason,
             date, time, move_count, duration_seconds)
        """
        try:
            conn   = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            if filter_engine:
                norm = normalize_engine_name(filter_engine)
                cursor.execute(
                    '''SELECT id, white_engine, black_engine, result, reason,
                              date, time, move_count, duration_seconds
                       FROM games
                       WHERE white_engine = ? OR black_engine = ?
                       ORDER BY id DESC''',
                    (norm, norm))
            else:
                cursor.execute(
                    '''SELECT id, white_engine, black_engine, result, reason,
                              date, time, move_count, duration_seconds
                       FROM games ORDER BY id DESC''')

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
