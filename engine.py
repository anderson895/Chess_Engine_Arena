# ═══════════════════════════════════════════════════════════
#  engine.py — UCI engine wrapper and dedicated analyzer
# ═══════════════════════════════════════════════════════════
#
#  KEY PROTOCOL RULES (learned from Arasan/Houdini behaviour):
#
#  1. NEVER send 'stop' to an idle engine.  Many engines re-emit their
#     last bestmove on 'stop', which then contaminates the next search.
#
#  2. setoption and ucinewgame are fire-and-forget per the UCI spec.
#     Do NOT send isready after them — extra readyok responses queue up
#     and are consumed by the WRONG _wait() call, causing get_best_move
#     to fire 'go' before the position command is processed.
#
#  3. The single isready/readyok in get_best_move (sent AFTER position)
#     is the only synchronisation point needed before each search.
#     After readyok arrives, drain once more to flush any late-arriving
#     stale bestmove before sending 'go'.
#
# ═══════════════════════════════════════════════════════════

import queue
import subprocess
import sys
import threading
import time


class UCIEngine:
    def __init__(self, path, name="Engine"):
        self.path      = path
        self.name      = name
        self.process   = None
        self.ready     = False
        self.q         = queue.Queue()
        self.last_info = {}

    # ── Lifecycle ─────────────────────────────────────────

    def start(self):
        kw = dict(
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            bufsize=1,
        )
        if sys.platform == 'win32':
            kw['creationflags'] = subprocess.CREATE_NO_WINDOW
        try:
            self.process = subprocess.Popen([self.path], **kw)
        except FileNotFoundError:
            raise RuntimeError(f"Engine not found: {self.path}")
        except PermissionError:
            raise RuntimeError(f"Permission denied: {self.path}")

        threading.Thread(target=self._reader, daemon=True).start()

        self._send("uci")
        if not self._wait("uciok", 15):
            raise RuntimeError(f"No 'uciok' from {self.path}")
        self.ready = True

        self._send("isready")
        if not self._wait("readyok", 10):
            raise RuntimeError(f"No 'readyok' from {self.path}")

    def stop(self):
        if self.process:
            try:
                self._send("stop"); time.sleep(0.1)
                self._send("quit")
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                pass
            self.process = None
            self.ready   = False

    @property
    def alive(self):
        return self.process is not None and self.process.poll() is None

    # ── Internal I/O ──────────────────────────────────────

    def _reader(self):
        try:
            for line in self.process.stdout:
                self.q.put(line.rstrip('\n'))
        except Exception:
            pass

    def _send(self, cmd):
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.write(cmd + '\n')
                self.process.stdin.flush()
            except BrokenPipeError:
                pass

    def new_game(self):
        """ucinewgame is fire-and-forget — no isready needed."""
        if not self.ready or not self.alive:
            return
        self._send("ucinewgame")
        time.sleep(0.05)
        self._drain()

    def set_option(self, name, value):
        """setoption is fire-and-forget — no isready needed."""
        if not self.ready or not self.alive:
            return
        self._send(f"setoption name {name} value {value}")

    def _drain(self):
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

    def _wait(self, kw, timeout):
        end = time.time() + timeout
        while time.time() < end:
            try:
                line = self.q.get(timeout=0.2)
                if not line:
                    continue
                if line.strip() == kw or line.startswith(kw):
                    return True
            except queue.Empty:
                if self.process and self.process.poll() is not None:
                    return False
        return False

    # ── Move / eval requests ──────────────────────────────

    def get_best_move(self, moves_str, movetime_ms=1000, on_info=None, start_fen=None):
        if not self.ready or not self.alive:
            return None

        # Drain before sending anything.
        # NEVER send 'stop' here — idle engines re-emit their last bestmove
        # on stop; it arrives AFTER drain() and poisons the next search.
        self._drain()
        self.last_info = {}

        if start_fen:
            cmd = (f"position fen {start_fen} moves {moves_str}"
                   if moves_str else f"position fen {start_fen}")
        else:
            cmd = (f"position startpos moves {moves_str}"
                   if moves_str else "position startpos")
        self._send(cmd)

        # Single sync point: engine cannot reply until position is processed.
        self._send("isready")
        if not self._wait("readyok", 10):
            return None

        # Second drain: flush any stale bestmove that arrived during the wait.
        self._drain()

        self._send(f"go movetime {movetime_ms}")

        max_wait = (movetime_ms / 1000) + 15
        end  = time.time() + max_wait
        best = None

        while time.time() < end:
            try:
                line = self.q.get(timeout=0.3)
            except queue.Empty:
                if self.process and self.process.poll() is not None:
                    break
                continue
            if not line:
                continue
            if line.startswith('info '):
                info = self._parse_info(line)
                self.last_info.update(info)
                if on_info:
                    on_info(info)
            elif line.startswith('bestmove'):
                parts = line.split()
                if len(parts) > 1 and parts[1] not in ('(none)', 'null', '0000'):
                    best = parts[1]
                break

        return best

    def get_eval(self, moves_str, movetime_ms=200):
        if not self.ready or not self.alive:
            return None
        self._drain()

        cmd = (f"position startpos moves {moves_str}"
               if moves_str else "position startpos")
        self._send(cmd)
        self._send(f"go movetime {movetime_ms}")

        end = time.time() + movetime_ms / 1000 + 5
        last_score      = None
        last_score_type = 'cp'

        while time.time() < end:
            try:
                line = self.q.get(timeout=0.2)
            except queue.Empty:
                if self.process and self.process.poll() is not None:
                    break
                continue
            if not line:
                continue
            if line.startswith('info '):
                info = self._parse_info(line)
                if 'score' in info:
                    last_score      = info['score']
                    last_score_type = info.get('score_type', 'cp')
            elif line.startswith('bestmove'):
                break

        if last_score is None:
            return None
        if last_score_type == 'mate':
            return 30000 if last_score > 0 else -30000
        return last_score

    # ── Info parsing ──────────────────────────────────────

    def _parse_info(self, line):
        info = {}
        tokens = line.split()[1:]
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t == 'depth' and i + 1 < len(tokens):
                try:
                    info['depth'] = int(tokens[i + 1]); i += 2; continue
                except ValueError:
                    pass
            elif t == 'score' and i + 1 < len(tokens):
                st = tokens[i + 1]
                if st in ('cp', 'mate') and i + 2 < len(tokens):
                    try:
                        info['score']      = int(tokens[i + 2])
                        info['score_type'] = st; i += 3; continue
                    except ValueError:
                        pass
            elif t == 'nodes' and i + 1 < len(tokens):
                try:
                    info['nodes'] = int(tokens[i + 1]); i += 2; continue
                except ValueError:
                    pass
            elif t == 'nps' and i + 1 < len(tokens):
                try:
                    info['nps'] = int(tokens[i + 1]); i += 2; continue
                except ValueError:
                    pass
            elif t == 'pv':
                info['pv'] = tokens[i + 1:i + 6]; break
            i += 1
        return info


