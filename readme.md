# Building Chess Engine Arena as a Standalone .exe

This guide explains how to package `chess_arena.py` into a single `.exe` that includes the **Stockfish analyzer**, **opening CSV**, and **app icon** — so end users need nothing installed.

---

## Prerequisites

You need **Windows** (to build a Windows `.exe`) and **Python 3.8+**.

### Install PyInstaller

```cmd
pip install pyinstaller
```

---

## Recommended Project Layout

Set up your folder exactly like this before building:

```
chess_arena/
|
|-- chess_arena.py
|-- logo.ico                 <- app icon (must be .ico)
|-- logo.png                 <- optional PNG for in-app use
|
|-- opening/
|   `-- openings_sheet.csv
|
`-- analyzer/
    `-- stockfish.exe
```

Build from inside the `chess_arena/` folder.

---

## Step 1 — Convert your logo to .ico

PyInstaller requires `.ico` format for the Windows taskbar icon.

**Option A — Online (easiest):**
Upload your image at https://icoconvert.com and download as `logo.ico`.

**Option B — Python with Pillow:**

```cmd
pip install pillow
python -c "from PIL import Image; Image.open('logo.png').save('logo.ico', sizes=[(256,256),(128,128),(64,64),(32,32),(16,16)])"
```

Save the result as `logo.ico` in the project root.

---

## Step 2 — Update chess_arena.py for bundled paths

When PyInstaller runs the `.exe`, bundled files are extracted to a temp folder at runtime (`sys._MEIPASS`). You must update the script so it looks there.

**A) Add this helper near the top of `chess_arena.py`** (right after the imports):

```python
def resource_path(relative_path):
    """Resolve path to a resource — works both as .py and as bundled .exe."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    try:
        base = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        base = os.getcwd()
    return os.path.join(base, relative_path)
```

**B) Replace the `_start_loading` method in `LoadingScreen`** with this version:

```python
def _start_loading(self):
    csv_candidates = [
        resource_path(os.path.join("opening", "openings_sheet.csv")),
        resource_path(os.path.join("opening", "openings.csv")),
        resource_path("openings_sheet.csv"),
        resource_path("openings.csv"),
    ]

    anal_candidates = [
        resource_path(os.path.join("analyzer", "stockfish_18_x86-64.exe")),
        resource_path(os.path.join("analyzer", "stockfish.exe")),
        resource_path(os.path.join("analyzer", "stockfish_x86-64.exe")),
        resource_path(os.path.join("analyzer", "stockfish")),
    ]

    threading.Thread(target=self._load_openings,
                     args=(csv_candidates,), daemon=True).start()
    threading.Thread(target=self._load_analyzer,
                     args=(anal_candidates,), daemon=True).start()
```

---

## Step 3 — Build the .exe

Run this from inside the `chess_arena/` folder:

```cmd
pyinstaller --onefile --windowed --icon=logo.ico --name="ChessEngineArena" --add-data="opening;opening" --add-data="analyzer;analyzer" --add-data="logo.ico;." chess_arena.py
```

### Flag reference

| Flag | Purpose |
|------|---------|
| `--onefile` | Bundle everything into a single `.exe` |
| `--windowed` | Hide the console window |
| `--icon=logo.ico` | Set the app icon |
| `--name="ChessEngineArena"` | Name of the output `.exe` |
| `--add-data="opening;opening"` | Bundle the `opening/` folder |
| `--add-data="analyzer;analyzer"` | Bundle the `analyzer/` folder |
| `--add-data="logo.ico;."` | Bundle the icon at root level |

> The separator in `--add-data` is `;` on Windows and `:` on Linux/macOS.

---

## Step 4 — Find your output

```
chess_arena/
`-- dist/
    `-- ChessEngineArena.exe   <- distribute this file
```

The `build/` folder and `.spec` file are temporary and can be deleted.

---

## Distribution

Users only need the single `.exe` file. No Python, no folders, no setup required. Stockfish and the opening book are extracted automatically to a temp folder when the app launches.

---

## Troubleshooting

**Build fails: logo.ico not found**
Make sure `logo.ico` is in the same folder as `chess_arena.py`, not inside a subfolder.

**App opens then immediately closes**
Remove `--windowed` to see the error in the console:
```cmd
pyinstaller --onefile --icon=logo.ico --name="ChessEngineArena" --add-data="opening;opening" --add-data="analyzer;analyzer" chess_arena.py
```

**Analyzer not found at runtime**
You skipped Step 2. The script must use `resource_path()` or Stockfish will not be found in the temp extraction folder.

**Windows Defender / antivirus flags the .exe**
This is common with PyInstaller executables and chess engines combined. Add an exception in Windows Defender for the `dist/` folder during testing. For distribution, consider code signing.

**The .exe is very large (80-150 MB)**
Normal — it contains Python, tkinter, and Stockfish. To compress with UPX:
```cmd
pyinstaller --onefile --windowed --upx-dir="C:\path\to\upx" --icon=logo.ico ...
```
Download UPX from https://upx.github.io

**Want repeatable builds?**
Edit the auto-generated `ChessEngineArena.spec` file and rebuild:
```cmd
pyinstaller ChessEngineArena.spec
```

---

## Full Build Command (copy-paste)

Windows CMD:
pyinstaller --onefile --windowed --icon=assets/logo.ico --name="ChessEngineArena" --add-data="opening;opening" --add-data="analyzer;analyzer" --add-data="assets/logo.ico;assets" chess_arena.py