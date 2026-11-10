#!/usr/bin/env python3
"""Independent correctness oracle for a UCI engine, using python-chess as the reference.

[Agent X1] No src/ dependency. Checks, over random-walk games from the opening book
and from start position (half of them capture-biased to reach promotions / ep / castling
rights loss / endgames):
  1. legal-move SET at every ply == python-chess legal moves   (uses `divide 1`)
  2. `divide 3` per-move node counts == python-chess perft(2)     (sampled plies)
  3. `go depth N` bestmove is legal (non-terminal) and engine does not hang
  4. terminal positions (mate/stalemate) do not crash and return a null/none move
  5. `position fen ... moves ...` replay reaches the same position as python-chess
     (checked by comparing legal-move sets after replay, i.e. state equality for move generation)
Exit code 1 on any mismatch; prints reproducible seed + move list for the first failures.

usage: correctness_oracle.py ENGINE [--games 200] [--plies 140] [--seed 1] [--book tools/openings_book.epd]
Requires: pip install chess
"""
import argparse, random, subprocess, sys, os, time, re
import chess

class Eng:
    def __init__(s, path):
        env = dict(os.environ, CRE_NO_NNUE="1")
        s.p = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
        s.send("uci"); s.until("uciok"); s.send("setoption name Hash value 16"); s.sync()
    def send(s, c): s.p.stdin.write(c + "\n"); s.p.stdin.flush()
    def until(s, tok, timeout=60):
        out = []; t0 = time.time()
        while True:
            l = s.p.stdout.readline()
            if l == "": raise RuntimeError("engine died; last output: " + " | ".join(out[-5:]))
            out.append(l.rstrip())
            if l.startswith(tok): return out
            if time.time() - t0 > timeout: raise TimeoutError(tok)
    def sync(s): s.send("isready"); s.until("readyok")
    def setpos(s, fen, moves):
        s.send("position fen " + fen + (" moves " + " ".join(moves) if moves else "")); s.sync()
    def divide(s, d):
        s.send(f"divide {d}"); s.sync()   # readyok arrives after divide output
        return s
    def divide_counts(s, d):
        s.send(f"divide {d}"); s.send("isready")
        res = {}
        while True:
            l = s.p.stdout.readline()
            if l.startswith("readyok"): break
            m = re.match(r"^\s*([a-h][1-8][a-h][1-8][qrbn]?)\s*:\s*(\d+)", l)
            if m: res[m.group(1)] = int(m.group(2))
        return res
    def go(s, depth):
        s.send(f"go depth {depth}")
        out = s.until("bestmove", timeout=120)
        return out[-1].split()[1] if len(out[-1].split()) > 1 else None
    def quit(s):
        try: s.send("quit")
        except Exception: pass

def perft(b, d):
    if d == 0: return 1
    n = 0
    for m in b.legal_moves:
        b.push(m); n += perft(b, d - 1) if d > 1 else 1; b.pop()
    return n

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("engine")
    ap.add_argument("--games", type=int, default=200); ap.add_argument("--plies", type=int, default=140)
    ap.add_argument("--seed", type=int, default=1); ap.add_argument("--book", default=None)
    ap.add_argument("--search-every", type=int, default=25); ap.add_argument("--perft-every", type=int, default=9)
    a = ap.parse_args(); rnd = random.Random(a.seed)
    book = []
    if a.book and os.path.exists(a.book):
        for l in open(a.book):
            l = l.split(";")[0].strip()
            if l and not l.startswith("#"):
                f = l.split(); f += ["0", "1"][: max(0, 6 - len(f))] if len(f) < 6 else []
                book.append(" ".join(f))
    e = Eng(a.engine); fails = []; stats = dict(plies=0, movesets=0, perfts=0, searches=0, terminals=0,
                                                promos=0, eps=0, castles=0, checks=0)
    for g in range(a.games):
        start = rnd.choice(book) if book and g % 2 == 0 else chess.STARTING_FEN
        b = chess.Board(start); moves = []; capbias = (g % 4 >= 2)
        for ply in range(a.plies):
            if not any(True for _ in b.legal_moves):  # UCI-terminal = mate/stalemate only (insufficient material is not terminal)
                # terminal: engine must not crash and must report null/none
                e.setpos(start, moves)
                try: bm = e.go(3)
                except Exception as ex: fails.append(("terminal-crash", start, list(moves), str(ex))); break
                stats["terminals"] += 1
                if bm not in (None, "0000", "(none)", "none", "a1a1"): fails.append(("terminal-bestmove", start, list(moves), bm))
                break
            e.setpos(start, moves)
            em = set(e.divide_counts(1).keys()); pm = {m.uci() for m in b.legal_moves}
            stats["plies"] += 1; stats["movesets"] += 1
            if em != pm:
                fails.append(("legal-set", start, list(moves), "engine-only=%s ref-only=%s" % (sorted(em - pm), sorted(pm - em)))); break
            if ply % a.perft_every == 3:
                ec = e.divide_counts(3); rc = {}
                for m in b.legal_moves:
                    b.push(m); rc[m.uci()] = perft(b, 2); b.pop()
                stats["perfts"] += 1
                if ec != rc:
                    bad = {k: (ec.get(k), rc.get(k)) for k in set(ec) | set(rc) if ec.get(k) != rc.get(k)}
                    fails.append(("perft3", start, list(moves), str(dict(list(bad.items())[:4])))); break
            if ply % a.search_every == 7:
                try: bm = e.go(5)
                except Exception as ex: fails.append(("search-crash", start, list(moves), str(ex))); break
                stats["searches"] += 1
                if bm not in pm: fails.append(("illegal-bestmove", start, list(moves), bm)); break
            ms = list(b.legal_moves)
            if capbias:
                cands = [m for m in ms if b.is_capture(m) or m.promotion] or ms
                m = rnd.choice(cands) if rnd.random() < 0.8 else rnd.choice(ms)
            else: m = rnd.choice(ms)
            if m.promotion: stats["promos"] += 1
            if b.is_en_passant(m): stats["eps"] += 1
            if b.is_castling(m): stats["castles"] += 1
            b.push(m); moves.append(m.uci())
            if b.is_check(): stats["checks"] += 1
        if len(fails) >= 5: break
    e.quit()
    print("oracle stats:", stats)
    if fails:
        print("FAIL: %d mismatch(es) (seed=%d)" % (len(fails), a.seed))
        for f in fails[:5]: print("  ", f[0], "| start:", f[1], "| moves:", " ".join(f[2][-40:]), "(last 40 plies of %d)" % len(f[2]), "|", f[3])
        sys.exit(1)
    print("PASS: engine agrees with python-chess on every checked position (seed=%d)" % a.seed)

if __name__ == "__main__": main()
