# ═══════════════════════════════════════════════════════════════════════════════
#  backup_db.py — snapshot the local database to a GitHub Release
#
#  The database lives in ~/.chess_arena and is ~170 MB once a few TWIC
#  issues are imported, so it cannot go in the repo: GitHub rejects any
#  file over 100 MB outright, and SQLite is binary, so git would store a
#  whole new copy on every commit.
#
#  Releases are the right home for it — 2 GB per asset, and assets live
#  outside git history, so uploading repeatedly never grows the clone.
#
#  Usage:
#    python -m tools.backup_db                 # snapshot and upload
#    python -m tools.backup_db --list          # show existing backups
#    python -m tools.backup_db --restore       # fetch the newest backup
#    python -m tools.backup_db --restore db-2026-08-02
#    python -m tools.backup_db --local-only    # just write the .bz2 here
# ═══════════════════════════════════════════════════════════════════════════════

import argparse
import bz2
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

from core.utils import get_db_path

# bz2 beats gzip substantially on SQLite pages (16% vs 24% of original) and
# is five times faster than lzma for the same ratio.
COMPRESS_LEVEL = 9
ASSET = "chess_arena.db.bz2"
TAG_PREFIX = "db-"
KEEP = 5              # dated releases retained by --prune
CHUNK = 4 * 1024 * 1024


def _mb(n):
    return f"{n / 1048576:.1f} MB"


def _gh(*args, check=True, capture=True):
    """Run the gh CLI, returning stdout."""
    try:
        p = subprocess.run(["gh", *args], check=check, text=True,
                           capture_output=capture)
    except FileNotFoundError:
        raise SystemExit("gh CLI not found — install it from https://cli.github.com")
    if capture and p.returncode and check:
        raise SystemExit(f"gh {' '.join(args)} failed:\n{p.stderr}")
    return (p.stdout or "").strip()


def snapshot(dest_dir):
    """
    Write a compressed, consistent copy of the live database.

    VACUUM INTO rather than a file copy: the app may be running, and in WAL
    mode the .db on disk is only part of the picture — a plain copy can
    miss committed data sitting in the -wal file. VACUUM INTO takes a read
    lock and emits a complete, already-compacted database.
    """
    src = get_db_path()
    if not os.path.isfile(src):
        raise SystemExit(f"no database at {src}")
    raw_size = os.path.getsize(src)
    print(f"source     : {src}  ({_mb(raw_size)})")

    with sqlite3.connect(src) as conn:
        games = conn.execute(
            "SELECT COUNT(*) FROM master_games").fetchone()[0]
        engine = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        vacuumed = os.path.join(dest_dir, "snapshot.db")
        print("snapshot   : VACUUM INTO …", end="", flush=True)
        t = time.perf_counter()
        # Parameter binding is not allowed for VACUUM INTO's path.
        conn.execute(f"VACUUM INTO '{vacuumed.replace(chr(39), chr(39) * 2)}'")
        print(f" {time.perf_counter() - t:.0f}s  "
              f"({_mb(os.path.getsize(vacuumed))})")

    out = os.path.join(dest_dir, ASSET)
    print("compress   : bz2 …", end="", flush=True)
    t = time.perf_counter()
    with open(vacuumed, "rb") as fh, \
            bz2.open(out, "wb", compresslevel=COMPRESS_LEVEL) as gz:
        shutil.copyfileobj(fh, gz, CHUNK)
    os.remove(vacuumed)
    size = os.path.getsize(out)
    print(f" {time.perf_counter() - t:.0f}s  {_mb(size)} "
          f"({size / raw_size:.0%} of original)")

    if size > 2 * 1024 ** 3:
        raise SystemExit("asset exceeds the 2 GB GitHub Release limit")
    return out, {"games": games, "engine_games": engine, "raw": raw_size,
                 "packed": size}


def list_backups():
    raw = _gh("release", "list", "--limit", "100", "--json",
              "tagName,createdAt,name")
    rels = [r for r in json.loads(raw or "[]")
            if r["tagName"].startswith(TAG_PREFIX)]
    rels.sort(key=lambda r: r["createdAt"], reverse=True)
    return rels


