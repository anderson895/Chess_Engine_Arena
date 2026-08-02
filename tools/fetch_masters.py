# ═══════════════════════════════════════════════════════════════════════════════
#  fetch_masters.py — Pull real human games (GM / IM / titled players) into the
#  master_games table.
#
#  Sources, all free and key-less:
#    lichess-broadcast  OTB tournaments relayed live by Lichess. Real names,
#                       FIDE IDs, Elo, ECO. The best source for official events.
#    chesscom           Chess.com Published-Data API — monthly archives of any
#                       player, plus the titled-player directory.
#    lichess            Lichess games export for a single account.
#    twic               The Week in Chess weekly PGN zips (bulk historical).
#
#  Standard library only — no extra dependencies.
#
#  Usage:
#    python -m tools.fetch_masters broadcasts --pages 3
#    python -m tools.fetch_masters chesscom --player hikaru --months 6
#    python -m tools.fetch_masters titled --title GM --players 20 --months 2
#    python -m tools.fetch_masters lichess --player DrNykterstein --max 200
#    python -m tools.fetch_masters twic --from 1650 --to 1655
#    python -m tools.fetch_masters file --path games.pgn
#    python -m tools.fetch_masters stats
# ═══════════════════════════════════════════════════════════════════════════════

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from data.masters import MastersDB

# Chess.com etiquette: identify yourself so they can reach you if your client
# misbehaves. Lichess asks the same.
USER_AGENT = ("ChessEngineArena/1.0 (https://github.com/JARP; "
              "masters-import script)")

LICHESS = "https://lichess.org"
CHESSCOM = "https://api.chess.com/pub"
TWIC = "https://theweekinchess.com/zips"
PGNMENTOR = "https://www.pgnmentor.com"


# ── HTTP ───────────────────────────────────────────────────────

def _get(url, accept=None, retries=4, timeout=60):
    """
    GET a URL, returning raw bytes.

    Backs off on 429 (both APIs rate-limit rather than ban) and returns None
    on 404 so a missing month or round just skips instead of aborting a run.
    """
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    delay = 2
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                print(f"    HTTP {e.code} — retrying in {delay}s")
                time.sleep(delay)
                delay *= 2
                continue
            print(f"    HTTP {e.code} for {url}")
            return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            print(f"    error for {url}: {e}")
            return None
    return None


def _get_json(url):
    raw = _get(url, accept="application/json")
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as e:
        print(f"    bad JSON from {url}: {e}")
        return None


def _get_pgn(url):
    raw = _get(url, accept="application/x-chess-pgn")
    if not raw:
        return ""
    # Broadcast and TWIC PGNs are UTF-8; player names carry accents, so
    # decoding as anything else mangles them.
    return raw.decode("utf-8", "replace").replace("\r\n", "\n")


def inject_title(pgn, username, title):
    """
    Tag a player's games with their title.

    Chess.com's PGN export carries no [WhiteTitle]/[BlackTitle], but when we
    walk the titled-player directory we already know the title, so stamp it
    in — that is what makes the 'Titled only' filter work for this source.
    """
    u = re.escape(username)
    pgn = re.sub(rf'(\[White\s+"{u}"\]\n)', rf'\1[WhiteTitle "{title}"]\n',
                 pgn, flags=re.IGNORECASE)
    pgn = re.sub(rf'(\[Black\s+"{u}"\]\n)', rf'\1[BlackTitle "{title}"]\n',
                 pgn, flags=re.IGNORECASE)
    return pgn


# ── Lichess broadcasts (OTB tournaments) ───────────────────────

