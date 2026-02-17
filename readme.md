# ♟️ Chess Engine Arena - Enhanced Edition

A powerful and beautiful chess engine battleground with full UCI support, game statistics tracking, and interactive PGN replay.

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.7+-green)
![License](https://img.shields.io/badge/license-MIT-orange)

## ✨ Features

### 🎮 Core Features
- **Full UCI Engine Support** - Compatible with Stockfish, Komodo, Leela Chess Zero, and any UCI-compliant engine
- **Complete Chess Rules** - Castling, en passant, promotion, check/checkmate detection
- **Draw Detection** - Stalemate, 50-move rule, threefold repetition, insufficient material
- **Real-time Evaluation** - Live engine evaluation scores and search depth display
- **Material Tracking** - Dynamic material advantage calculation

### 📊 Database & Statistics
- **SQLite Database** - Automatic game recording and history tracking
- **Engine Statistics** - Win/loss records, win rates, match counts
- **Game History Browser** - View all past games with detailed information
- **PGN Export** - Export games in standard PGN format

### 🎬 Interactive PGN Viewer
- **Board Replay** - Navigate through games move-by-move
- **Button Controls** - Start, Previous, Next, End navigation
- **Keyboard Shortcuts** - Arrow keys for quick navigation
- **Move Highlighting** - Visual indication of last move
- **Position Display** - Current move number and player turn

### 🎨 Modern UI
- **Dark Theme** - Professional, eye-friendly interface
- **Responsive Design** - Adjustable window size
- **Board Flipping** - View from either side
- **Victory Dialog** - Beautiful game-over screen with winner display
- **Real-time Updates** - Live move logging and engine output

---

## 📋 Requirements

### System Requirements
- **Operating System**: Windows 10/11, Linux, or macOS
- **Python**: 3.7 or higher
- **RAM**: 2GB minimum (4GB+ recommended for stronger engines)
- **Storage**: 50MB for application + space for database

### Python Dependencies
```
tkinter (included with Python)
sqlite3 (included with Python)
```

**No external dependencies required!** ✅

---

## 🚀 Quick Start

### 1. Download the Program

**Option A: Clone Repository**
```bash
git clone https://github.com/yourusername/chess-engine-arena.git
cd chess-engine-arena
```

**Option B: Direct Download**
- Download `chess_arena.py`
- Save to your preferred folder

### 2. Get Chess Engines

Download UCI chess engines (examples):

**Stockfish** (Recommended - Free & Strong)
- Download: https://stockfishchess.org/download/
- Extract `stockfish.exe` (Windows) or `stockfish` (Linux/Mac)

**Other Popular Engines:**
- **Komodo**: https://komodochess.com/
- **Leela Chess Zero**: https://lczero.org/
- **Arasan**: https://www.arasanchess.org/

### 3. Run the Application

**Windows:**
```bash
python chess_arena.py
```

**Linux/Mac:**
```bash
python3 chess_arena.py
```

### 4. Load Engines

1. Click the **"…"** button next to "Engine 1 (Black)"
2. Browse and select your first engine (e.g., `stockfish.exe`)
3. Click the **"…"** button next to "Engine 2 (White)"
4. Browse and select your second engine
5. Click **"▶ START GAME"**

---

## 📖 User Guide

### Starting a Match

1. **Load Engines**
   - Click "…" buttons to select engine executables
   - Engine names are auto-detected from filename

2. **Configure Settings**
   - **Move time (ms)**: Time each engine has to think (default: 1000ms)
   - **Move delay (s)**: Delay between moves for viewing (default: 0.5s)

3. **Start Game**
   - Click "▶ START GAME"
   - Watch engines battle in real-time!

### During a Game

| Button | Function |
|--------|----------|
| ⏸ PAUSE / RESUME | Pause or resume the game |
| ⏹ STOP GAME | End the current game |
| ↺ NEW GAME | Reset board for a new game |
| ⇅ FLIP BOARD | View from opposite side |
| 💾 EXPORT PGN | Save current game as PGN |

### Viewing Statistics

1. Click **"📊 STATISTICS"**
2. View engine win/loss records
3. Click **"View Game History"** to see all games
4. Select any game and click **"View PGN"** to replay

### PGN Replay Controls

| Control | Action |
|---------|--------|
| ⏮ Start | Go to starting position |
| ◀ Prev | Previous move |
| Next ▶ | Next move |
| End ⏭ | Jump to final position |
| ← / → Keys | Navigate moves |
| Home / End Keys | Start / Final position |

---

## 🔧 Configuration

### Database Location

By default, the database is saved in the same folder as the program:
```
your_folder/
├── chess_arena.py
└── chess_arena.db  ← Auto-created
```

**To change database location:**

Edit line ~665 in the code:
```python
# Current (same folder as program):
self.db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chess_arena.db")

# Alternative (custom location):
self.db_path = "C:/MyChessData/chess_arena.db"  # Windows
self.db_path = "/home/user/chess/chess_arena.db"  # Linux/Mac
```

### Engine Settings

**Stronger Play (Longer Thinking Time):**
```
Move time (ms): 5000-10000
```

**Faster Games (Shorter Thinking Time):**
```
Move time (ms): 500-1000
```

**Match Speed (Move Delay):**
```
Move delay (s): 0 = No delay (fast)
Move delay (s): 1-2 = Good for watching
```

---

## 📦 Building Executables

### Windows Executable (.exe)

**Using PyInstaller:**

1. **Install PyInstaller**
   ```bash
   pip install pyinstaller
   ```

2. **Create Executable**
   ```bash
   pyinstaller --onefile --windowed --name "ChessArena" chess_arena.py
   ```

3. **Find Your .exe**
   ```
   dist/ChessArena.exe  ← Distribute this file
   ```

**With Custom Icon (Optional):**
```bash
pyinstaller --onefile --windowed --icon=chess_icon.ico --name "ChessArena" chess_arena.py
```

### Linux/Mac Executable

**Using PyInstaller:**

```bash
# Install
pip3 install pyinstaller

# Build
pyinstaller --onefile --windowed --name "ChessArena" chess_arena.py

# Result
dist/ChessArena  ← Your executable
```

**Make Executable:**
```bash
chmod +x dist/ChessArena
./dist/ChessArena
```

---

## 🗂️ Project Structure

```
chess-engine-arena/
│
├── chess_arena.py  # Main application
├── chess_arena.db                  # SQLite database (auto-created)
├── README.md                       # This file
│
├── engines/                        # (Optional) Store your engines here
│   ├── stockfish.exe
│   ├── komodo.exe
│   └── lc0.exe
│
└── dist/                          # (Created by PyInstaller)
    └── ChessArena.exe             # Compiled executable
```

---

## 🎯 Usage Examples

### Example 1: Quick Match
```
1. Load Stockfish as Engine 1 (Black)
2. Load Komodo as Engine 2 (White)
3. Set move time: 1000ms
4. Click START GAME
5. Watch the battle!
```

### Example 2: Tournament Setup
```
1. Set move time: 5000ms (strong play)
2. Run multiple games
3. Click STATISTICS to see who wins more
4. View game history to analyze positions
```

### Example 3: Study Games
```
1. Play several games
2. Click STATISTICS → View Game History
3. Select interesting game
4. Click View PGN
5. Use ◀ Prev / Next ▶ to review moves
```

---

## 🐛 Troubleshooting

### Engine Not Found
**Problem**: "Engine not found" error

**Solution**:
- Verify the engine file exists
- Check file permissions (Linux/Mac: `chmod +x engine_file`)
- Ensure full path is correct

### No UCI Response
**Problem**: Engine doesn't respond

**Solution**:
- Make sure engine is UCI-compatible
- Try a different engine (e.g., Stockfish)
- Check engine version compatibility

### Database Error
**Problem**: Database write errors

**Solution**:
- Check folder write permissions
- Ensure disk space available
- Delete `chess_arena.db` to reset

### Board Not Updating
**Problem**: Board frozen during game

**Solution**:
- Click STOP GAME
- Restart the application
- Check if engines are still running

---

## 📊 Database Schema

The SQLite database stores game data:

```sql
CREATE TABLE games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    white_engine TEXT NOT NULL,
    black_engine TEXT NOT NULL,
    result TEXT NOT NULL,           -- "1-0", "0-1", "1/2-1/2"
    reason TEXT NOT NULL,            -- "Checkmate", "Stalemate", etc.
    date TEXT NOT NULL,              -- "2025.02.17"
    time TEXT NOT NULL,              -- "14:30:22"
    pgn TEXT NOT NULL,               -- Full PGN notation
    move_count INTEGER,              -- Number of moves
    duration_seconds INTEGER         -- Game duration
);
```

**View Database:**
- Use [DB Browser for SQLite](https://sqlitebrowser.org/)
- Or Python: `sqlite3 chess_arena.db`

---

## 🔑 Keyboard Shortcuts

### Main Window
| Shortcut | Action |
|----------|--------|
| Space | Pause/Resume |
| Escape | Stop Game |
| N | New Game |
| F | Flip Board |
| Ctrl+S | Export PGN |

### PGN Viewer
| Shortcut | Action |
|----------|--------|
| ← Left | Previous move |
| → Right | Next move |
| Home | Start position |
| End | Final position |
| Escape | Close viewer |

---

## 🤝 Contributing

Contributions are welcome! Here's how:

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

---

## 📝 License

This project is licensed under the MIT License.

```
MIT License

Copyright (c) 2025 Chess Engine Arena

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
```

---

## 🙏 Acknowledgments

- **Stockfish Team** - For the amazing open-source chess engine
- **UCI Protocol** - Universal Chess Interface standard
- **Chess Community** - For inspiration and support
- **Python & Tkinter** - For making this possible

---

## 📞 Support

### Get Help
- **Issues**: Open an issue on GitHub
- **Questions**: Check existing issues or create new one
- **Email**: your-email@example.com

### Useful Links
- **Stockfish**: https://stockfishchess.org/
- **UCI Protocol**: https://www.chessprogramming.org/UCI
- **Chess Programming Wiki**: https://www.chessprogramming.org/

---

## 🎓 FAQ

**Q: Can I use any chess engine?**
A: Yes! Any UCI-compatible engine works. Stockfish, Komodo, Leela Chess Zero, etc.

**Q: How do I make engines play stronger?**
A: Increase "Move time (ms)" to 5000-10000. More time = stronger play.

**Q: Can I watch games in slow motion?**
A: Yes! Increase "Move delay (s)" to 1-2 seconds.

**Q: Where are my games saved?**
A: In `chess_arena.db` in the same folder as the program.

**Q: Can engines use opening books?**
A: Yes, if the engine has opening books configured, they work automatically.

**Q: Can I run this on Raspberry Pi?**
A: Yes! Python 3.7+ and Tkinter are available on Raspberry Pi OS.

**Q: How do I delete game history?**
A: Delete the `chess_arena.db` file. It will auto-recreate on next run.

**Q: Can I use this for engine testing?**
A: Absolutely! Perfect for comparing engine strengths and testing parameters.

---

## 🚀 Roadmap

### Planned Features
- [ ] Time control presets (Blitz, Rapid, Classical)
- [ ] Opening book integration
- [ ] Multiple game tournaments
- [ ] ELO rating calculation
- [ ] Engine parameter configuration
- [ ] Move analysis annotations
- [ ] Export to multiple formats (ChessBase, etc.)
- [ ] Network play support

---

## 📸 Screenshots

### Main Interface
```
┌────────────────────────────────────────────────────────────┐
│  Engine Arena                      ♟️ Chess Board           │
│  ├─ Engine 1 (Black): Stockfish    ┌─────────────────┐    │
│  │  Eval: +0.35  Depth: 20         │  ♜ ♞ ♝ ♛ ♚ ♝ ♞ ♜  │    │
│  ├─ Engine 2 (White): Komodo       │  ♟ ♟ ♟ ♟ ♟ ♟ ♟ ♟  │    │
│  │  Eval: -0.28  Depth: 18         │  . . . . . . . .  │    │
│  ├─ Settings                        │  . . . . ♙ . . .  │    │
│  │  Move time: 1000ms               │  . . . . . . . .  │    │
│  │  Move delay: 0.5s                │  . . . . . . . .  │    │
│  └─ [▶ START] [⏸ PAUSE] [⏹ STOP]  │  ♙ ♙ ♙ ♙ . ♙ ♙ ♙  │    │
│                                     │  ♖ ♘ ♗ ♕ ♔ ♗ ♘ ♖  │    │
│                                     └─────────────────┘    │
└────────────────────────────────────────────────────────────┘
```

---

**Made with ❤️ for the Chess Community**

**Version**: 1.0.0  
**Last Updated**: February 2025  
**Author**: Your Name

---

## ⭐ Star This Project

If you find this useful, please star the repository!

```bash
# Get the latest version
git pull origin main

# Stay updated!
```

Happy Chess Engine Battling! ♟️🔥