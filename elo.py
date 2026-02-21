# ═══════════════════════════════════════════════════════════
#  elo.py — Elo rating computation helpers
# ═══════════════════════════════════════════════════════════

from utils import normalize_engine_name


def compute_elo_ratings(games, k=32, start_elo=1500):
    """
    Compute Elo ratings for all engines from full game history.

    Parameters
    ----------
    games : list of (white_engine, black_engine, result) tuples
        Ordered oldest-first.
    k : int
        K-factor used in Elo update formula (default 32).
    start_elo : int
        Starting Elo for any engine not yet in the system (default 1500).

    Returns
    -------
    dict  — {engine_name: rounded_elo}
    """
    ratings = {}

    def get_r(name):
        return ratings.setdefault(normalize_engine_name(name), start_elo)

    def set_r(name, val):
        ratings[normalize_engine_name(name)] = val

    for white, black, result in games:
        w = normalize_engine_name(white)
        b = normalize_engine_name(black)
        rw = get_r(w)
        rb = get_r(b)
        ew = 1 / (1 + 10 ** ((rb - rw) / 400))
        eb = 1 - ew

        if result == '1-0':
            sw, sb = 1.0, 0.0
        elif result == '0-1':
            sw, sb = 0.0, 1.0
        elif result == '1/2-1/2':
            sw, sb = 0.5, 0.5
        else:
            continue  # skip aborted / no-result games

        set_r(w, rw + k * (sw - ew))
        set_r(b, rb + k * (sb - eb))

    return {n: round(v) for n, v in ratings.items()}


def compute_elo_history(games, engine_name, k=32, start_elo=1500):
    """
    Return the Elo history for a single engine as a list of (game_index, elo) pairs.

    Parameters
    ----------
    games : list of (white_engine, black_engine, result) tuples
        Full game history ordered oldest-first.
    engine_name : str
        Engine whose history we want (color suffixes are stripped automatically).
    k : int
        K-factor (default 32).
    start_elo : int
        Starting Elo (default 1500).

    Returns
    -------
    list of (int, int)  — [(game_number, elo), ...]
    """
    ratings = {}
    history = []
    engine_name = normalize_engine_name(engine_name)

    def get_r(name):
        return ratings.setdefault(normalize_engine_name(name), start_elo)

    def set_r(name, val):
        ratings[normalize_engine_name(name)] = val

    for i, (white, black, result) in enumerate(games):
        w = normalize_engine_name(white)
        b = normalize_engine_name(black)
        rw = get_r(w)
        rb = get_r(b)
        ew = 1 / (1 + 10 ** ((rb - rw) / 400))
        eb = 1 - ew

        if result == '1-0':
            sw, sb = 1.0, 0.0
        elif result == '0-1':
            sw, sb = 0.0, 1.0
        elif result == '1/2-1/2':
            sw, sb = 0.5, 0.5
        else:
            continue

        set_r(w, rw + k * (sw - ew))
        set_r(b, rb + k * (sb - eb))

        if w == engine_name or b == engine_name:
            history.append((len(history) + 1, round(get_r(engine_name))))

    return history