def upload(path, meta, tag, notes):
    existing = {r["tagName"] for r in list_backups()}
    if tag in existing:
        print(f"upload     : replacing asset on existing release {tag}")
        _gh("release", "upload", tag, path, "--clobber", capture=False)
    else:
        print(f"upload     : creating release {tag}")
        _gh("release", "create", tag, path, "--title", f"Database {tag}",
            "--notes", notes, capture=False)
    print(f"done       : {tag}  ({_mb(meta['packed'])})")


def prune(keep=KEEP):
    rels = list_backups()
    for r in rels[keep:]:
        print(f"prune      : deleting {r['tagName']}")
        _gh("release", "delete", r["tagName"], "--yes", "--cleanup-tag",
            check=False)


def restore(tag=None, force=False):
    rels = list_backups()
    if not rels:
        raise SystemExit("no database backups found in this repo's releases")
    tag = tag or rels[0]["tagName"]
    dest = get_db_path()

    tmp = tempfile.mkdtemp()
    print(f"download   : {tag}")
    _gh("release", "download", tag, "--pattern", ASSET, "--dir", tmp,
        capture=False)
    packed = os.path.join(tmp, ASSET)

    plain = os.path.join(tmp, "restored.db")
    print("decompress : …", end="", flush=True)
    with bz2.open(packed, "rb") as gz, open(plain, "wb") as fh:
        shutil.copyfileobj(gz, fh, CHUNK)
    print(f" {_mb(os.path.getsize(plain))}")

    with sqlite3.connect(plain) as conn:
        n = conn.execute("SELECT COUNT(*) FROM master_games").fetchone()[0]
    print(f"verify     : {n:,} master games in the downloaded copy")

    # Never clobber live data silently — the local copy may be newer.
    if os.path.isfile(dest):
        if not force:
            print(f"\nA database already exists at {dest}.")
            print(f"Leaving it alone. The restored copy is at:\n  {plain}")
            print("Re-run with --force to replace the live database "
                  "(the current one is kept as a .bak).")
            return
        backup = f"{dest}.bak-restore-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.move(dest, backup)
        print(f"safety     : existing database moved to {backup}")
    shutil.move(plain, dest)
    print(f"restored   : {dest}")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(
        prog="backup_db",
        description="Snapshot the local chess database to a GitHub Release.")
    ap.add_argument("--tag", help=f"release tag (default {TAG_PREFIX}<date>)")
    ap.add_argument("--list", action="store_true", help="show backups")
    ap.add_argument("--restore", nargs="?", const="", metavar="TAG",
                    help="download a backup (newest if no tag given)")
    ap.add_argument("--force", action="store_true",
                    help="with --restore, replace the live database")
    ap.add_argument("--local-only", action="store_true",
                    help="write the compressed snapshot here, do not upload")
    ap.add_argument("--prune", action="store_true",
                    help=f"delete all but the newest {KEEP} backups")
    args = ap.parse_args(argv)

    if args.list:
        rels = list_backups()
        if not rels:
            print("no database backups yet")
        for r in rels:
            print(f"  {r['tagName']:<20} {r['createdAt']}")
        return 0

    if args.restore is not None:
        restore(args.restore or None, args.force)
        return 0

    tag = args.tag or TAG_PREFIX + time.strftime("%Y-%m-%d")
    workdir = "." if args.local_only else tempfile.mkdtemp()
    path, meta = snapshot(workdir)

    if args.local_only:
        print(f"written    : {path}")
        return 0

    notes = (f"Masters + engine database snapshot.\n\n"
             f"- {meta['games']:,} master games\n"
             f"- {meta['engine_games']:,} engine games\n"
             f"- {_mb(meta['raw'])} uncompressed, {_mb(meta['packed'])} packed\n\n"
             f"Restore with `python -m tools.backup_db --restore {tag}`.")
    upload(path, meta, tag, notes)
    if args.prune:
        prune()
    return 0


if __name__ == "__main__":
    sys.exit(main())
