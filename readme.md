## Chess Engine Resources
https://e.pcloud.link/publink/show?lang=en&code=kZHEppZbCDCs9wagDhvjGGM2bo36LEIvynX
###

https://chessengines.blogspot.com/



# ♟ Chess Engine Arena — Enhanced

A feature-rich desktop application for running chess engine matches, tournaments,
and human-vs-engine games. Built with Python + Tkinter.

## Project Structure

```
Chess_Engine_Arena/
│
├── main.py                    # ← Run this to start the app
│
├── engines/                   # ← Your UCI chess engines go here
│   ├── stockfish.exe          #     (e.g., Stockfish, Komodo, Lc0, Fruit)
│   ├── gfruit.exe             #     gfruit.exe = default for "Play vs Engine"
│   └── README.txt
│
├── analyzer/                  # ← Stockfish for move quality analysis
│   ├── stockfish.exe          #     (auto-detected on startup)
│   └── README.txt
│
├── openings/                  # ← ECO opening book CSV
│   ├── openings_sheet.csv     #     (auto-detected on startup)
│   └── README.txt
│
├── core/                      # Game logic & engine communication
│   ├── __init__.py
│   ├── board.py               #   Full chess rules engine
│   ├── constants.py           #   App-wide constants, colours, piece data
│   ├── elo.py                 #   Elo rating computation
│   ├── engine.py              #   UCI engine wrapper & analyzer
│   ├── opening_book.py        #   ECO/opening CSV loader & lookup
│   └── utils.py               #   Shared utility functions
│
├── data/                      # Persistence layer
│   ├── __init__.py
│   └── database.py            #   SQLite game/stats database
│
├── ui/                        # User interface (Tkinter)
│   ├── __init__.py
│   ├── app.py                 #   Main ChessGUI window (responsive)
│   ├── dialogs.py             #   Reusable dialog windows
│   ├── loading_screen.py      #   Startup splash / loader
│   ├── theme.py               #   Centralized fonts, colours, styles
│   ├── views.py               #   Rankings, stats, history, PGN viewer
│   └── widgets.py             #   Shared widget factories
│
├── tournament/                # Tournament system
│   ├── __init__.py
│   └── manager.py             #   Round-robin & bracket tournaments
│
├── chess_arena.db             # SQLite database (auto-created)
├── ChessEngineArena.spec      # PyInstaller spec (optional)
└── README.md
```

## Where to Put Your Files

| File Type               | Folder        | Auto-detected?                          |
|--------------------------|---------------|-----------------------------------------|
| Chess engines (.exe)     | `engines/`    | No — browse via the "…" button          |
| Analyzer (Stockfish)     | `analyzer/`   | ✅ Yes, on startup                       |
| Opening book (.csv)      | `openings/`   | ✅ Yes, on startup                       |

### Analyzer (auto-detected filenames)
Place any of these in `analyzer/` or `engines/`:
- `stockfish.exe`
- `stockfish_18_x86-64.exe`
- `stockfish_x86-64.exe`
- `stockfish` (Linux/Mac)

### Opening Book (auto-detected filenames)
Place any of these in `openings/`:
- `openings_sheet.csv` (preferred)
- `openings.csv`

### Game Engines
Place engine executables in `engines/`. You load them manually via the
browse button in the Configuration panel. For "Play vs Engine" mode,
`engines/gfruit.exe` is auto-loaded as the default opponent if present.

## Running

```bash
python main.py
```

## Requirements

- Python 3.8+
- Tkinter (included with most Python installations)
- No external pip packages required

## Features

- **Engine vs Engine** — Pit two UCI engines against each other
- **Human vs Engine** — Play as White or Black against any UCI engine
- **Move Quality Analysis** — Stockfish analyzer rates every move
- **Eval Bar** — Real-time centipawn evaluation display
- **Opening Book** — ECO openings CSV with automatic detection
- **Elo Ratings** — Automatic rating tracking with history charts
- **Tournaments** — Round-robin and bracket tournament modes
- **PGN Viewer** — Interactive game replay with board navigation
- **Responsive Layout** — Resizable window with dynamic board scaling


## Full Build Command (copy-paste)

Windows CMD:
```cmd
python -m PyInstaller --onefile --windowed --icon=assets/logo.ico --name="ChessEngineArena" --add-data="openings;opening" --add-data="analyzer;analyzer" --add-data="engines;gfruit.exe" --add-data="assets;assets" main.py
```
