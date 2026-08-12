# ═══════════════════════════════════════════════════════════
#  elo.py — Elo rating computation helpers
# ═══════════════════════════════════════════════════════════

import math

from core.scale import ARENA_ORIGIN
from core.utils import normalize_engine_name

# Engines under this many games in a bucket have no rating worth showing:
# a 1500 that came out of one game is the starting value, not a
# measurement, and putting it beside a number built on 180 games invites
# them to be read as equals.
MIN_RATED_GAMES = 10


def tc_bucket(time_control):
    """
    The rating bucket a stored time_control belongs to.

    Games record the label ("Bullet (1+0)") while presets are keyed
    ("bullet"), so both are reduced to the first bare word. Anything
    unrecognised — including rows saved before the column existed —
    counts as Classic, which is what the app played back then.
    """
    return (time_control or "Classic").split(" ")[0].split("(")[0] \
        .strip().lower() or "classic"


# Elo's 400-point scale expressed for the logistic that produces it
_SCALE = 400 / math.log(10)

# Virtual drawn games against an opponent fixed at start_elo, added to
# every engine. Results alone do not always determine a rating: an engine
# that lost all thirteen of its games is consistent with any rating below
# its opponents, and the fit would send it to minus infinity looking for
# the best one. Two virtual draws say "and it held an average engine
# twice", which bounds it without meaning much once real games pile up.
_PRIOR_GAMES = 2.0

_SCORES = {'1-0': (1.0, 0.0), '0-1': (0.0, 1.0), '1/2-1/2': (0.5, 0.5)}

# Reported margins are 95% intervals, the convention every published
# rating list uses for a "±" — so a quoted 2900 ±90 means the games are
# consistent with anything from 2810 to 2990.
_CONFIDENCE = 1.96


def fit_elo_ratings(games, start_elo=ARENA_ORIGIN, sweeps=200, tol=0.05):
    """
    Ratings that best explain every result at once.

    The sequential update this replaces reads each game in turn and
    forgets it, so the answer depends on the order the games happen to be
    in — shuffling the same 3181 games moved ratings by up to 92 points —
    and it converges too slowly to open the field up: an engine only ever
    gets K-sized nudges away from where it started, so 36 games leave it
    bunched near start_elo whatever it did in them.

    This solves for the ratings instead. Each engine's rating is moved to
    where its expected score matches what it actually scored, by Newton
    steps against the other engines held still, sweeping until nothing
    moves. Order cannot matter because no game is ever "next", and the
    spread comes out at whatever the results imply — on the same data it
    roughly doubled, 511 points to 979.

    Every rating comes from the games passed in and nothing else. There
    is deliberately no way to pin an engine to a published rating — see
    core/scale.py for the measurements that ruled it out.

    Parameters
    ----------
    games : list of (white, black, result) tuples
    start_elo : the origin, and what the virtual prior draws are played
        against. Cosmetic: it shifts every engine equally.

    Returns
    -------
    dict — {engine_name: (elo, margin)}, margin a 95% interval
    """
    # Per-engine (opponent index, score) so a sweep never rescans the list
    index, opponents = {}, []

    def slot(name):
        if name not in index:
            index[name] = len(opponents)
            opponents.append([])
        return index[name]

    for white, black, result in games:
        scores = _SCORES.get(result)
        if scores is None:
            continue            # aborted / no result, as before
        w = normalize_engine_name(white)
        b = normalize_engine_name(black)
        if w == b:
            continue            # self-play carries no rating information
        i, j = slot(w), slot(b)
        opponents[i].append((j, scores[0]))
        opponents[j].append((i, scores[1]))

    names = [None] * len(index)
    for name, i in index.items():
        names[i] = name
    base = float(start_elo)
    ratings = [base] * len(names)

    slopes = [1.0] * len(names)

    for _ in range(sweeps):
        moved = 0.0
        for i, played in enumerate(opponents):
            r = ratings[i]
            # The virtual draws, as an extra opponent sitting at start_elo
            e0 = 1.0 / (1.0 + math.exp((base - r) / _SCALE))
            actual = 0.5 * _PRIOR_GAMES
            expected = e0 * _PRIOR_GAMES
            slope = _PRIOR_GAMES * e0 * (1.0 - e0) / _SCALE
            for j, score in played:
                e = 1.0 / (1.0 + math.exp((ratings[j] - r) / _SCALE))
                actual += score
                expected += e
                slope += e * (1.0 - e) / _SCALE
            # Newton step on this engine alone, the rest held still
            step = (actual - expected) / slope
            ratings[i] = r + step
            slopes[i] = slope
            moved = max(moved, abs(step))
        if moved < tol:
            break

    # The curvature the Newton step divided by is also what says how well
    # the games pin the rating down: a lot of games against opponents of
    # similar strength make it steep and the rating precise, while games
    # already decided by a mismatch barely move it. Every draw-heavy game
    # against a near equal is worth several against an engine two tiers
    # away, which is why the margin does not follow the game count alone.
    return {n: (round(ratings[i]),
                round(_CONFIDENCE * math.sqrt(_SCALE / slopes[i])))
            for n, i in index.items()}


