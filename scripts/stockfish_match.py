#!/usr/bin/env python3
"""Play Chess-rust-engine vs Stockfish 19.

Teacher games use SF19 at FULL STRENGTH (UCI_LimitStrength off) and a real
time control. 100–120 ms games teach junk — we refuse them.

Ladder games use UCI_Elo so we can actually *measure* ~2000.

Examples:
  python scripts/stockfish_match.py --stockfish ./stockfish --mode ladder \\
      --elo 2000 --games 20 --tc 10+0.1 --pgn results/ladder-2000.pgn

  python scripts/stockfish_match.py --stockfish ./stockfish --mode teacher \\
      --games 8 --movetime-ms 2000 --pgn results/teacher.pgn \\
      --book datasets/teacher_book.txt
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import chess
import chess.engine
import chess.pgn

MIN_MOVETIME_MS = 500
MIN_TC_BASE = 2.0

OPENINGS = [
    "",  # startpos
    "e2e4 e7e5",
    "e2e4 c7c5",
    "d2d4 d7d5",
    "d2d4 g8f6",
    "c2c4 e7e5",
    "g1f3 d7d5",
    "e2e4 e7e6",
    "e2e4 c7c6",
    "d2d4 f7f5",
]


def parse_tc(s: str) -> tuple[float, float]:
    if "+" in s:
        base, inc = s.split("+", 1)
        return float(base), float(inc)
    return float(s), 0.0


def apply_uci_line(board: chess.Board, line: str) -> None:
    for tok in line.split():
        board.push_uci(tok)


def configure_sf(engine: chess.engine.SimpleEngine, args) -> None:
    opts = {"Hash": args.hash_mb, "Threads": 1}
    if args.mode == "ladder":
        opts["UCI_LimitStrength"] = True
        opts["UCI_Elo"] = args.elo
    else:
        # Full strength. Never cap SF19 in teacher mode.
        opts["UCI_LimitStrength"] = False
    try:
        engine.configure(opts)
    except chess.engine.EngineError as e:
        print("warning: configure", e, file=sys.stderr)


def play_game(
    ours: chess.engine.SimpleEngine,
    sf: chess.engine.SimpleEngine,
    our_white: bool,
    opening: str,
    args,
    book_fh,
) -> chess.pgn.Game:
    board = chess.Board()
    apply_uci_line(board, opening)
    game = chess.pgn.Game()
    game.headers["Event"] = f"Chess-rust-engine vs SF19 {args.mode}"
    game.headers["White"] = "Chess-rust-engine" if our_white else "Stockfish 19"
    game.headers["Black"] = "Stockfish 19" if our_white else "Chess-rust-engine"
    game.headers["Opening"] = opening or "startpos"
    node = game
    for mv in board.move_stack:
        node = node.add_variation(mv)

    wtime = btime = args.base_s
    inc = args.inc_s

    while not board.is_game_over(claim_draw=True) and len(board.move_stack) < args.max_ply:
        is_white = board.turn == chess.WHITE
        is_ours = is_white == our_white
        engine = ours if is_ours else sf

        if args.movetime_ms:
            limit = chess.engine.Limit(time=args.movetime_ms / 1000.0)
        else:
            limit = chess.engine.Limit(
                white_clock=max(0.05, wtime),
                black_clock=max(0.05, btime),
                white_inc=inc,
                black_inc=inc,
            )

        fen_before = board.fen()
        t0 = time.perf_counter()
        try:
            play = engine.play(board, limit, info=chess.engine.INFO_NONE)
        except chess.engine.EngineError as e:
            print("engine error", e, file=sys.stderr)
            break
        elapsed = time.perf_counter() - t0
        if is_white:
            wtime = max(0.05, wtime - elapsed + inc)
        else:
            btime = max(0.05, btime - elapsed + inc)

        if play.move is None:
            break
        board.push(play.move)
        node = node.add_variation(play.move)

        if args.mode == "teacher" and is_ours and book_fh is not None:
            # SF19 MAX label from the position we just moved from.
            tmp = chess.Board(fen_before)
            try:
                info = sf.analyse(
                    tmp, chess.engine.Limit(time=max(1.0, args.movetime_ms / 1000.0 if args.movetime_ms else 2.0))
                )
                pv = info.get("pv") or []
                if pv:
                    teacher = pv[0]
                    if teacher != play.move:
                        book_fh.write(f"{fen_before} | {teacher.uci()}\n")
                        book_fh.flush()
            except chess.engine.EngineError:
                pass

    result = board.result(claim_draw=True)
    if result == "*":
        # 200-ply cap: treat as adjudicated draw (endgames we failed to mate).
        result = "1/2-1/2"
        game.headers["Termination"] = "adjudication"
    game.headers["Result"] = result
    return game


def score_of(game: chess.pgn.Game, our_white: bool) -> float:
    r = game.headers.get("Result", "*")
    if r == "1/2-1/2":
        return 0.5
    if r == "1-0":
        return 1.0 if our_white else 0.0
    if r == "0-1":
        return 0.0 if our_white else 1.0
    return 0.0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ours", default="target/release/chess-rust-engine")
    p.add_argument("--stockfish", required=True)
    p.add_argument("--mode", choices=["ladder", "teacher", "smoke"], default="ladder")
    p.add_argument("--elo", type=int, default=2000, help="UCI_Elo for ladder mode")
    p.add_argument("--games", type=int, default=20)
    p.add_argument("--tc", default="10+0.1", help="base+inc seconds, ignored if --movetime-ms")
    p.add_argument("--movetime-ms", type=int, default=0)
    p.add_argument("--hash-mb", type=int, default=64)
    p.add_argument("--max-ply", type=int, default=320)
    p.add_argument("--pgn", default="results/match.pgn")
    p.add_argument("--book", default="datasets/teacher_book.txt")
    args = p.parse_args()

    args.base_s, args.inc_s = parse_tc(args.tc)

    if args.movetime_ms and args.movetime_ms < MIN_MOVETIME_MS:
        print(
            f"refusing movetime {args.movetime_ms} ms (< {MIN_MOVETIME_MS}). "
            "Short games teach bad moves.",
            file=sys.stderr,
        )
        return 2
    if not args.movetime_ms and args.base_s < MIN_TC_BASE:
        print(
            f"refusing tc base {args.base_s}s (< {MIN_TC_BASE}). Use e.g. 10+0.1.",
            file=sys.stderr,
        )
        return 2

    Path(args.pgn).parent.mkdir(parents=True, exist_ok=True)
    if args.mode == "teacher":
        Path(args.book).parent.mkdir(parents=True, exist_ok=True)

    ours = chess.engine.SimpleEngine.popen_uci(args.ours)
    sf = chess.engine.SimpleEngine.popen_uci(args.stockfish)
    try:
        ours.configure({"Hash": args.hash_mb, "Threads": 1})
        configure_sf(sf, args)

        wins = draws = losses = 0
        book_fh = open(args.book, "a", encoding="utf-8") if args.mode == "teacher" else None
        try:
            with open(args.pgn, "w", encoding="utf-8") as pgn_f:
                for g in range(args.games):
                    opening = OPENINGS[g % len(OPENINGS)]
                    our_white = g % 2 == 0
                    game = play_game(ours, sf, our_white, opening, args, book_fh)
                    pts = score_of(game, our_white)
                    if pts == 1:
                        wins += 1
                    elif pts == 0.5:
                        draws += 1
                    else:
                        losses += 1
                    print(
                        f"game {g+1}/{args.games} {'W' if our_white else 'B'} "
                        f"{game.headers['Result']}  running W-D-L {wins}-{draws}-{losses}",
                        flush=True,
                    )
                    print(game, file=pgn_f, end="\n\n")
        finally:
            if book_fh:
                book_fh.close()
    finally:
        ours.quit()
        sf.quit()

    n = max(1, wins + draws + losses)
    score = (wins + 0.5 * draws) / n
    print(f"summary W-D-L {wins}-{draws}-{losses}  score {score:.3f}  n={n}")
    print(f"pgn {args.pgn}")
    if args.mode == "ladder":
        print(f"opponent SF19 UCI_Elo {args.elo}")
    else:
        print("opponent SF19 MAX (UCI_LimitStrength off)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