# ═══════════════════════════════════════════════════════════
#  AnalyzerEngine — dedicated evaluation engine
# ═══════════════════════════════════════════════════════════

class AnalyzerEngine(UCIEngine):

    def eval_position(self, moves_str, movetime_ms=150):
        if not self.ready or not self.alive:
            return None, None
        self._drain()

        cmd = (f"position startpos moves {moves_str}"
               if moves_str else "position startpos")
        self._send(cmd)
        self._send(f"go movetime {movetime_ms}")

        end  = time.time() + movetime_ms / 1000 + 5
        last_score      = None
        last_score_type = 'cp'

        n_moves      = len(moves_str.split()) if moves_str else 0
        side_to_move = 'w' if n_moves % 2 == 0 else 'b'

        while time.time() < end:
            try:
                line = self.q.get(timeout=0.2)
            except queue.Empty:
                if self.process and self.process.poll() is not None:
                    break
                continue
            if not line:
                continue
            if line.startswith('info '):
                info = self._parse_info(line)
                if 'score' in info:
                    last_score      = info['score']
                    last_score_type = info.get('score_type', 'cp')
            elif line.startswith('bestmove'):
                break

        if last_score is None:
            return None, None

        if last_score_type == 'mate':
            cp = 30000 if last_score > 0 else -30000
        else:
            cp = last_score

        if side_to_move == 'b':
            cp = -cp

        return cp, last_score_type