def fetch_broadcasts(pages=1, log=print, max_tours=None):
    """
    Every round of every tournament on the Lichess broadcast index.

    Page 1 covers the currently active and most recent events; higher pages
    walk further back through finished ones. A page holds up to 74
    tournaments and each has ~10 rounds, so *max_tours* caps a run that
    would otherwise make hundreds of requests.
    """
    chunks = []
    done = 0
    for page in range(1, int(pages) + 1):
        index = _get_json(f"{LICHESS}/api/broadcast/top?page={page}")
        if not index:
            break

        tours = []
        for key in ("active", "upcoming"):
            tours.extend(index.get(key) or [])
        past = index.get("past") or {}
        tours.extend(past.get("currentPageResults") or [])

        if not tours:
            break
        log(f"  page {page}: {len(tours)} tournaments")

        for entry in tours:
            if max_tours and done >= int(max_tours):
                log(f"  stopping at {done} tournaments (max_tours)")
                return "\n\n".join(chunks)
            tour = (entry.get("tour") or {})
            tid, name = tour.get("id"), tour.get("name", "?")
            if not tid:
                continue
            detail = _get_json(f"{LICHESS}/api/broadcast/{tid}")
            rounds = (detail or {}).get("rounds") or []
            got = 0
            for rnd in rounds:
                pgn = _get_pgn(f"{LICHESS}/api/broadcast/round/{rnd['id']}.pgn")
                if pgn and pgn.strip():
                    chunks.append(pgn)
                    got += pgn.count("[Event ")
            done += 1
            log(f"    {name[:56]:<56} {got:>5} games")
    return "\n\n".join(chunks)


# ── Chess.com published data ───────────────────────────────────

def fetch_chesscom_player(username, months=6, log=print, title=None):
    """
    The last *months* monthly archives for one Chess.com account.

    The archive PGN carries only the handle and no title, so the account's
    public profile is read once to recover both — otherwise 'Titled only'
    can never match a Chess.com import, and the table shows "Hikaru"
    instead of "Nakamura, Hikaru".
    """
    if title is None:
        profile = _get_json(
            f"{CHESSCOM}/player/{urllib.parse.quote(username)}") or {}
        title = profile.get("title") or None
        if title:
            log(f"    {username}: {title} ({profile.get('name') or '?'})")

    data = _get_json(f"{CHESSCOM}/player/{urllib.parse.quote(username)}"
                     f"/games/archives")
    if not data or not data.get("archives"):
        log(f"    no archives for {username}")
        return ""
    urls = data["archives"][-int(months):]
    chunks = []
    for url in urls:
        pgn = _get_pgn(url + "/pgn")
        if not pgn:
            # Older archives occasionally lack the .pgn view; rebuild from JSON.
            js = _get_json(url) or {}
            pgn = "\n\n".join(g.get("pgn", "") for g in js.get("games", []))
        if pgn.strip():
            chunks.append(inject_title(pgn, username, title) if title else pgn)
        log(f"    {url.rsplit('/player/', 1)[-1]:<40} "
            f"{pgn.count('[Event '):>5} games")
        time.sleep(0.35)   # stay under the ~3 archives/sec limit
    return "\n\n".join(chunks)


def fetch_chesscom_titled(title="GM", players=10, months=2, log=print):
    """Archives for the first *players* accounts holding a given title."""
    data = _get_json(f"{CHESSCOM}/titled/{title.upper()}")
    names = (data or {}).get("players") or []
    if not names:
        log(f"    no players for title {title}")
        return ""
    names = names[:int(players)]
    log(f"  {title}: {len(names)} accounts")
    chunks = []
    for name in names:
        log(f"  {name}")
        chunks.append(fetch_chesscom_player(name, months, log,
                                            title=title.upper()))
    return "\n\n".join(c for c in chunks if c)


# ── Lichess account export ─────────────────────────────────────

def fetch_lichess_player(username, max_games=200, rated=True, log=print):
    params = urllib.parse.urlencode({
        "max": int(max_games),
        "rated": str(bool(rated)).lower(),
        "opening": "true",
        "clocks": "false",
        "evals": "false",
    })
    pgn = _get_pgn(f"{LICHESS}/api/games/user/"
                   f"{urllib.parse.quote(username)}?{params}")
    log(f"    {username}: {pgn.count('[Event ')} games")
    return pgn


