# Chess Engine Arena

A feature-rich desktop app for running chess engine matches, tournaments,
and human-vs-engine games. Built with **Python + NiceGUI** — runs as a
native desktop window (pywebview/WebView2) or in the browser.

- [Download](#download)
- [Features](#features)
- [Getting Started](#getting-started)
- [The Main Screen](#the-main-screen)
- [Tournaments](#tournaments)
- [Adding Engines and Files](#adding-engines-and-files)
- [Game Review](#game-review)
- [Masters Database](#masters-database)
- [Project Structure](#project-structure)
- [Building a Standalone .exe](#building-a-standalone-exe)
- [Resources](#resources)

## Download

Prebuilt Windows builds are on the
[Releases page](https://github.com/anderson895/Chess_Engine_Arena/releases).
Download `ChessEngineArena-<version>-win64.zip`, extract it anywhere, and run
`ChessEngineArena.exe`.

Keep the .exe inside its folder — it needs the `_internal` directory beside
it. Requires Windows 10/11 64-bit.

To run from source instead, see [Getting Started](#getting-started).

## Features

- **Engine vs Engine** — pit two UCI engines against each other
- **Human vs Engine** — play as White or Black against any UCI engine
- **2 Players** — two people at one board; every move is graded as it is
  played, and finished games are saved and rated under the players' names
- **Undo** — take back a move in a game you play: against an engine, your
  move and its reply; with two players, the last move ([details](#undo))
- **Any starting position** — set a position up on a board editor, paste a
  FEN or PGN, pick a book opening or play the moves, and the engines play
  on from there; afterwards you choose whether the result is recorded
  ([details](#starting-position))
- **Drag and drop** — move a piece by dragging it to its square, or by
  clicking it and then the square; its legal moves show while it is held
- **Premove** — against an engine, make your next move while it is still
  thinking; it is played the moment the engine replies ([details](#premoves))
- **Clocks** — Bullet (1+0) and Blitz (3+2) are played on the clock by
  engines and people alike; run out of time and you lose
  ([details](#clocks))
- **Tournaments** — Swiss (no rematches, Buchholz tiebreaks), Round Robin
  (single/double), Knockout brackets and team events, with a live board,
  standings, schedule and per-game review; every game is saved to the
  database, a finished event can be continued or extended, and a newer
  version of an engine can take its place with its points
  ([details](#tournaments))
- **Game Review** — a chess.com-style review of any game: accuracy for
  both players, how many Brilliant / Great / Book / Best / Excellent /
  Good / Inaccuracy / Mistake / Miss / Blunder moves each made, an
  evaluation graph, and a move-by-move walkthrough with the engine's best
  move ([details](#game-review))
- **Live move grading** — every move of a regular or tournament game is
  graded as it is played, by the same rules as the review; click a move in
  the move list to look at the position after it
- **Eval Bar** — real-time evaluation display
- **Opening Book** — ECO openings named by position, so a game that
  transposes into another opening is named after the one it reaches;
  auto-detected and disk-cached; pick any opening as a starting position
- **Elo Ratings** — automatic rating tracking with interactive history charts
- **Rankings / Statistics / Game History** — searchable tables with
  medals for the top 3 and per-engine opening statistics
- **Masters Database** — over-the-board games by real titled players,
  imported from Lichess broadcasts, Chess.com, TWIC and PGN Mentor, with
  filters for player, colour, opponent, event, ECO, rating and year
  ([details](#masters-database))
- **chess.com-style look** — warm dark theme, a green board by default,
  player bars with clocks, and the same look on every screen
  ([details](#the-main-screen))
- **Sprite-based UI** — all pieces, nav cards, medals, badges and icons
  come from `assets/Chess_packs.png` (no emoji dependence)

## Getting Started

### Requirements

- Python 3.10+
- `pip install -r requirements.txt` (NiceGUI + pywebview)
- Windows: WebView2 runtime (built into Windows 11) for native mode

### Running

```bash
# activate the virtual environment first
.\venv\Scripts\activate

python main.py             # native desktop window (default)
python main.py --browser   # open in the web browser (DevTools debugging)
```

First launch parses the opening book (a blocking loading screen is shown);
the parsed book is cached to disk, so every launch after that is fast.

The database lives at `~/.chess_arena/chess_arena.db` (auto-created) and is
shared by regular games and tournaments.

## The Main Screen

The layout follows chess.com: navigation down the left, the board in the
middle, and one panel with tabs on the right.

- **Sidebar** — Play, Rankings, Openings, Tournaments, History and Masters.
  **Settings** at the bottom holds the board style (green by default) and
  the piece design; **Sound** turns the move sounds on and off.
- **Board** — the status line on top, and a player bar above and below the
  board: avatar, name, rating, head-to-head record, material lead and, in
  Bullet and Blitz, the clock (lit for the side to move, red under ten
  seconds). **Flip** turns the board and swaps the bars.
- **Play** tab — Engine vs Engine, Play vs Engine or 2 Players; the engines
  or player names, the time control and the starting position (normal, a
  book opening, or one you set up); then **Start Game**.
- **Game** tab — the coach's line about the latest move, the opening, the
  move list with each move's grade (click a move to look at that position;
  **Back to game** returns), step buttons, **Undo**, Pause, Stop, Flip,
  **Game Review**, New Game and Export PGN.
- **Engine** tab — the engines' output, and the opening book and analyzer
  in use, with buttons to load others.

### Undo

**Undo** takes back moves in a game you play. Against an engine it takes
back your last move and the engine's reply, so it is your move again; with
two players it takes back the last move. Moves already graded keep their
grades, and the clocks go back to where they stood. Moves that came with
the starting position (a book opening, or moves played while setting it
up) are never taken back, and Undo is unavailable while the engine is
thinking. Games with takebacks are saved and rated as usual.

### Clocks

Bullet (1+0) and Blitz (3+2) games are played on the clock, by people as
well as engines. Your clock runs from the start of your turn until you
move, and every move adds the increment. If it runs out, you lose on
time, unless your opponent has too little material left to mate: then
the game is drawn (FIDE rule 6.9). **Pause** stops your clock, and so
does the Stop dialog while it is open. Before a game, the clocks show
the time it will start with. Classic has no clock.

### Premoves

Against an engine you can make your next move while it is still
thinking: click or drag one of your pieces as usual. The move is shown in
red, and it is played the moment the engine replies, if it is still legal
then. If it is not, it is dropped and you move as usual. One move waits
at a time, so making another replaces it. Right-click the board, or click
an empty square, to cancel it. A pawn premoved to the last rank becomes a
queen.

### Starting position

A game starts from the normal position unless you choose another under
**Starting position** on the Play tab:

- **Pick Opening** — any line from the opening book (or **Random**).
- **Set Up Position** — a board editor, as on chess.com and Lichess.
  **Place pieces**: pick a piece below or above the board and click
  squares to put it down (the same piece again takes it off; the bin
  removes pieces), or drag pieces around. Set the side to move and the
  castling rights, or type a **FEN** and press Load. **Play moves**: play
  legal moves for both sides from the position, with Undo. **Pick
  Opening** and **Paste PGN** fill the board too — a PGN's FEN tag sets
  where its moves start, and a FEN on its own works as well.
  **Use this position** is available once the position can be played:
  one king a side, no pawns on the first or last rank, the side that just
  moved not in check, and the game not already over.
- **Continue from here** in [Game Review](#best-moves-and-what-ifs) — the
  position on the review's board, from any game.

The board shows the position as soon as it is set, and the engines play on
from there. **✕** goes back to the normal start.

A game that started from a chosen opening or position is not recorded on
its own: when it ends, the game-over window asks **Record this game?**
**Record result** saves it to History and counts it toward the ratings;
**Don't record** leaves it out. Until you answer, the Game tab keeps the
same two buttons; Game Review and Export PGN work either way. Starting the
next game (or **New Game**) without answering leaves it unrecorded. Games
from the normal start are saved and rated as always.

Saved games keep their start in the PGN (`[SetUp "1"]` and `[FEN "…"]`),
so History, the review and exported PGN replay them from the right
position, numbered from the right move.

## Tournaments

**Tournaments** in the sidebar lists every event, and **New Tournament**
sets one up: Swiss, Round Robin, Knockout or a team event. Its window shows
the live board, the standings and the schedule. **Pause** halts an event to
pick up later, and so does closing the app — the game that was in progress
is played again from the start when the event resumes. **Stop** ends the
event where it stands and declares a winner.

A Swiss is paired top-down by standing — the leader against the
highest-placed player they have not met, and so on down — and never
repeats a pairing while some other way of pairing the round avoids it.
Only an event with more rounds than the field can fill has rematches, and
then as few as each round allows.

### Removing a player

The **✕** beside a player in the standings takes them out — for an engine
entered by mistake, or one that keeps failing. Before the first round it
simply leaves the field (in a team event, its squad), and so does a player
in a Swiss or round robin that has not played yet — a late entry made by
mistake, withdrawn or not. Once a player has played, it withdraws instead:
it is never paired again, the games it has played stand, and it stays in
the standings marked "Withdrawn". A game it is playing at that moment is
stopped and not counted. In a Swiss its opponent for the round is paired
again (or gets the bye), in a knockout its opponent goes through, and in a
round robin or team event its remaining games are not played.

In a Swiss, **Add Player** brings a withdrawn engine back: pick it from the
list (it is marked "withdrawn — bring back") or browse to the right file
for it. It keeps the points it had and is paired again from the next
round.

### Renaming a player: a new version plays on

The **✎** beside a player in the standings lets another version of the
engine take its place — or simply gives it a better name. Pick the new
engine file (or browse to it with **…**); the name follows the file, and
you can type another. The player keeps everything it has in the event:
points, W/D/L, tiebreaks, the opponents it has met (so a Swiss still
avoids rematches) and its place in the schedule or the bracket. Its
remaining games are played by the new engine, under the new name.

The games it already played keep the name they were played under — in the
schedule, in Game History and in the ratings, since the old version played
them — and the standings show where the points came from ("was …"). An
engine that sat out because its file was missing plays again once it is
given one, and a withdrawn one in a Swiss can be brought back in the same
step (**Bring it back into the event**). A player cannot be renamed during
a game it is playing. To carry on a finished event with a newer version,
**Continue** it, rename the player, then press **Resume**.

If the new version was entered on its own already (with **Add Player**)
and has not played, pick it in the list — it is marked "entered here,
never played" — and its empty entry makes way for the player taking the
name. Two entries that have both played cannot be merged: they would have
games in the same rounds.

The **Rename** in Rankings is different: it renames an engine across every
saved game, for a name that was wrong all along.

### Continuing a finished tournament

**Continue** — in the window of a finished event, or at the bottom of its
page in the list — plays on:

- an event that was stopped early finishes its schedule;
- a Swiss gets more rounds, paired from the standings as they are;
- a round robin or team event plays another cycle: every pairing again,
  with the colours (home and away) reversed.

A knockout ends with its champion, so there is nothing to add to one.

A finished event keeps everything it needs to be continued. Events that
finished in older versions kept only their games, so Swiss and round-robin
events are rebuilt from those, byes included; a team event's line-ups and
a knockout's bracket were never saved, so those cannot be continued. Their
engines are found again by name: **Scan folder…** points the app at the
folder your engines are in, and it remembers it; **…** picks a single
engine file. An engine that is still missing sits out the new rounds and
keeps the points it has.

## Adding Engines and Files

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

### Opening Book

Place any of these in `openings/` (both filenames are auto-detected):

- `openings_sheet.csv` (preferred)
- `openings.csv`

Delete the `.cache.json` next to it to force a re-parse (it also
invalidates automatically when the CSV changes).

The bundled book is generated from the
[Lichess opening dataset](https://github.com/lichess-org/chess-openings)
(CC0, public domain); `python -m tools.build_openings` regenerates it.

## Game Review

Open a review with **Game Review** in the Game tab (the game on the
board, or the one that just ended), with the **Game Review** button when a
game finishes, or by double-clicking a game in Game History, a tournament
or the Masters database.

The screen follows chess.com's Game Review. On the left is the board
between the two player bars. On the right are the coach, the evaluation
graph, both players' accuracy and how many moves of each class they
played, with a grade for the opening, middlegame and endgame. **Start
Review** walks through the game a move at a time: the move's badge on the
board, a line from the coach, and the engine's best move as a green arrow
whenever the move played was not the best. Click a move, the graph, or use
← → Home End to jump around; the header has flip, copy/download PGN and
previous/next game.

### Best moves and what-ifs

**Best**, under the coach, plays out the engine's best line in place of
the move shown — or, when that move was the best, the line that follows
it — so you can step through it move by move.

Any move can also be tried on the board, by clicking or dragging a piece,
to see what would have happened. It starts a side line from the position
shown, analysed and graded like the game's own moves, with the best reply
as a green arrow; keep playing moves for either side to go deeper. ← and →
step along the line, and **Back to game**, a click on a move in the game's
list or **Next** return to the game. Playing the game's own move simply
steps on through the game.

**Continue from here** makes the position on the board — the game's, or
a side line's — the [starting position](#starting-position) of the next
game, and takes you back to the Play tab with it set. Only the position
goes, as on Lichess: the moves that led to it were not played by the next
game's players. Games that are not standard chess (Chess960 games in the
Masters database) cannot be reviewed.

A dedicated Stockfish process analyses every position, apart from the
analyzer that grades live games, so a review never holds up a game being
played. It runs below normal priority, on one thread while a game or
tournament is running. **Fast / Balanced / Deep** sets the time per
position (0.2 / 0.5 / 1.5 s). Analyses are cached in
`~/.chess_arena/reviews.db`, so reopening a game is instant; like
`masters.db`, the cache is never published with the engine database.

### How moves are classified

Each move is graded by how much of the mover's winning chances it gives
away, from the engine's evaluation (Lichess's win-chance curve): **Best**
is the engine's top move or as good, then **Excellent** (up to 2% lost),
**Good** (5%), **Inaccuracy** (10%), **Mistake** (20%) and **Blunder**
(more). On top of that:

| Class     | When                                                          |
|-----------|---------------------------------------------------------------|
| Brilliant | A good piece sacrifice: the best move (or nearly) leaves a piece that can be taken for clearly more than the move took — not a pawn, not a trade or recapture. The player is not worse after it and was not winning anyway. |
| Great     | The only good move: every alternative throws the result away. |
| Miss      | The opponent just made a mistake and the move hands the chance back, or a forced mate is missed. |
| Book      | The position is opening theory.                               |
| Forced    | The only legal move (shown on the move, not counted).          |

Accuracy uses Lichess's published formula: each move scores by the change
in winning chances, and a player's accuracy blends a volatility-weighted
mean with a harmonic mean, so one blunder costs more than many small
slips.

The same rules grade regular games (under the board, as moves are
played), tournaments (in the live tournament window) and the review. The
review searches longer, so its verdicts are the surest of the three.

### Openings and transpositions

Opening names belong to positions, not move orders. A game that starts
1.e4 Nc6 is a Nimzowitsch Defense, and becomes a Ruy Lopez once 2.Nf3 e5
3.Bb5 reaches that position. The live game, tournaments, game history and
the review all name openings this way.

When the bundled opening book changes, the next launch re-names the
openings of the games already saved, so game history and the opening
statistics use the new names. The database is backed up first, to
`chess_arena.db.bak-openings-<date>` beside it. This runs once per opening
book; `python -m tools.retag_openings` does the same by hand (a dry run
unless given `--apply`).

## Masters Database

Open **Masters** in the sidebar. This is a separate collection of games
played by real people — grandmasters, IMs and rated club players — kept in
its own database so that human results can never reach the engine Elo
ratings.

Everything is stored locally in `~/.chess_arena/masters.db`, a separate
SQLite file from the engine database (`chess_arena.db`) beside it. The two
have opposite lifecycles: the collection runs to a few hundred megabytes
and can be re-fetched from its sources at any time, while engine games,
tournaments and Elo history are small and cannot be recreated. Search and
replay work offline; the network is only used while importing.

A fresh install starts with an empty collection — that is expected. Fill
it from the import sources whenever you like; nothing else depends on it.

Installs from before the split kept both in one file. The masters tables
are moved across automatically the first time the app opens, and the
engine database is compacted afterwards.

### Getting the games

**Import games** offers five sources, all free and none requiring an API
key. The same fetchers are available from the command line:

```bash
# Over-the-board tournaments relayed live by Lichess.
# Real names, FIDE IDs, Elo and ECO — but only the top boards.
python -m tools.fetch_masters broadcasts --pages 1 --max-tours 10

# The Week in Chess: one zipped PGN per week, complete tournament
# coverage (every board, every round). Issue 1655 is late July 2026;
# subtract about 52 per year going back. Available from issue 920.
python -m tools.fetch_masters twic --from 1646 --to 1655

# PGN Mentor: whole careers, or every master game in an opening.
python -m tools.fetch_masters pgnmentor --kind players --names Carlsen Fischer
python -m tools.fetch_masters pgnmentor --kind openings --all

# Chess.com and Lichess accounts.
python -m tools.fetch_masters titled --title GM --players 20 --months 3
python -m tools.fetch_masters lichess --player DrNykterstein --max 500

# Anything you already have.
python -m tools.fetch_masters file --path games.pgn
```

Re-importing is safe: a dedupe key over players, date, result and opening
moves means duplicates are skipped. Games still in progress are refused —
the next sync picks them up once they finish.

> **Coverage note:** Lichess relays only the top boards of an event, so a
> player outside the top boards will be missing rounds. TWIC carries the
> whole tournament and is the source to use when a player looks incomplete.

### Housekeeping

**Storage & maintenance** holds the size report, an optional background
sync, and a hard cap on the number of games (older imports are pruned once
it is reached). Clock and evaluation annotations are stripped on import,
which cuts stored PGN by about 60%.

```bash
python -m tools.fetch_masters stats      # counts, span, size on disk
python -m tools.fetch_masters reparse    # re-derive columns from stored PGN
python -m tools.fetch_masters prune --max 200000
```

### Moving the engine database between machines

`chess_arena.db` holds the games, tournaments and Elo history that cannot
be recreated. SQLite is binary, so committing it would make git store a
whole new copy on every change; `tools/backup_db.py` publishes it as a
GitHub Release asset instead, which lives outside git history:

```bash
python -m tools.backup_db            # snapshot and upload
python -m tools.backup_db --list
python -m tools.backup_db --restore  # newest backup; --force to overwrite
```

On the other machine, either run `--restore`, or download
`chess_arena.db.bz2` from the newest `db-*` release, decompress it and put
the result at `~/.chess_arena/chess_arena.db`.

`masters.db` is deliberately left out — it is large and every game in it
can be re-fetched from the import sources, so a new machine simply starts
with an empty collection.

## Project Structure

```
Chess_Engine_Arena/
│
├── main.py                    # ← Run this to start the app (NiceGUI entry)
│
├── engines/                   # ← Your UCI chess engines go here
│   └── gfruit.exe             #     default opponent for "Play vs Engine"
│
├── analyzer/                  # ← Stockfish for move grading and reviews
│   ├── stockfish_18_x86-64.exe#     (auto-detected on startup)
│   └── nn-*.nnue              #     NNUE network files (required by SF)
│
├── openings/                  # ← ECO opening book CSV (Lichess, CC0)
│   ├── openings_sheet.csv     #     (auto-detected on startup)
│   └── openings_sheet.csv.cache.json   # auto-generated parse cache
│
├── assets/                    # Sprite sheet + sliced UI assets
│   ├── Chess_packs.png        #   master sprite sheet
│   ├── pieces/                #   12 chess-piece PNGs (board rendering)
│   └── ui/                    #   nav cards, medals, badges, icons
│
├── core/                      # Game logic & engine communication
│   ├── board.py               #   full chess rules engine, SAN parser, SEE
│   ├── constants.py           #   app-wide constants, colours, tiers
│   ├── elo.py                 #   Elo rating computation
│   ├── engine.py              #   UCI engine wrapper & analyzer (MultiPV)
│   ├── engine_finder.py       #   finding engine files again by name
│   ├── opening_book.py        #   openings by position + disk cache
│   ├── pgn.py                 #   reading PGN: tags, FEN starts, SAN → UCI
│   ├── review.py              #   move classification, accuracy, GameAnalyst
│   ├── start_position.py      #   where a game starts: a FEN and moves
│   └── utils.py               #   shared utilities (paths, PGN building…)
│
├── data/
│   ├── database.py            #   SQLite games/tournaments database
│   └── reviews.py             #   cache of Game Review analyses
│
├── webui/                     # User interface (NiceGUI)
│   ├── session.py             #   GameSession — UI-agnostic game controller
│   ├── main_page.py           #   main layout: board, Play/Game/Engine tabs
│   ├── sidebar.py             #   the navigation bar down the left
│   ├── board.py               #   board component + eval bar (diffed updates)
│   ├── review.py              #   Game Review screen
│   ├── quality.py             #   move-class badges, coach line, move list
│   ├── views.py               #   rankings, stats, history
│   ├── dialogs.py             #   promotion, stop-game, opening picker…
│   ├── position_setup.py      #   Set Up Position: board editor, FEN, PGN
│   ├── tournament.py          #   tournament list/setup/live/history UI
│   ├── widgets.py             #   player bars, panel tabs, sprite icons
│   └── theme.py               #   chess.com-style palette + global CSS
│
├── tournament/
│   └── manager.py             #   tournament logic: formats, pairing, runner
│
├── art_src/                   # Source art sheets (not bundled at runtime)
├── tools/                     # Dev utilities: sprite slicing, sound probes,
│                              #   opening book build, opening re-tag
│
├── requirements.txt
└── readme.md
```

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

## Resources

Where to find more UCI engines to drop into `engines/`:

- [Engine collection (pCloud)](https://e.pcloud.link/publink/show?lang=en&code=kZHEppZbCDCs9wagDhvjGGM2bo36LEIvynX)
- [chessengines.blogspot.com](https://chessengines.blogspot.com/)
