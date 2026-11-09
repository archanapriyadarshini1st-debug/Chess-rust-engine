#!/usr/bin/env python3
"""Label *our* mistakes in games we lost, using Stockfish 19 at real depth/time.

For every position in a lost game where it was our move:
  1. ask SF19 for its best move + score (the teacher), `--movetime` seconds
  2. ask SF19 for the score of the move we actually played (same budget)
  3. keep it if we gave up >= `--min-loss` cp and the position was not already
     decided (|best score| < `--max-abs`) - we learn from decisions, not from
     already-lost positions.

Why not depth-8 / 120 ms labels: shallow labels mostly encode shallow tactics
and noise. Default is 0.5 s/position (roughly depth 20+ on a CI core).

Output JSONL: fen, played, best, best_cp, played_cp, loss_cp, ply, game, phase
"""
import argparse, json, sys
import chess, chess.engine, chess.pgn


def pov_cp(info, color):
    return info["score"].pov(color).score(mate_score=10000)


def phase_of(board):
    pieces = sum(len(board.pieces(t, c)) for t in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN) for c in (True, False))
    if board.fullmove_number <= 12:
        return "opening"
    return "endgame" if pieces <= 6 else "middlegame"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pgn")
    ap.add_argument("--stockfish", required=True)
    ap.add_argument("--engine", default="Rust")
    ap.add_argument("--out", default="missed_moves.jsonl")
    ap.add_argument("--movetime", type=float, default=0.5)
    ap.add_argument("--min-loss", type=int, default=80)
    ap.add_argument("--max-abs", type=int, default=600)
    ap.add_argument("--skip-plies", type=int, default=4)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--hash", type=int, default=128)
    ap.add_argument("--all-games", action="store_true", help="also analyse games we drew/won")
    a = ap.parse_args()

    eng = chess.engine.SimpleEngine.popen_uci(a.stockfish)
    eng.configure({"Threads": a.threads, "Hash": a.hash})
    limit = chess.engine.Limit(time=a.movetime)

    n_games = n_pos = n_bad = 0
    with open(a.pgn) as f, open(a.out, "w") as out:
        gi = 0
        while True:
            g = chess.pgn.read_game(f)
            if g is None:
                break
            gi += 1
            res = g.headers.get("Result", "*")
            white, black = g.headers.get("White", ""), g.headers.get("Black", "")
            if a.engine not in (white, black):
                continue
            ours = chess.WHITE if white == a.engine else chess.BLACK
            lost = (res == "0-1" and ours == chess.WHITE) or (res == "1-0" and ours == chess.BLACK)
            if not lost and not a.all_games:
                continue
            n_games += 1
            board = g.board()
            for ply, node in enumerate(g.mainline()):
                mv = node.move
                if board.turn == ours and ply >= a.skip_plies and not board.is_game_over():
                    n_pos += 1
                    best = eng.analyse(board, limit)
                    best_cp = pov_cp(best, ours)
                    best_mv = best["pv"][0] if best.get("pv") else None
                    if best_mv is not None and best_mv != mv and abs(best_cp) < a.max_abs:
                        alt = eng.analyse(board, limit, root_moves=[mv])
                        played_cp = pov_cp(alt, ours)
                        loss = best_cp - played_cp
                        if loss >= a.min_loss:
                            n_bad += 1
                            out.write(json.dumps({
                                "fen": board.fen(), "played": mv.uci(), "best": best_mv.uci(),
                                "best_cp": best_cp, "played_cp": played_cp, "loss_cp": loss,
                                "ply": ply, "game": gi, "phase": phase_of(board),
                            }) + "\n")
                board.push(mv)
    eng.quit()
    print(f"lost games analysed: {n_games}, positions: {n_pos}, mistakes kept: {n_bad} -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