# ── PGN Mentor (bulk career collections) ───────────────────────

def _decode_pgn(raw):
    """Older archives are CP1252, newer ones UTF-8. Try the strict one first."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")


def _unzip_pgn(raw, label, log=print):
    chunks = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for member in zf.namelist():
                if member.lower().endswith(".pgn"):
                    text = _decode_pgn(zf.read(member))
                    chunks.append(text)
                    log(f"    {label:<28} {text.count('[Event '):>6} games")
    except zipfile.BadZipFile:
        log(f"    {label}: corrupt zip")
    return chunks


def _list_pgnmentor(kind, log=print):
    raw = _get(f"{PGNMENTOR}/files.html")
    if not raw:
        return []
    html = raw.decode("utf-8", "replace")
    names = sorted(set(re.findall(rf'href="{kind}/([^"/]+)\.zip"', html)))
    log(f"  {len(names)} {kind} available")
    return names


def list_pgnmentor_players(log=print):
    """The 250-odd players PGN Mentor publishes career collections for."""
    return _list_pgnmentor("players", log)


def list_pgnmentor_openings(log=print):
    """
    The 233 opening collections.

    Far larger than the player files — every recorded master game in a given
    opening, across all players — so this is the bulk route to a database
    that feels complete rather than a handful of famous careers.
    """
    return _list_pgnmentor("openings", log)


def fetch_pgnmentor(names, kind="players", log=print):
    """
    Download and unzip PGN Mentor collections.

    *kind* is 'players' (whole careers, e.g. 'Carlsen') or 'openings'
    (e.g. 'Vienna', 'SicilianNajdorf').
    """
    if isinstance(names, str):
        names = [names]
    chunks = []
    for name in names:
        name = name.strip()
        if not name:
            continue
        raw = _get(f"{PGNMENTOR}/{kind}/{urllib.parse.quote(name)}.zip")
        if not raw:
            log(f"    {name}: not found in {kind}")
            continue
        chunks.extend(_unzip_pgn(raw, name, log))
        time.sleep(0.4)
    return "\n\n".join(chunks)


# ── The Week in Chess ──────────────────────────────────────────

def fetch_twic(issue_from, issue_to=None, log=print):
    """
    TWIC publishes one zipped PGN per weekly issue.

    Issue numbers are sequential from 1 (Sept 1994); issue 1655 is late
    July 2026, so subtract ~52 per year to reach a target date.
    """
    issue_to = int(issue_to or issue_from)
    chunks = []
    for issue in range(int(issue_from), issue_to + 1):
        raw = _get(f"{TWIC}/twic{issue}g.zip")
        if not raw:
            log(f"    issue {issue}: not available")
            continue
        chunks.extend(_unzip_pgn(raw, f"issue {issue}", log))
        time.sleep(0.5)
    return "\n\n".join(chunks)


# ── Shared database snapshot ───────────────────────────────────

GITHUB_API = "https://api.github.com/repos"
DEFAULT_REPO = "anderson895/Chess_Engine_Arena"
DB_TAG_PREFIX = "db-"
DB_ASSET = "chess_arena.db.bz2"


def find_shared_db(repo=DEFAULT_REPO, log=print):
    """
    Locate the newest published database snapshot.

    Uses the public Releases API directly rather than the gh CLI, because
    this has to work from the packaged .exe, where neither gh nor the
    project source is present.

    Returns (tag, download_url, size_bytes) or None.
    """
    data = _get_json(f"{GITHUB_API}/{repo}/releases?per_page=100")
    if not data:
        log("could not reach the releases API")
        return None
    snapshots = sorted(
        (r for r in data if (r.get("tag_name") or "").startswith(DB_TAG_PREFIX)),
        key=lambda r: r.get("created_at", ""), reverse=True)
    for rel in snapshots:
        for asset in rel.get("assets") or []:
            if asset.get("name") == DB_ASSET:
                return (rel["tag_name"], asset["browser_download_url"],
                        asset.get("size", 0))
    log("no database snapshot published yet")
    return None


def download_shared_db(dest_path, url, total=0, log=print, on_progress=None):
    """
    Stream a .bz2 snapshot to *dest_path*, decompressing as it goes.

    Decompressing during the download avoids ever holding the ~170 MB
    expanded database in memory, and means only one temporary file exists.
    """
    import bz2

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    decomp = bz2.BZ2Decompressor()
    read = 0
    with urllib.request.urlopen(req, timeout=120) as resp, \
            open(dest_path, "wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            read += len(chunk)
            out.write(decomp.decompress(chunk))
            if on_progress:
                on_progress(read, total)
    log(f"downloaded {read / 1048576:.1f} MB, "
        f"expanded to {os.path.getsize(dest_path) / 1048576:.1f} MB")
    return dest_path


# ── Import driver ──────────────────────────────────────────────

def store(pgn_text, source, db=None, log=print):
    if not pgn_text or not pgn_text.strip():
        log("Nothing fetched.")
        return 0, 0, 0
    db = db or MastersDB()
    added, skipped, rejected, live = db.import_pgn(pgn_text, source=source)
    log(f"→ {added} added, {skipped} duplicates skipped, "
        f"{rejected} unusable (no moves / no players), "
        f"{live} still in progress")
    return added, skipped, rejected, live


def _use_utf8_console():
    """
    Windows consoles default to cp1252, which cannot encode the arrows and
    ellipses in this script's output — printing progress would raise
    UnicodeEncodeError and kill an otherwise successful import. Tournament
    and player names are non-ASCII too, so this is not cosmetic.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass   # already UTF-8, or not a reconfigurable stream


