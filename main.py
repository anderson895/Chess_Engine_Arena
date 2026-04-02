# ═══════════════════════════════════════════════════════════
#  main.py — Application entry point
#
#  Run:  python main.py
# ═══════════════════════════════════════════════════════════

import tkinter as tk
from ui.loading_screen import LoadingScreen


def main():
    root = tk.Tk()
    try:
        root.iconbitmap("")   # hide default Tk icon on Windows
    except Exception:
        pass
    LoadingScreen(root)
    root.mainloop()


if __name__ == "__main__":
    main()
