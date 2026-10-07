Place your ECO openings CSV file here.
Supported filenames (auto-detected at startup):
  - openings_sheet.csv  (preferred)
  - openings.csv

CSV format: ECO code, opening name, moves (SAN or UCI, space-separated)
Example rows:
  B20,Sicilian Defense,e4 c5
  B20,Sicilian Defense,e2e4 c7c5

Openings are named by position, not by move order: the position each line
ends on carries its name. A game that transposes (1.e4 Nc6 2.Nf3 e5 3.Bb5)
is named after the opening it reaches (Ruy Lopez), whatever it started as.

The bundled openings_sheet.csv is generated from the Lichess opening
dataset, https://github.com/lichess-org/chess-openings (CC0 1.0, public
domain), by:
  python -m tools.build_openings

You can also load a CSV manually via the "Load openings CSV…" button.
