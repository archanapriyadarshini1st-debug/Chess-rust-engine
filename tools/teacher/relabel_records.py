#!/usr/bin/env python3
"""Relabel packed 28-byte training records with Stockfish 19 MAX at a fixed depth (Agent TL, EXP-TL1).

Input  : records exactly as written by `datagen-bin` / read by tools/nnue/train.py
         (occ u64 | 16 B = 32 piece nibbles, ascending square, piece = color*6+type | stm u8 | score i16 | wdl u8).
Output : same layout, same ORDER, same `wdl` (the played game's outcome is never touched), but `score` is the
         Stockfish 19 score (UCI_LimitStrength off, side-to-move POV, mates clipped to +-3000).
Teacher and outcome stay separate supervision: only `score` is replaced; `wdl` keeps its game-result meaning.

Information the packed record does NOT carry, and what is assumed (documented, not hidden):
  * castling rights  -> inferred: a right is granted iff king and rook stand on their original squares.
    (the 768-feature net cannot see castling rights either, so the inferred right is the best average label)
  * en-passant square, halfmove clock, history -> none / 0 / empty.
Positions that are illegal under these rules (e.g. side not to move is in check), or where the side to move
is in check or has no legal move, are DROPPED and counted; nothing is silently relabelled with a stand-in.

A provenance JSON is written next to the output (SF version + binary sha256, depth, hash, host, input sha256, counts).
Refuses depth < 10 (EXP-P1: shallower labels leave >7% of the label variance unexplained).
"""
import argparse, hashlib, json, multiprocessing as mp, os, platform, re, subprocess, sys, time
import numpy as np

REC = np.dtype([("occ", "<u8"), ("pcs", "u1", (16,)), ("stm", "u1"), ("score", "<i2"), ("wdl", "u1")])
assert REC.itemsize == 28
MIN_DEPTH = 10
PIECE_CH = "PNBRQKpnbrqk"  # index = color*6 + type
SCORE_RE = re.compile(r"score (cp|mate) (-?\d+)")


def rec_to_fen(r):
    """Packed record -> FEN (castling inferred as documented above), or None if the nibbles are inconsistent."""
    occ = int(r["occ"])
    pcs = bytes(r["pcs"])
    n = bin(occ).count("1")
    if n > 32 or n < 2:
        return None
    nib = []
    for b in pcs:
        nib.append(b & 15)
        nib.append(b >> 4)
    board = {}
    k = 0
    for sq in range(64):
        if occ >> sq & 1:
            p = nib[k]
            if p > 11:
                return None
            board[sq] = PIECE_CH[p]
            k += 1
    rows = []
    for rank in range(7, -1, -1):
        s, e = "", 0
        for f in range(8):
            c = board.get(rank * 8 + f)
            if c is None:
                e += 1
            else:
                s += (str(e) if e else "") + c
                e = 0
        rows.append(s + (str(e) if e else ""))
    cast = ""
    if board.get(4) == "K":
        cast += "K" if board.get(7) == "R" else ""
        cast += "Q" if board.get(0) == "R" else ""
    if board.get(60) == "k":
        cast += "k" if board.get(63) == "r" else ""
        cast += "q" if board.get(56) == "r" else ""
    return "%s %s %s - 0 1" % ("/".join(rows), "w" if r["stm"] == 0 else "b", cast or "-")


