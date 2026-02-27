# Building Chess Engine Arena as a Standalone .exe

This guide explains how to package `main.py` into a single `.exe` that includes the **Stockfish analyzer**, **opening CSV**, and **app icon** — so end users need nothing installed.

## Chess Engine Resources
https://e.pcloud.link/publink/show?lang=en&code=kZHEppZbCDCs9wagDhvjGGM2bo36LEIvynX

---

## Prerequisites

You need **Windows** (to build a Windows `.exe`) and **Python 3.8+**.

### Install PyInstaller
```cmd
pip install pyinstaller
```

---

## Step 1 — Recommended Project Layout

Set up your folder exactly like this before building:
```
chess_arena/
|
|-- main.py
|-- assets/
|   |-- logo.ico
|   `-- logo.png
|
|-- opening/
|   `-- openings_sheet.csv
|
`-- analyzer/
    `-- stockfish.exe  (download from https://stockfishchess.org/)
```

---


## Step 2 — Run the Build Command
```cmd
pyinstaller --onefile --windowed --icon=assets/logo.ico --name="ChessEngineArena" --add-data="opening;opening" --add-data="analyzer;analyzer" --add-data="assets;assets" main.py
```

### Flag Reference

| Flag | Purpose |
|------|---------|
| `--onefile` | Bundle everything into a single `.exe` |
| `--windowed` | Hide the console window |
| `--icon=assets/logo.ico` | Set the app icon |
| `--name="ChessEngineArena"` | Name of the output `.exe` |
| `--add-data="opening;opening"` | Bundle the `opening/` folder |
| `--add-data="analyzer;analyzer"` | Bundle the `analyzer/` folder |
| `--add-data="assets;assets"` | Bundle the `assets/` folder |

> The separator in `--add-data` is `;` on Windows and `:` on Linux/macOS.

---

## Step 3 — Find Your Output
```
chess_arena/
`-- dist/
    `-- ChessEngineArena.exe   <- distribute this file
```

The `build/` folder and `.spec` file are temporary and can be deleted.

---

## Full Build Command (copy-paste)

Windows CMD:
```cmd
pyinstaller --onefile --windowed --icon=assets/logo.ico --name="ChessEngineArena" --add-data="opening;opening" --add-data="analyzer;analyzer" --add-data="assets;assets" main.py
```