def main(argv=None):
    _use_utf8_console()
    ap = argparse.ArgumentParser(
        prog="fetch_masters",
        description="Import real human chess games into the Arena masters database.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("broadcasts", help="Lichess OTB tournament relays")
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--max-tours", type=int, default=15,
                   help="stop after this many tournaments (0 = no limit)")

    p = sub.add_parser("chesscom", help="one Chess.com account")
    p.add_argument("--player", required=True)
    p.add_argument("--months", type=int, default=6)

    p = sub.add_parser("titled", help="Chess.com titled-player directory")
    p.add_argument("--title", default="GM",
                   choices=["GM", "WGM", "IM", "WIM", "FM", "WFM",
                            "NM", "WNM", "CM", "WCM"])
    p.add_argument("--players", type=int, default=10)
    p.add_argument("--months", type=int, default=2)

    p = sub.add_parser("lichess", help="one Lichess account")
    p.add_argument("--player", required=True)
    p.add_argument("--max", type=int, default=200)

    p = sub.add_parser("pgnmentor", help="PGN Mentor bulk collections")
    p.add_argument("--kind", choices=["players", "openings"],
                   default="players")
    p.add_argument("--names", nargs="+",
                   help="e.g. Carlsen Kasparov  /  Vienna SicilianNajdorf")
    p.add_argument("--all", action="store_true",
                   help="every collection of the chosen kind (large)")
    p.add_argument("--list", action="store_true",
                   help="print the available names and exit")

    p = sub.add_parser("twic", help="The Week in Chess weekly zips")
    p.add_argument("--from", dest="issue_from", type=int, required=True)
    p.add_argument("--to", dest="issue_to", type=int)

    p = sub.add_parser("file", help="import a local .pgn file")
    p.add_argument("--path", required=True)

    p = sub.add_parser("purge", help="delete imported games")
    p.add_argument("--source", default=None)

    p = sub.add_parser("prune", help="keep only the newest N games")
    p.add_argument("--max", type=int, required=True)

    sub.add_parser("stats", help="show what is already stored")
    sub.add_parser("backfill", help="fill blank opening names from ECO codes")

    p = sub.add_parser(
        "reparse",
        help="re-derive metadata from the stored PGN (no re-download)")
    p.add_argument("--source", default=None)

    args = ap.parse_args(argv)
    db = MastersDB()
    print(f"Database: {db.db_path}\n")

    if args.cmd == "stats":
        s = db.stats()
        print(f"  games   : {s['total']:,}")
        print(f"  players : {s['players']:,}")
        print(f"  events  : {s['events']:,}")
        print(f"  span    : {s['oldest']} → {s['newest']}")
        print(f"  on disk : {s['file_bytes'] / 1048576:.1f} MB "
              f"({s['pgn_bytes'] / max(s['total'], 1):,.0f} bytes/game)")
        for src, n in s["sources"]:
            print(f"    {src or '(none)':<20} {n:>8,}")
        return 0

    if args.cmd == "reparse":
        n, dropped = db.reparse(args.source)
        print(f"Re-parsed {n:,} games from their stored PGN"
              + (f", removed {dropped:,} unfinished" if dropped else ""))
        if dropped:
            db.vacuum()
        return 0

    if args.cmd == "backfill":
        print(f"Filled {db.backfill_openings():,} opening names from ECO codes")
        return 0

    if args.cmd == "purge":
        n = db.purge(args.source)
        freed = db.vacuum()
        print(f"Deleted {n:,} games"
              + (f" from {args.source}" if args.source else "")
              + f", reclaimed {freed / 1048576:.1f} MB")
        return 0

    if args.cmd == "prune":
        n = db.prune(args.max)
        freed = db.vacuum()
        print(f"Pruned {n:,} oldest games, reclaimed "
              f"{freed / 1048576:.1f} MB")
        return 0

    if args.cmd == "broadcasts":
        print("Fetching Lichess broadcasts…")
        store(fetch_broadcasts(args.pages, max_tours=args.max_tours or None),
              "lichess-broadcast", db)

    elif args.cmd == "chesscom":
        print(f"Fetching Chess.com archives for {args.player}…")
        store(fetch_chesscom_player(args.player, args.months), "chesscom", db)

    elif args.cmd == "titled":
        print(f"Fetching Chess.com {args.title} archives…")
        store(fetch_chesscom_titled(args.title, args.players, args.months),
              "chesscom", db)

    elif args.cmd == "lichess":
        print(f"Fetching Lichess games for {args.player}…")
        store(fetch_lichess_player(args.player, args.max), "lichess", db)

    elif args.cmd == "pgnmentor":
        lister = (list_pgnmentor_openings if args.kind == "openings"
                  else list_pgnmentor_players)
        if args.list or not (args.names or args.all):
            for name in lister():
                print(f"  {name}")
            return 0
        names = lister() if args.all else args.names
        print(f"Fetching {len(names)} PGN Mentor {args.kind} collection(s)…")
        # Import per file: --all openings is hundreds of MB of movetext and
        # holding it all in memory before the first insert would be reckless.
        totals = [0, 0, 0, 0]
        for name in names:
            pgn = fetch_pgnmentor([name], kind=args.kind)
            if pgn:
                for i, v in enumerate(store(pgn, "pgnmentor", db)):
                    totals[i] += v
        print(f"\nTotals: {totals[0]:,} added, {totals[1]:,} duplicates, "
              f"{totals[2]:,} unusable, {totals[3]:,} in progress")

    elif args.cmd == "twic":
        print("Fetching TWIC issues…")
        store(fetch_twic(args.issue_from, args.issue_to), "twic", db)

    elif args.cmd == "file":
        with open(args.path, "r", encoding="utf-8", errors="replace") as fh:
            store(fh.read(), "pgn", db)

    print(f"\nTotal in database: {db.count():,} games")
    return 0


if __name__ == "__main__":
    sys.exit(main())
