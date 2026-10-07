# ═══════════════════════════════════════════════════════════
#  engine.py — UCI engine wrapper and dedicated analyzer
# ═══════════════════════════════════════════════════════════

import os
import queue
import subprocess
import sys
import threading
import time


class UCIEngine:
    """
    Wraps a UCI-compatible chess engine subprocess.

    Usage
    -----
    eng = UCIEngine('/path/to/engine', 'MyEngine')
    eng.start()
    best = eng.get_best_move('e2e4 e7e5', movetime_ms=1000)
    eng.stop()
    """

    def __init__(self, path, name="Engine", low_priority=False):
        self.path     = path
        self.name     = name
        self.process  = None
        self.ready    = False
        self.q        = queue.Queue()
        self.last_info = {}
        self.id_name  = None        # the engine's own "id name", once started
        self._options = {}          # UCI options already sent, name → value
        # Run below normal priority — for background analysis that must not
        # take CPU from engines playing a game
        self.low_priority = low_priority
        # One conversation with the engine at a time: two worker threads
        # sharing the output queue would take each other's replies.
        # stop_search() stays outside it — it must reach a running search.
        self._talk = threading.RLock()

    # ── Lifecycle ─────────────────────────────────────────

    def start(self):
        """Start the engine subprocess and perform the UCI handshake."""
        kw = dict(
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            bufsize=1,
        )
        # Run the engine from its own directory so it can find data files
        # placed next to the binary (NNUE networks, opening books, …).
        eng_dir = os.path.dirname(os.path.abspath(self.path))
        if os.path.isdir(eng_dir):
            kw['cwd'] = eng_dir
        if sys.platform == 'win32':
            kw['creationflags'] = subprocess.CREATE_NO_WINDOW
            if self.low_priority:
                kw['creationflags'] |= subprocess.BELOW_NORMAL_PRIORITY_CLASS
        try:
            self.process = subprocess.Popen([self.path], **kw)
        except FileNotFoundError:
            raise RuntimeError(f"Engine not found: {self.path}")
        except PermissionError:
            raise RuntimeError(f"Permission denied: {self.path}")

        threading.Thread(target=self._reader, daemon=True).start()
        self._options = {}          # a fresh process starts on its defaults

        self._send("uci")
        if not self._wait("uciok", 15, on_line=self._note_id):
            raise RuntimeError(f"No 'uciok' from {self.path}")
        self.ready = True

        self._send("isready")
        if not self._wait("readyok", 10):
            raise RuntimeError(f"No 'readyok' from {self.path}")

    def stop(self):
        """Send quit command and terminate the engine subprocess."""
        proc = self.process
        self.process = None
        self.ready   = False
        if proc is None:
            return
        try:
            if proc.poll() is None:
                try:
                    proc.stdin.write("stop\nquit\n")
                    proc.stdin.flush()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=1.5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
        except Exception:
            pass

    @property
    def alive(self):
        """True if the engine process is running."""
        return self.process is not None and self.process.poll() is None

    def stop_search(self):
        """Ask a running search to finish now (its bestmove still arrives)."""
        self._send("stop")

    def set_option(self, name, value):
        """
        Send a UCI option and wait until the engine has applied it.

        Only call this while the engine is idle — options sent during a
        search are applied by some engines and ignored by others. An option
        already at *value* is not sent again, so callers can set it before
        every search without paying for the round trip.

        Returns True once the engine confirms with readyok.
        """
        if not self.ready or not self.alive:
            return False
        with self._talk:
            if self._options.get(name) == value:
                return True
            self._drain()
            self._send(f"setoption name {name} value {value}")
            self._send("isready")
            if not self._wait("readyok", 15):
                return False
            self._options[name] = value
            return True

    # ── Internal I/O ──────────────────────────────────────

    def _reader(self):
        """Background thread: push every stdout line onto self.q."""
        try:
            for line in self.process.stdout:
                self.q.put(line.rstrip('\n'))
        except Exception:
            pass

    def _send(self, cmd):
        """Send a single UCI command to the engine."""
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.write(cmd + '\n')
                self.process.stdin.flush()
            except BrokenPipeError:
                pass

    def _drain(self):
        """Discard all pending output lines."""
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

    def _note_id(self, line):
        if line.startswith("id name "):
            self.id_name = line[len("id name "):].strip()

    def _wait(self, kw, timeout, on_line=None):
        """
        Block until a line starting with *kw* appears, or until *timeout*
        seconds pass. *on_line* sees every line read on the way.
        """
        end = time.time() + timeout
        while time.time() < end:
            try:
                line = self.q.get(timeout=0.2)
                if not line:
                    continue
                if on_line:
                    on_line(line)
                if line.strip() == kw or line.startswith(kw):
                    return True
            except queue.Empty:
                if self.process and self.process.poll() is not None:
                    return False
        return False

    # ── Move / eval requests ──────────────────────────────

    def get_best_move(self, moves_str, movetime_ms=1000, on_info=None,
                      clock=None):
        """
        Ask the engine for its best move.

        Parameters
        ----------
        moves_str : str
            Space-separated UCI move history from the starting position.
        movetime_ms : int
            Milliseconds the engine is allowed to think (fixed-time mode).
        on_info : callable | None
            Optional callback invoked with each parsed ``info`` dict.
        clock : dict | None
            Real-clock mode: ``{"wtime", "btime", "winc", "binc"}`` in ms.
            When given, the engine manages its own time (``go wtime …``)
            and *movetime_ms* is ignored.

        Returns
        -------
        str | None  — UCI move string, or None on failure.
        """
        if not self.ready or not self.alive:
            return None
        self._drain()
        self.last_info = {}

        cmd = (f"position startpos moves {moves_str}"
               if moves_str else "position startpos")
        self._send(cmd)
        if clock:
            self._send(f"go wtime {clock['wtime']} btime {clock['btime']} "
                       f"winc {clock['winc']} binc {clock['binc']}")
            max_wait = max(clock['wtime'], clock['btime']) / 1000 + 10
        else:
            self._send(f"go movetime {movetime_ms}")
            max_wait = (movetime_ms / 1000) + 10
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

    def _search_score(self, moves_str, movetime_ms):
        """
        Run a fixed-time search and return the last reported score.

        Returns
        -------
        (score: int | None, score_type: str)
            Score is from the *side to move*'s perspective, as reported
            by the engine. score_type is 'cp' or 'mate'.
        """
        if not self.ready or not self.alive:
            return None, 'cp'
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
                # Only the principal line counts. With MultiPV above 1 the
                # weaker lines arrive after it, and keeping "the last score
                # seen" would report the second-best move's eval instead.
                # Bound scores are aspiration-window guesses, not results.
                if ('score' in info and 'bound' not in info
                        and info.get('multipv', 1) == 1):
                    last_score      = info['score']
                    last_score_type = info.get('score_type', 'cp')
            elif line.startswith('bestmove'):
                break

        return last_score, last_score_type

    def get_eval(self, moves_str, movetime_ms=200):
        """
        Ask the engine to evaluate a position and return the centipawn score.

        Returns
        -------
        int | None  — centipawn score from White's perspective, or None.
        """
        cp, _ = self._eval_white_pov(moves_str, movetime_ms)
        return cp

    def _eval_white_pov(self, moves_str, movetime_ms):
        """Evaluate a position; return (cp, score_type) from White's perspective."""
        score, score_type = self._search_score(moves_str, movetime_ms)
        if score is None:
            return None, None

        if score_type == 'mate':
            cp = 30000 if score > 0 else -30000
        else:
            cp = score

        # Engines report from the side to move; flip when Black is to move.
        n_moves = len(moves_str.split()) if moves_str else 0
        if n_moves % 2 == 1:
            cp = -cp
        return cp, score_type

    # ── Info parsing ──────────────────────────────────────

    def _parse_info(self, line):
        """Parse a UCI ``info`` line into a dict of named values."""
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
            elif t == 'multipv' and i + 1 < len(tokens):
                try:
                    info['multipv'] = int(tokens[i + 1]); i += 2; continue
                except ValueError:
                    pass
            elif t == 'score' and i + 1 < len(tokens):
                st = tokens[i + 1]
                if st in ('cp', 'mate') and i + 2 < len(tokens):
                    try:
                        info['score']      = int(tokens[i + 2])
                        info['score_type'] = st; i += 3
                        if i < len(tokens) and tokens[i] in ('lowerbound',
                                                             'upperbound'):
                            info['bound'] = tokens[i]; i += 1
                        continue
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
                info['pv'] = tokens[i + 1:]; break
            i += 1
        return info


