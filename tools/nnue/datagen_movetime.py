#!/usr/bin/env python3
"""Teacher data (MOVETIME variant, Agent A): Stockfish 19 at FULL strength
(UCI_LimitStrength off) plays itself with a real wall-clock budget per move,
HARD FLOOR 500 ms.  Never 26 ms / 20k-node / 100-120 ms games.
Same 28-byte record as datagen.py (agent B) so tools/nnue/train.py eats it unchanged.
Opening diversity: ~40 embedded mainline openings (cut at 6/8/10 plies) + 0-2 random plies.
We store quiet positions as packed 28-byte records:
    occ u64 | 16 bytes of piece nibbles (color*6+type, ascending square) | stm u8 |
    score i16 (SF cp, side-to-move POV) | wdl u8 (0 loss, 1 draw, 2 win, stm POV)
Stockfish is only a *teacher of labels*; no Stockfish network is copied anywhere.
"""
import argparse, os, random, struct, sys, time, multiprocessing as mp
import chess, chess.engine

REC = struct.Struct("<Q16sBhB")  # 28 bytes
assert REC.size == 28


def pack(board: chess.Board, score: int, wdl: int) -> bytes:
    occ = 0
    nib = []
    for sq in range(64):
        p = board.piece_at(sq)
        if p is not None:
            occ |= 1 << sq
            nib.append((0 if p.color else 6) + p.piece_type - 1)  # white=0..5 black=6..11
    nib += [0] * (32 - len(nib))
    b = bytes(nib[2 * i] | (nib[2 * i + 1] << 4) for i in range(16))
    return REC.pack(occ, b, 0 if board.turn else 1, score, wdl)


ENDGAMES = ["KQvK", "KRvK", "KPvK", "KBNvK", "KRvKP", "KQvKR", "KRPvKR", "KRvKB", "KRvKN", "KBPvK",
            "KQPvKQ", "KNPvK", "KPPvKP", "KRRvKR", "KQvKP", "KBvKN", "KRBvKR", "KQvKRP", "KPPvK",
            "KRPPvKR", "KBBvKN", "KQRvKQ", "KRNvKR", "KPvKP", "KBPvKB", "KNPvKB"]
PT = {"Q": chess.QUEEN, "R": chess.ROOK, "B": chess.BISHOP, "N": chess.KNIGHT, "P": chess.PAWN, "K": chess.KING}


def random_endgame(rnd):
    """Random legal endgame position from a material recipe like 'KRPvKR'."""
    recipe = rnd.choice(ENDGAMES)
    w, b = recipe.split("v")
    for _ in range(200):
        board = chess.Board(None)
        ok = True
        for color, pieces in ((chess.WHITE, w), (chess.BLACK, b)):
            for ch in pieces:
                for _ in range(50):
                    sq = rnd.randrange(8, 56) if ch == "P" else rnd.randrange(64)
                    if board.piece_at(sq) is None:
                        board.set_piece_at(sq, chess.Piece(PT[ch], color))
                        break
                else:
                    ok = False
        if not ok:
            continue
        board.turn = rnd.random() < 0.5
        if board.is_valid() and not board.is_game_over() and not board.is_insufficient_material():
            return board
    return None


MIN_MS = 500

OPENINGS = """
e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7
e4 e5 Nf3 Nc6 Bb5 Nf6 O-O Nxe4 d4 Nd6
e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 d6
e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Nf6 Nxc6 bxc6
e4 e5 Nf3 Nf6 Nxe5 d6 Nf3 Nxe4 d4 d5
e4 e5 Nc3 Nf6 Bc4 Nxe4 Qh5 Nd6 Bb3 Nc6
e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6
e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6 Nc3 e5
e4 c5 Nf3 e6 d4 cxd4 Nxd4 a6 Bd3 Nf6
e4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7 d3 d6
e4 c5 c3 d5 exd5 Qxd5 d4 Nf6 Nf3 e6
e4 e6 d4 d5 Nc3 Bb4 e5 c5 a3 Bxc3+
e4 e6 d4 d5 Nd2 Nf6 e5 Nfd7 Bd3 c5
e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5 Ng3 Bg6
e4 c6 d4 d5 e5 Bf5 Nf3 e6 Be2 c5
e4 d5 exd5 Qxd5 Nc3 Qa5 d4 Nf6 Nf3 c6
e4 g6 d4 Bg7 Nc3 d6 Nf3 Nf6 Be2 O-O
e4 d6 d4 Nf6 Nc3 g6 f4 Bg7 Nf3 O-O
d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O
d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4 a4 Bf5
d4 d5 c4 dxc4 Nf3 Nf6 e3 e6 Bxc4 c5
d4 d5 Nf3 Nf6 Bf4 e6 e3 c5 c3 Nc6
d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O Bd3 d5
d4 Nf6 c4 e6 Nf3 b6 g3 Ba6 b3 Bb4+
d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O
d4 Nf6 c4 g6 Nc3 d5 cxd5 Nxd5 e4 Nxc3
d4 Nf6 c4 c5 d5 e6 Nc3 exd5 cxd5 d6
d4 Nf6 Nf3 g6 g3 Bg7 Bg2 O-O O-O d6
d4 Nf6 Bg5 Ne4 Bf4 c5 f3 Qa5+ c3 Nf6
c4 e5 Nc3 Nf6 Nf3 Nc6 g3 d5 cxd5 Nxd5
c4 Nf6 Nc3 e6 e4 d5 e5 d4 exf6 dxc3
c4 c5 Nf3 Nf6 Nc3 Nc6 g3 g6 Bg2 Bg7
c4 e6 Nf3 d5 g3 Nf6 Bg2 Be7 O-O O-O
Nf3 d5 g3 Nf6 Bg2 e6 O-O Be7 d3 O-O
Nf3 Nf6 c4 g6 Nc3 Bg7 e4 d6 d4 O-O
Nf3 Nf6 g3 g6 Bg2 Bg7 O-O O-O d3 d6
g3 d5 Bg2 Nf6 Nf3 e6 O-O Be7 d3 O-O
b3 e5 Bb2 Nc6 e3 d5 Bb5 Bd6 f4 Qh4+
f4 d5 Nf3 Nf6 e3 g6 Be2 Bg7 O-O O-O
e4 e5 f4 exf4 Nf3 g5 h4 g4 Ne5 Nf6
"""


