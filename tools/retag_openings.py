# ═══════════════════════════════════════════════════════════════════════════════
#  retag_openings.py — re-name the opening of every stored game
#
#  The app does this by itself once per opening book (see
#  data.database.retag_openings_once). This is the same job by hand: a dry
#  run that shows what would change, and --apply to back up and rewrite.
#
#  The engine database syncs between PCs, so publish a fresh snapshot with
#  tools/backup_db.py after applying.
#
#  Usage:
#    python -m tools.retag_openings                 # dry run on the live DB
#    python -m tools.retag_openings --apply         # back up, then rewrite
#    python -m tools.retag_openings --db COPY.db    # work on another file
# ═══════════════════════════════════════════════════════════════════════════════

import argparse
import os
import sys
import time

from core.opening_book import OpeningBook
from core.utils import file_sha1, get_db_path, get_resource_path
from data.database import Database, OPENING_NAMES_KEY

CSV = get_resource_path(os.path.join("openings", "openings_sheet.csv"))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="back up the database and rewrite the names")
    ap.add_argument("--db", help="database file (default: the live one)")
    ap.add_argument("--top", type=int, default=25,
                    help="how many of the commonest renames to list")
    args = ap.parse_args()

    book = OpeningBook(CSV)
    if not book.loaded:
        raise SystemExit(f"No openings in {CSV}")
    db = Database(args.db or get_db_path())
    print(f"Database: {db.db_path}")

    if args.apply:
        print(f"Backup:   {db.backup('openings')}")
    t0 = time.time()
    report = db.retag_openings(
        book, dry_run=not args.apply,
        progress=lambda table, i, n: print(f"  {table}: {i}/{n}", end="\r"))
    print(" " * 40, end="\r")
    print(f"Checked {report['checked']} rows in {time.time() - t0:.1f}s — "
          f"{report['changed']} {'renamed' if args.apply else 'would change'}")

    renames = sorted(report['renames'].items(), key=lambda kv: -kv[1])
    for (old, new), n in renames[:args.top]:
        print(f"  {n:5d}  {old or '(none)'}  →  {new}")

    if args.apply:
        db.set_meta(OPENING_NAMES_KEY, file_sha1(CSV))
        print("Done. Publish a fresh snapshot with: python -m tools.backup_db")


if __name__ == "__main__":
    sys.exit(main())