# ═══════════════════════════════════════════════════════════
#  AnalyzerEngine — dedicated evaluation engine
# ═══════════════════════════════════════════════════════════

class AnalyzerEngine(UCIEngine):
    """
    A dedicated UCIEngine instance for position evaluation and move-quality
    analysis.  Returns scores always from White's perspective.
    """

    def probe(self):
        """
        Run a minimal search to verify the engine can actually evaluate.

        Some builds pass the UCI handshake but die on their first search
        (e.g. Stockfish without its NNUE network file next to the binary).

        Returns
        -------
        bool — True if the engine produced a score and is still alive.
        """
        cp, _ = self.eval_position("", movetime_ms=60)
        return cp is not None and self.alive

    def eval_position(self, moves_str, movetime_ms=150):
        """
        Evaluate a position and return the score from White's perspective.

        Parameters
        ----------
        moves_str : str
            Space-separated UCI move history.
        movetime_ms : int
            Search time in milliseconds.

        Returns
        -------
        (cp: int | None, score_type: str | None)
            cp is the centipawn score from White's perspective.
            score_type is 'cp' or 'mate'.
        """
        return self._eval_white_pov(moves_str, movetime_ms)

    def configure(self, threads=None, hash_mb=None):
        """Size the engine for a long analysis job (threads, hash in MB)."""
        ok = True
        if threads:
            ok &= self.set_option("Threads", int(threads))
        if hash_mb:
            ok &= self.set_option("Hash", int(hash_mb))
        return ok

    def analyse(self, moves_str, movetime_ms=500, multipv=2):
        """
        Search a position and return its best lines, not just a score.

        Move review needs more than one number per position: the engine's
        best move (to tell "Best" from merely good), the runner-up (to tell
        whether the best move was the *only* good one) and the line that
        follows (for the coach text and the best-move arrow).

        Parameters
        ----------
        moves_str : str
            Space-separated UCI history from the start position.
        movetime_ms : int
            Search time in milliseconds.
        multipv : int
            How many lines to return, best first.

        Returns
        -------
        dict | None
            ``{"lines": [{"move", "cp", "mate", "pv", "depth"}, …],
            "bestmove": uci | None}``, or None if the engine failed.
            Scores are from the *side to move's* point of view. A forced
            mate has ``cp`` None and ``mate`` its distance in moves —
            negative when the side to move is being mated, 0 when it is
            already checkmated. A finished game (mate or stalemate) comes
            back as a single line with no move.
        """
        if not self.ready or not self.alive:
            return None
        with self._talk:
            return self._analyse(moves_str, movetime_ms, multipv)

    def _analyse(self, moves_str, movetime_ms, multipv):
        if not self.set_option("MultiPV", int(multipv)):
            return None
        # Sync first: anything still in flight from an earlier search that
        # was cut short arrives before "readyok" and is discarded with it
        self._drain()
        self._send("isready")
        if not self._wait("readyok", 10):
            return None

        cmd = (f"position startpos moves {moves_str}"
               if moves_str else "position startpos")
        self._send(cmd)
        self._send(f"go movetime {movetime_ms}")

        lines = {}
        best = None
        end = time.time() + movetime_ms / 1000 + 10
        stopped = False
        while True:
            if time.time() >= end:
                if stopped:
                    return None          # no bestmove even after "stop"
                # Overran the budget: ask for the answer so the protocol
                # stays in step, then give it a moment to arrive
                self._send("stop")
                stopped = True
                end = time.time() + 3
            try:
                line = self.q.get(timeout=0.2)
            except queue.Empty:
                if self.process is None or self.process.poll() is not None:
                    return None
                continue
            if not line:
                continue
            if line.startswith('info ') and ' score ' in line:
                info = self._parse_info(line)
                if 'score' not in info or 'bound' in info:
                    continue
                pv = info.get('pv') or []
                is_mate = info.get('score_type') == 'mate'
                lines[info.get('multipv', 1)] = {
                    "move":  pv[0] if pv else None,
                    "cp":    None if is_mate else info['score'],
                    "mate":  info['score'] if is_mate else None,
                    "pv":    pv,
                    "depth": info.get('depth', 0),
                }
            elif line.startswith('bestmove'):
                parts = line.split()
                if len(parts) > 1 and parts[1] not in ('(none)', 'null',
                                                       '0000'):
                    best = parts[1]
                break

        ordered = [lines[k] for k in sorted(lines)]
        if not ordered:
            return None
        if best and ordered[0]["move"] != best:
            # The reported best move outranks a stale line 1 left over
            # from an iteration the stop cut short
            for i, ln in enumerate(ordered):
                if ln["move"] == best:
                    ordered.insert(0, ordered.pop(i))
                    break
        if best is None:
            # Mate or stalemate on the board: there is nothing to play,
            # whatever partial lines an iteration may have printed
            ordered = [dict(ordered[0], move=None, pv=[])]
        return {"lines": ordered, "bestmove": best}
