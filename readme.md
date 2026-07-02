## Chess Engine Resources
https://e.pcloud.link/publink/show?lang=en&code=kZHEppZbCDCs9wagDhvjGGM2bo36LEIvynX
###

https://chessengines.blogspot.com/



# ♟ Chess Engine Arena

A feature-rich desktop app for running chess engine matches, tournaments,
and human-vs-engine games. Built with **Python + NiceGUI** — runs as a
native desktop window (pywebview/WebView2) or in the browser.

## Running

```bash
# activate the virtual environment first
.\venv\Scripts\activate

python main.py             # native desktop window (default)
python main.py --browser   # open in the web browser (DevTools debugging)
```

First launch parses the opening book (a blocking loading screen is shown);
the parsed book is cached to disk, so every launch after that is fast.

## Requirements

- Python 3.10+
- `pip install -r requirements.txt` (NiceGUI + pywebview)
- Windows: WebView2 runtime (built into Windows 11) for native mode

## Features

- **Engine vs Engine** — pit two UCI engines against each other
- **Human vs Engine** — play as White or Black against any UCI engine
- **Tournaments** — Swiss (Buchholz tiebreaks), Round Robin (single/double),
  and Knockout brackets, with a live board, standings, schedule and
  per-game replay; every game is saved to the database
- **Move Quality Analysis** — a Stockfish analyzer rates every move
  (Book / Brilliant / Best / Excellent / Great / Good / Inaccuracy /
  Mistake / Blunder); opening-book moves are labeled "Book"
- **Eval Bar** — real-time centipawn evaluation display
- **Opening Book** — ECO openings CSV, auto-detected and disk-cached;
  pick any opening as a forced starting position
- **Elo Ratings** — automatic rating tracking with interactive history charts
- **Rankings / Statistics / Game History** — searchable tables with
  medals for the top 3 and per-engine opening statistics
- **PGN Viewer** — interactive replay with keyboard navigation, copy and
  download
- **Sprite-based UI** — all pieces, nav cards, medals, badges and icons
  come from `assets/Chess_packs.png` (no emoji dependence)

## Project Structure

```
Chess_Engine_Arena/
│
├── main.py                    # ← Run this to start the app (NiceGUI entry)
│
├── engines/                   # ← Your UCI chess engines go here
│   └── gfruit.exe             #     default opponent for "Play vs Engine"
│
├── analyzer/                  # ← Stockfish for move-quality analysis
│   ├── stockfish_18_x86-64.exe#     (auto-detected on startup)
│   └── nn-*.nnue              #     NNUE network files (required by SF)
│
├── openings/                  # ← ECO opening book CSV
│   ├── openings_sheet.csv     #     (auto-detected on startup)
│   └── openings_sheet.csv.cache.json   # auto-generated parse cache
│
├── assets/                    # Sprite sheet + sliced UI assets
│   ├── Chess_packs.png        #   master sprite sheet
│   ├── pieces/                #   12 chess-piece PNGs (board rendering)
│   └── ui/                    #   nav cards, medals, badges, icons
│
├── core/                      # Game logic & engine communication
│   ├── board.py               #   full chess rules engine
│   ├── constants.py           #   app-wide constants, colours, tiers
│   ├── elo.py                 #   Elo rating computation
│   ├── engine.py              #   UCI engine wrapper & analyzer
│   ├── opening_book.py        #   ECO CSV loader + lookup + disk cache
│   └── utils.py               #   shared utilities (PGN, move quality…)
│
├── data/
│   └── database.py            #   SQLite games/tournaments database
│
├── webui/                     # User interface (NiceGUI)
│   ├── session.py             #   GameSession — UI-agnostic game controller
│   ├── main_page.py           #   main layout, config panel, startup loading
│   ├── board.py               #   board component + eval bar (diffed updates)
│   ├── views.py               #   rankings, stats, history, PGN viewer
│   ├── dialogs.py             #   promotion, stop-game, opening picker…
│   ├── tournament.py          #   tournament list/setup/live/history UI
│   ├── widgets.py             #   sprite-icon helpers, loader overlay
│   └── theme.py               #   colours + global CSS
│
├── tournament/
│   └── manager.py             #   tournament logic: formats, pairing, runner
│
├── requirements.txt
└── readme.md
```

The database lives at `~/.chess_arena/chess_arena.db` (auto-created) and is
shared by regular games and tournaments.

## Where to Put Your Files

| File Type              | Folder      | Auto-detected?                          |
|------------------------|-------------|-----------------------------------------|
| Chess engines (.exe)   | `engines/`  | ✅ Shown in the engine dropdown          |
| Analyzer (Stockfish)   | `analyzer/` | ✅ Yes, on startup                       |
| Opening book (.csv)    | `openings/` | ✅ Yes, on startup                       |

Engines placed in `engines/`, `engine/`, `analyzer/` or `stockfish/` appear
automatically in the **Engine dropdown**; anything else can be picked with
the **…** browse button (a real file-explorer dialog in both native and
browser modes).

> **Stockfish note:** small Stockfish builds need their NNUE network files
> (`nn-*.nnue`) next to the .exe. The app starts engines from their own
> folder so these are found automatically, and the analyzer is probed at
> startup — a build that can't search is reported instead of failing
> silently.

### Opening Book (auto-detected filenames)
Place any of these in `openings/`:
- `openings_sheet.csv` (preferred)
- `openings.csv`

Delete the `.cache.json` next to it to force a re-parse (it also
invalidates automatically when the CSV changes).

## Building a Standalone .exe

NiceGUI ships its own PyInstaller wrapper that knows all the hidden
imports:

```cmd
nicegui-pack --onefile --windowed --name "ChessEngineArena" ^
  --add-data "assets;assets" ^
  --add-data "openings;openings" ^
  --add-data "analyzer;analyzer" ^
  --add-data "engines;engines" ^
  main.py
```

(Or run plain `pyinstaller` with `ChessEngineArena.spec` as a starting
point — but `nicegui-pack` is the supported path for NiceGUI apps.)
