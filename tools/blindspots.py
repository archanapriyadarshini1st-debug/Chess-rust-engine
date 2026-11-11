#!/usr/bin/env python3
"""Blind-spot suite extractor (EXP-KB1).

For every game our engine LOST in a fastchess PGN, find the first moment the
opponent's own reported score reached >= +thr (opponent POV) on three
consecutive moves (the "opponent-decisive" ply) and compare it with how long it
took OUR engine to report <= -thr on three consecutive moves. The gap is the
"eval lag". A large lag in quiet middlegame positions points at the static
evaluation (HCE / NNUE), not at search depth or the clock.

Each decisive position is relabelled by a pinned Stockfish teacher (full
strength, fixed movetime, MultiPV) and by our own engine (static eval +
fixed-depth search). Everything is converted to OUR side's point of view, and
our side is always the side to move in the recorded position.

Records are *teacher evaluations*. They are not game outcomes and not WDL.

    python tools/blindspots.py match.pgn --engine Rust \
        --ours ./target/release/chess-rust-engine --stockfish ./stockfish \
        --out blindspots.jsonl
"""
import argparse
import hashlib
import json
import platform
import re
import statistics as st
import subprocess
import sys

import chess
import chess.engine
import chess.pgn

SCORE_RE = re.compile(r"\s*([+-]?\d+\.\d+|[+-]?M\d+|[+-]?#\d+)/(\d+)\s+([\d.]+)s")
VAL = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330, chess.ROOK: 500, chess.QUEEN: 900}


def parse_comment(c):
    m = SCORE_RE.match(c or "")
    if not m:
        return None
    s = m.group(1)
    if "M" in s or "#" in s:
        return (100.0 if not s.startswith("-") else -100.0), int(m.group(2))
    return float(s), int(m.group(2))


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def first_run(seq, pred, n=3):
    for i in range(len(seq) - n + 1):
        if all(pred(x[1]) for x in seq[i:i + n]):
            return seq[i][0]
    return None


def material(board, color):
    return sum(VAL[p.piece_type] for p in board.piece_map().values()
               if p.color == color and p.piece_type in VAL)


def cp(info, pov):
    return info["score"].pov(pov).score(mate_score=10000)


