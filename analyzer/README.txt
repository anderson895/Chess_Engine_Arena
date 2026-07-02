Place your Stockfish engine here for move quality analysis.
Supported filenames (auto-detected at startup):
  - stockfish.exe
  - stockfish_18_x86-64.exe
  - stockfish_x86-64.exe
  - stockfish (Linux/Mac)

This engine runs alongside the game to rate every move as
Book / Brilliant / Best / Excellent / Great / Good / Inaccuracy /
Mistake / Blunder.

IMPORTANT — NNUE network files
------------------------------
Small Stockfish builds need their NNUE network files placed in this
folder next to the .exe (they are too large for the git repo, so
download them after cloning):

  https://tests.stockfishchess.org/api/nn/nn-c288c895ea92.nnue   (~104 MB)
  https://tests.stockfishchess.org/api/nn/nn-37f18f62d772.nnue   (~3 MB)

If the network files are missing, the engine passes the UCI handshake
but dies on its first search — the app detects this at startup and
reports "No analyzer" instead of failing silently. The exact filenames
your build needs are printed by the engine itself (run it in a console
and type "go"; it prints the download URL).