def compute_elo_by_tc(rows, start_elo=ARENA_ORIGIN):
    """
    Ratings computed separately for each time control.

    A Classic game gives both sides the same fixed think time per move
    while Bullet makes them budget a whole minute, and an engine is not
    equally strong at the two — a pre-NNUE search that holds up at depth
    collapses when the clock is what runs out. Pooling them averages the
    answers to two different questions, so each bucket is rated on its
    own games and nothing crosses between them.

    Parameters
    ----------
    rows : list of (white, black, result, time_control) tuples
        Order is irrelevant to fit_elo_ratings, but they arrive
        oldest-first from get_all_games_for_elo_tc.

    Returns
    -------
    dict — {bucket: {engine_name: (elo, margin)}}
    """
    buckets = {}
    for white, black, result, tc in rows:
        buckets.setdefault(tc_bucket(tc), []).append((white, black, result))
    return {key: fit_elo_ratings(games, start_elo)
            for key, games in buckets.items()}


def tally_by_tc(rows):
    """
    {bucket: {engine: {games, wins, draws, losses}}} over the same rows.

    Counts exactly what the rating pass counts, so an engine is never
    called provisional on games that were then thrown away: aborted
    results and self-play are skipped here for the reason they are
    skipped there. W/D/L rides along because it comes free from the walk
    and every caller that wants the game count wants the record too.
    """
    tallies = {}
    for white, black, result, tc in rows:
        if result not in ('1-0', '0-1', '1/2-1/2'):
            continue
        w = normalize_engine_name(white)
        b = normalize_engine_name(black)
        if w == b:
            continue
        bucket = tallies.setdefault(tc_bucket(tc), {})
        for name, won in ((w, result == '1-0'), (b, result == '0-1')):
            rec = bucket.setdefault(
                name, {"games": 0, "wins": 0, "draws": 0, "losses": 0})
            rec["games"] += 1
            if result == '1/2-1/2':
                rec["draws"] += 1
            elif won:
                rec["wins"] += 1
            else:
                rec["losses"] += 1
    return tallies


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
        if w == b:
            # Self-play carries no rating information, and applying both
            # updates to one name would just overwrite the first with the
            # second (a free ±K swing).
            continue
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


def fit_elo_history(games, engine_name, points=40, start_elo=ARENA_ORIGIN):
    """
    One engine's fitted rating as the evidence for it accumulated.

    The obvious history is the running total the sequential update leaves
    behind, but that answers a different question from the rating on
    display: it is where the tally happened to be after game n, not what
    the results up to game n implied. The two disagree, and a chart whose
    last point is not the number beside it is worse than no chart.

    So each point is a fit over the games played up to it. That costs a
    fit per point, which is why the curve is sampled rather than drawn
    once per game — the last point is always the full history, so it
    always matches.

    Returns
    -------
    list of (games_played, elo) — x counts this engine's own games.
    """
    name = normalize_engine_name(engine_name)
    marks = []                    # (engine's games so far, prefix length)
    played = 0
    for i, (white, black, result) in enumerate(games):
        if result not in _SCORES:
            continue
        w = normalize_engine_name(white)
        b = normalize_engine_name(black)
        if w == b or name not in (w, b):
            continue
        played += 1
        marks.append((played, i + 1))
    if not marks:
        return []
    if len(marks) > points:
        step = (len(marks) - 1) / (points - 1)
        marks = sorted({marks[round(n * step)] for n in range(points)})
    # The final point reads the whole bucket, not just up to this engine's
    # last game. Opponents that played on afterwards moved their own
    # ratings, and that moves this one — cutting the fit short there would
    # end the chart a few points off the rating the rankings show.
    marks[-1] = (marks[-1][0], len(games))
    return [(n, fit_elo_ratings(games[:cut], start_elo).get(
        name, (start_elo, 0))[0]) for n, cut in marks]