def static_eval(ours_path, fen):
    """Our engine's `eval` debug command: (hce_cp, side-to-move POV)."""
    out = subprocess.run([ours_path], input=f"position fen {fen}\neval\nquit\n",
                         capture_output=True, text=True, timeout=20).stdout
    m = re.search(r"eval_hce (-?\d+)", out)
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pgn")
    ap.add_argument("--engine", default="Rust", help="OUR engine's name in the PGN White/Black tags")
    ap.add_argument("--ours", required=True)
    ap.add_argument("--stockfish", required=True)
    ap.add_argument("--sf-movetime", type=float, default=2.0)
    ap.add_argument("--our-depth", type=int, default=14)
    ap.add_argument("--multipv", type=int, default=3)
    ap.add_argument("--thr", type=float, default=1.0, help="decisive threshold in pawns")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    sf = chess.engine.SimpleEngine.popen_uci(a.stockfish)
    sf.configure({"Threads": 1, "Hash": 64})
    ours = chess.engine.SimpleEngine.popen_uci(a.ours)
    prov = {
        "teacher": sf.id.get("name"), "teacher_sha256": sha(a.stockfish),
        "teacher_movetime_s": a.sf_movetime, "teacher_multipv": a.multipv,
        "teacher_threads": 1, "teacher_limit_strength": False,
        "ours_sha256": sha(a.ours), "ours_depth": a.our_depth,
        "pgn_sha256": sha(a.pgn), "machine": platform.platform(),
        "score_pov": "OUR engine; centipawns; OUR engine is side to move in every record",
        "label_kind": "teacher_evaluation (NOT game outcome, NOT WDL)",
    }

    recs, lags, never, lost = [], [], 0, 0
    with open(a.pgn) as fh:
        gi = 0
        while True:
            g = chess.pgn.read_game(fh)
            if g is None:
                break
            gi += 1
            ours_white = g.headers["White"] == a.engine
            res = g.headers["Result"]
            if res not in ("1-0", "0-1") or (res == "1-0") == ours_white:
                continue
            lost += 1
            our_c = chess.WHITE if ours_white else chess.BLACK
            node, ply = g, 0
            mine, theirs, fens = [], [], {}
            while node.variations:
                node = node.variations[0]
                ply += 1
                fens[ply] = node.board().fen()
                p = parse_comment(node.comment)
                if p:
                    (mine if (ply % 2 == 1) == ours_white else theirs).append((ply, p[0]))
            dec = first_run(theirs, lambda v: v >= a.thr)
            aware = first_run(mine, lambda v: v <= -a.thr)
            if dec is None:
                continue
            if aware is None:
                never += 1
            else:
                lags.append(aware - dec)
            fen = fens[dec]
            b = chess.Board(fen)
            if b.turn != our_c:
                continue
            infos = sf.analyse(b, chess.engine.Limit(time=a.sf_movetime), multipv=a.multipv)
            sf_cp = cp(infos[0], our_c)
            ainfo = ours.analyse(b, chess.engine.Limit(depth=a.our_depth))
            our_cp = cp(ainfo, our_c)
            our_move = ainfo["pv"][0].uci()
            top = [i["pv"][0].uci() for i in infos]
            r = {
                "game": gi, "decisive_ply": dec, "aware_ply": aware,
                "lag_plies": (aware - dec) if aware else None, "fen": fen,
                "teacher_cp": sf_cp, "teacher_best": top[0],
                "teacher_multipv": [{"move": i["pv"][0].uci(), "cp": cp(i, our_c)} for i in infos],
                "ours_static_hce_cp": static_eval(a.ours, fen), "ours_search_cp": our_cp,
                "ours_move": our_move, "overrate_cp": our_cp - sf_cp,
                "ours_move_in_teacher_top": our_move in top,
                "material_diff_cp": material(b, our_c) - material(b, not our_c),
                "n_pieces": len(b.piece_map()),
            }
            recs.append(r)
            print(f"g{gi} ply{dec}: teacher {sf_cp:+d} ours {our_cp:+d} overrate {r['overrate_cp']:+d} "
                  f"mat {r['material_diff_cp']:+d} pieces {r['n_pieces']}", flush=True)
    sf.quit()
    ours.quit()

    with open(a.out, "w") as o:
        o.write(json.dumps({"provenance": prov}) + "\n")
        for r in recs:
            o.write(json.dumps(r) + "\n")

    n = len(recs)
    print(f"\n=== summary: {n} positions from {lost} lost games (PRELIMINARY) ===")
    if n:
        gaps = [r["overrate_cp"] for r in recs]
        quiet = sum(1 for r in recs if abs(r["material_diff_cp"]) <= 100)
        print("median teacher cp %+d | median ours (depth %d) cp %+d | median overrate %+d | mean overrate %+.0f"
              % (st.median(r["teacher_cp"] for r in recs), a.our_depth,
                 st.median(r["ours_search_cp"] for r in recs), st.median(gaps), st.mean(gaps)))
        print("|material diff| <= 100cp (positional, not material): %d of %d" % (quiet, n))
        print("our move inside teacher MultiPV-%d: %d of %d"
              % (a.multipv, sum(r["ours_move_in_teacher_top"] for r in recs), n))
        print("we overrate our position by >= 100cp vs teacher: %d of %d" % (sum(1 for g in gaps if g >= 100), n))
        print("median piece count %s" % st.median(r["n_pieces"] for r in recs))
    if lags:
        print("eval lag plies: median %s mean %.1f n=%d; never aware: %d"
              % (st.median(lags), st.mean(lags), len(lags), never))
    return 0


if __name__ == "__main__":
    sys.exit(main())
