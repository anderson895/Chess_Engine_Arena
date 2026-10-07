# ═══════════════════════════════════════════════════════════════════════════════
#  build_openings.py — regenerate openings/openings_sheet.csv from Lichess
#
#  Source: https://github.com/lichess-org/chess-openings (CC0 1.0 — public
#  domain). Its names are assigned to positions, which is what the book
#  needs to follow transpositions, and they are clean ("Ruy Lopez: Morphy
#  Defense") where the old sheet mixed ECO codes and suffixes into them.
#
#  The output keeps the sheet's own format — ECO,name,moves with SAN moves
#  and no move numbers — so the book, the opening picker and the masters
#  importer read it unchanged. Every line is replayed while writing; one
#  that does not parse stops the build instead of being dropped silently.
#
#  Usage:
#    python -m tools.build_openings                # download and rebuild
#    python -m tools.build_openings --from DIR     # use local a.tsv … e.tsv
# ═══════════════════════════════════════════════════════════════════════════════

import argparse
import csv
import io
import os
import re
import sys
import urllib.request

from core.pgn import tokens_to_uci
from core.utils import get_resource_path

SOURCE = "https://raw.githubusercontent.com/lichess-org/chess-openings/master/{}.tsv"
PARTS = "abcde"
OUT = get_resource_path(os.path.join("openings", "openings_sheet.csv"))


def read_part(part, local_dir=None):
    """Rows (eco, name, pgn) of one Lichess TSV."""
    if local_dir:
        with open(os.path.join(local_dir, f"{part}.tsv"), encoding="utf-8") as f:
            text = f.read()
    else:
        req = urllib.request.Request(SOURCE.format(part),
                                     headers={"User-Agent": "ChessEngineArena"})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    return [(row["eco"], row["name"], row["pgn"]) for row in reader]


def san_moves(pgn):
    """'1. e4 e5 2. Nf3' → ['e4', 'e5', 'Nf3'], checked by replaying them."""
    tokens = [t for t in pgn.split() if not re.match(r"^\d+\.+$", t)]
    if tokens_to_uci(tokens, strict=True) is None:
        raise ValueError(f"cannot play {pgn!r}")
    return tokens


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="local_dir",
                    help="folder holding a.tsv … e.tsv instead of downloading")
    args = ap.parse_args()

    rows = []
    for part in PARTS:
        part_rows = read_part(part, args.local_dir)
        print(f"{part}.tsv: {len(part_rows)} lines")
        rows += part_rows

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ECO", "name", "moves"])
        for eco, name, pgn in rows:
            w.writerow([eco, name, " ".join(san_moves(pgn))])
    print(f"Wrote {len(rows)} openings to {OUT}")


if __name__ == "__main__":
    sys.exit(main())
