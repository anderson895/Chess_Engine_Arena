# ♟ Chess Engine Arena

A UCI chess engine arena with full game logging, statistics, PGN export,
and human vs engine mode.

---

## 📁 Project Structure

```
chess_arena/
├── chess_arena.py        ← main application
├── chess_arena.spec      ← PyInstaller build config
├── build.bat             ← Windows build script (double-click to build)
├── build.sh              ← Linux/Mac build script
├── assets/
│   └── logo.ico          ← app icon (16px to 256px)
├── chess_arena.db        ← game history database (auto-created on first run)
└── README.md             ← this file
```

---

## 🛠 Building the .exe on Windows 11

### Step 1 — Install Python

1. Go to **https://python.org/downloads**
2. Download the latest Python 3.x installer
3. Run the installer — **check ✅ "Add Python to PATH"** before clicking Install
4. Verify by opening Command Prompt and typing:
   ```
   python --version
   ```
   Should output something like `Python 3.12.3`

---

### Step 2 — Open Terminal in the Project Folder

**Option A (easiest):**
- Open the `chess_arena` folder in File Explorer
- Hold **Shift** + **Right-click** on empty space
- Click **"Open in Terminal"** or **"Open PowerShell window here"**

**Option B:**
- Open Command Prompt or PowerShell
- Navigate to the folder manually:
  ```
  cd C:\Users\YourName\Desktop\chess_arena
  ```

---

### Step 3 — Install PyInstaller

Run this once (only needed the first time):
```
pip install pyinstaller
```

---

### Step 4 — Build the .exe

**Option A — Double-click `build.bat`** (easiest, no typing needed)

**Option B — Run manually in terminal:**
```
pyinstaller chess_arena.spec --clean --noconfirm
```

**Option C — Full one-liner (no .spec file needed):**
```
pyinstaller --onefile --windowed --icon=assets\logo.ico --add-data "assets\logo.ico;assets" --name "ChessEngineArena" chess_arena.py
```

---

### Step 5 — Get the Output

After building, find your `.exe` here:
```
chess_arena\
└── dist\
    └── ChessEngineArena.exe  ✅ this is your app
```

Double-click `ChessEngineArena.exe` to run — no installation needed.

---

## ⚠️ Common Errors & Fixes

### ❌ `python` not recognized
```
'python' is not recognized as an internal or external command
```
**Fix:** Re-install Python and make sure to check **"Add Python to PATH"**

---

### ❌ PowerShell script disabled
```
cannot be loaded because running scripts is disabled on this system
```
**Fix:** Run this in PowerShell (once):
```
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

---

### ❌ `ModuleNotFoundError: No module named 'tkinter'`
**Fix:**
```
pip install tk
```

---

### ❌ Antivirus blocks the .exe
PyInstaller-built apps are sometimes flagged by antivirus as false positives.
**Fix:** Add an exception for the `dist` folder in your antivirus settings,
or temporarily disable real-time protection during the build.

---

### ❌ .exe crashes immediately (no error window)
Run from terminal to see the error message:
```
dist\ChessEngineArena.exe
```

---

### ❌ Icon not showing on the .exe
- Make sure `assets\logo.ico` exists in the project folder
- The `.ico` file must be a real ICO format (not a renamed PNG)
- Try the full absolute path: `--icon=C:\full\path\to\assets\logo.ico`

---

### ❌ sqlite3 error
SQLite3 is **built into Python** — no separate install needed.
It is automatically bundled by PyInstaller. If you still get an error,
make sure `'sqlite3'` is listed under `hiddenimports` in `chess_arena.spec`.

---

## 📝 Notes

- The `.exe` is a **single-file** bundle — no installer or extra files needed
- The `chess_arena.db` database is created automatically next to the `.exe`
- Requires a **UCI-compatible chess engine** to play (e.g. Stockfish, Komodo, Leela)
  - Download Stockfish free at: **https://stockfishchess.org/download**
- The `.exe` size will be ~30–60 MB — this is normal (Python runtime is bundled inside)

---

## 🎮 How to Use

1. Run `ChessEngineArena.exe`
2. Select **Play Mode**: Engine vs Engine, or Play vs Engine
3. Click **`…`** to browse and load a UCI engine `.exe` (e.g. `stockfish.exe`)
4. Set move time and delay
5. Click **▶ START GAME**