class UCI:
    def __init__(self, path, hash_mb):
        self.p = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.send("uci"); self.wait("uciok")
        self.name = self.name_line
        for o, v in (("Threads", 1), ("Hash", hash_mb), ("UCI_LimitStrength", "false"), ("MultiPV", 1)):
            self.send("setoption name %s value %s" % (o, v))
        self.send("isready"); self.wait("readyok")

    name_line = "?"

    def send(self, s):
        self.p.stdin.write(s + "\n"); self.p.stdin.flush()

    def wait(self, tok):
        last = []
        for line in self.p.stdout:
            line = line.strip()
            if line.startswith("id name"):
                self.name_line = line[8:]
            last.append(line)
            if line.startswith(tok):
                return last
        raise RuntimeError("engine died waiting for " + tok)

    def label(self, fen, depth):
        self.send("position fen " + fen)
        self.send("go depth %d" % depth)
        lines = self.wait("bestmove")
        best = lines[-1].split()
        if len(best) < 2 or best[1] in ("(none)", "0000"):
            return None  # no legal move: mate/stalemate
        sc = None
        for l in lines:
            m = SCORE_RE.search(l)
            if m and " pv " in l and "multipv" not in l.replace("multipv 1", ""):
                sc = m.groups()
        if sc is None:
            return None
        kind, v = sc[0], int(sc[1])
        if kind == "mate":
            v = 3000 if v > 0 else -3000
        return max(-3000, min(3000, v))

    def close(self):
        try:
            self.send("quit"); self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def work(args):
    sf, depth, hash_mb, chunk_bytes = args
    import chess  # only for the legality gate; labels come from the engine
    recs = np.frombuffer(chunk_bytes, dtype=REC)
    eng = UCI(sf, hash_mb)
    eng.send("ucinewgame"); eng.send("isready"); eng.wait("readyok")
    out = np.empty(len(recs), dtype=REC)
    k = bad_fen = illegal = in_check = no_move = 0
    delta = 0.0
    for r in recs:
        fen = rec_to_fen(r)
        if fen is None:
            bad_fen += 1; continue
        b = chess.Board(fen)
        if not b.is_valid():
            illegal += 1; continue
        if b.is_check():
            in_check += 1; continue
        sc = eng.label(fen, depth)
        if sc is None:
            no_move += 1; continue
        o = out[k]; o["occ"] = r["occ"]; o["pcs"] = r["pcs"]; o["stm"] = r["stm"]; o["wdl"] = r["wdl"]; o["score"] = sc
        delta += abs(sc - int(r["score"]))
        k += 1
    name = eng.name; eng.close()
    return out[:k].tobytes(), dict(n=k, bad_fen=bad_fen, illegal=illegal, in_check=in_check, no_move=no_move, sum_abs_delta=delta, sf=name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stockfish", required=True)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--depth", type=int, default=12)
    ap.add_argument("--procs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--hash", type=int, default=32)
    ap.add_argument("--chunk", type=int, default=5000, help="records per task (a fresh engine per chunk => reproducible)")
    ap.add_argument("--limit", type=int, default=0, help="only the first N records (smoke tests)")
    a = ap.parse_args()
    if a.depth < MIN_DEPTH:
        sys.exit("refusing depth %d < %d" % (a.depth, MIN_DEPTH))
    raw = open(a.inp, "rb").read()
    if len(raw) % 28:
        sys.exit("input size is not a multiple of 28")
    if a.limit:
        raw = raw[: a.limit * 28]
    sf_sha = hashlib.sha256(open(a.stockfish, "rb").read()).hexdigest()
    tasks = [(a.stockfish, a.depth, a.hash, raw[i : i + a.chunk * 28]) for i in range(0, len(raw), a.chunk * 28)]
    t0 = time.time()
    tot = dict(n=0, bad_fen=0, illegal=0, in_check=0, no_move=0, sum_abs_delta=0.0)
    ver = "?"
    with mp.Pool(a.procs) as pool, open(a.out, "wb") as f:
        for i, (data, st) in enumerate(pool.imap(work, tasks)):  # imap keeps input order
            f.write(data); ver = st["sf"]
            for k in tot:
                tot[k] += st[k]
            if i % 20 == 0:
                print("%d/%d labelled, %.0f pos/s" % (tot["n"], len(raw) // 28, tot["n"] / max(1e-9, time.time() - t0)), file=sys.stderr, flush=True)
    prov = {
        "tool": "tools/teacher/relabel_records.py", "teacher": ver, "stockfish_sha256": sf_sha, "uci_limit_strength": False,
        "depth": a.depth, "threads_per_engine": 1, "procs": a.procs, "hash_mb": a.hash, "score_pov": "side_to_move",
        "mate_cp": 3000, "wdl": "unchanged: played-game outcome, side-to-move POV (0 loss,1 draw,2 win)",
        "input": os.path.basename(a.inp), "input_sha256": hashlib.sha256(raw).hexdigest(), "input_records": len(raw) // 28,
        "records_out": tot["n"], "dropped": {k: tot[k] for k in ("bad_fen", "illegal", "in_check", "no_move")},
        "mean_abs_delta_vs_input_score_cp": round(tot["sum_abs_delta"] / max(1, tot["n"]), 2),
        "castling": "inferred from king/rook home squares", "ep": "none", "order": "input order preserved",
        "host": platform.platform(), "cpus": os.cpu_count(), "seconds": round(time.time() - t0, 1),
    }
    json.dump(prov, open(a.out + ".provenance.json", "w"), indent=2)
    print(json.dumps(prov, indent=2))


if __name__ == "__main__":
    main()