def book_lines():
    """Return list of FENs after a mainline prefix (6..10 plies) from OPENINGS."""
    out = []
    for ln in OPENINGS.strip().splitlines():
        sans = ln.split()
        for cut in (6, 8, 10):
            b = chess.Board()
            try:
                for m in sans[:cut]:
                    b.push_san(m)
            except ValueError:
                break
            out.append(b.fen())
    return out



def worker(args):
    wid, sf, minutes, mt_ms, out, seed, book = args
    rnd = random.Random(seed * 1000 + wid)
    eng = chess.engine.SimpleEngine.popen_uci(sf)
    eng.configure({"Threads": 1, "Hash": 64, "UCI_LimitStrength": False})
    t_end = time.time() + minutes * 60
    games = npos = 0
    f = open(out, "ab")
    while time.time() < t_end:
        endgame = rnd.random() < 0.15  # 15% of games start from a random endgame recipe
        if endgame:
            board = random_endgame(rnd)
            if board is None:
                continue
        else:
            if book:
                board = chess.Board(rnd.choice(book))
            else:
                board = chess.Board()
            for _ in range(rnd.randint(0, 2) if book else rnd.randint(4, 8)):
                mv = rnd.choice(list(board.legal_moves))
                board.push(mv)
                if board.is_game_over():
                    break
            if board.is_game_over():
                continue
            info = eng.analyse(board, chess.engine.Limit(time=mt_ms / 1000.0))
            sc = info["score"].pov(chess.WHITE)
            if sc.is_mate() or abs(sc.score()) > 250:
                continue
        recs = []  # (board copy, score_stm)
        win_run = 0  # consecutive plies with |score|>1200 favouring the same side
        win_side = None
        draw_run = 0
        result = None
        while True:
            if board.is_game_over(claim_draw=True) or board.ply() > 400:
                break
            t = max(MIN_MS, int(mt_ms * rnd.uniform(0.9, 1.3))) / 1000.0
            r = eng.play(board, chess.engine.Limit(time=t), info=chess.engine.INFO_SCORE)
            if r.move is None:
                break
            s = r.info["score"].pov(board.turn)
            if s.is_mate():
                cp = 32000 if s.mate() > 0 else -32000
            else:
                cp = s.score()
            quiet = (not board.is_check()) and (not board.is_capture(r.move)) and r.move.promotion is None
            if quiet:
                # decisive positions keep a saturated label (mate -> +-3000) instead of being dropped,
                # otherwise the net never sees "this is simply won" (KQK/KRK drive-to-mate).
                recs.append((pack(board, max(-3000, min(3000, cp)), 1)[:-1], board.turn))
            # adjudication by SF's own score (teacher), generous thresholds
            white_cp = cp if board.turn else -cp
            if abs(white_cp) >= 1500:
                side = white_cp > 0
                win_run = win_run + 1 if win_side == side else 1
                win_side = side
                if win_run >= (12 if endgame else 6):
                    result = 1.0 if side else 0.0
                    break
            else:
                win_run = 0
                win_side = None
            if board.ply() > 90 and abs(white_cp) <= 8:
                draw_run += 1
                if draw_run >= 14:
                    result = 0.5
                    break
            else:
                draw_run = 0
            board.push(r.move)
        if result is None:
            if board.is_game_over(claim_draw=True):
                o = board.outcome(claim_draw=True)
                result = 0.5 if (o is None or o.winner is None) else (1.0 if o.winner else 0.0)
            else:
                result = 0.5
        for body, turn in recs:
            # body is pack() minus the wdl byte; patch score/wdl POV
            w = result if turn else 1.0 - result
            f.write(body + bytes([0 if w == 0.0 else (1 if w == 0.5 else 2)]))
        f.flush()
        games += 1
        npos += len(recs)
        if games % 10 == 0:
            print(f"[w{wid}] games={games} positions={npos}", flush=True)
    eng.quit()
    f.close()
    return games, npos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stockfish", required=True)
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--movetime-ms", type=int, default=500, help="per move, FLOOR 500")
    ap.add_argument("--procs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--out", default="data/shard.bin")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    if a.movetime_ms < MIN_MS:
        print(f"refusing movetime {a.movetime_ms} ms < {MIN_MS} ms (owner rule: no short games)", file=sys.stderr)
        sys.exit(2)
    book = book_lines()
    print(f"book lines: {len(book)}  movetime {a.movetime_ms} ms", flush=True)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    jobs = [(i, a.stockfish, a.minutes, a.movetime_ms, f"{a.out}.{i}", a.seed, book) for i in range(a.procs)]
    with mp.Pool(a.procs) as pool:
        res = pool.map(worker, jobs)
    with open(a.out, "wb") as out:
        for i in range(a.procs):
            p = f"{a.out}.{i}"
            if os.path.exists(p):
                out.write(open(p, "rb").read())
                os.remove(p)
    g = sum(r[0] for r in res)
    n = sum(r[1] for r in res)
    print(f"DONE games={g} positions={n} bytes={os.path.getsize(a.out)}")


if __name__ == "__main__":
    main()
