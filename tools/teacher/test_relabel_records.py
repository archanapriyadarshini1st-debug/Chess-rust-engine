#!/usr/bin/env python3
"""Unit tests for tools/teacher/relabel_records.py (no engine needed except the optional end-to-end test).
Run: python3 tools/teacher/test_relabel_records.py [--stockfish PATH]"""
import os, random, subprocess, sys, tempfile, unittest
import numpy as np, chess
sys.path.insert(0, os.path.dirname(__file__))
import relabel_records as R

SF = None


def pack(board, score=0, wdl=1):
    r = np.zeros(1, dtype=R.REC)[0]
    occ, nib = 0, []
    for sq in range(64):
        p = board.piece_at(sq)
        if p is not None:
            occ |= 1 << sq
            nib.append((0 if p.color else 6) + p.piece_type - 1)
    nib += [0] * (32 - len(nib))
    r["occ"] = occ
    r["pcs"] = np.array([nib[2 * i] | (nib[2 * i + 1] << 4) for i in range(16)], np.uint8)
    r["stm"] = 0 if board.turn else 1
    r["score"] = score; r["wdl"] = wdl
    return r


def random_positions(n, seed=1):
    rnd = random.Random(seed)
    out = []
    while len(out) < n:
        b = chess.Board()
        for _ in range(rnd.randint(8, 70)):
            mv = list(b.legal_moves)
            if not mv:
                break
            b.push(rnd.choice(mv))
        if not b.is_game_over() and not b.is_check():
            out.append(b)
    return out


class T(unittest.TestCase):
    def test_roundtrip_pieces_and_stm(self):
        for b in random_positions(300):
            fen = R.rec_to_fen(pack(b))
            c = chess.Board(fen)
            self.assertEqual(c.board_fen(), b.board_fen())
            self.assertEqual(c.turn, b.turn)

    def test_castling_inference(self):
        self.assertIn(" KQkq ", R.rec_to_fen(pack(chess.Board())))
        b = chess.Board(); b.push_san("e4"); b.push_san("e5"); b.push_san("Ke2"); b.push_san("Ke7")
        self.assertIn(" - 0 1", R.rec_to_fen(pack(b)))   # kings moved: no rights
        b = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        self.assertTrue(chess.Board(R.rec_to_fen(pack(b))).has_queenside_castling_rights(chess.WHITE))

    def test_garbage_rejected(self):
        r = pack(chess.Board()); r["pcs"] = np.full(16, 0xFF, np.uint8)
        self.assertIsNone(R.rec_to_fen(r))

    def test_end_to_end_order_wdl_and_known_scores(self):
        if not SF:
            self.skipTest("needs --stockfish")
        ps = random_positions(40, seed=7)
        recs = np.array([pack(b, score=1234, wdl=i % 3) for i, b in enumerate(ps)], dtype=R.REC)
        with tempfile.TemporaryDirectory() as d:
            i, o = os.path.join(d, "in.bin"), os.path.join(d, "out.bin")
            recs.tofile(i)
            subprocess.check_call([sys.executable, os.path.join(os.path.dirname(__file__), "relabel_records.py"), "--stockfish", SF,
                                   "--in", i, "--out", o, "--depth", "10", "--procs", "2", "--chunk", "7"], stdout=subprocess.DEVNULL)
            out = np.fromfile(o, dtype=R.REC)
            self.assertEqual(len(out), len(recs))                      # nothing dropped (all legal, none in check)
            self.assertTrue((out["occ"] == recs["occ"]).all())           # order preserved
            self.assertTrue((out["wdl"] == recs["wdl"]).all())           # game outcome untouched
            self.assertTrue((out["score"] != 1234).mean() > 0.9)         # score really replaced
            self.assertTrue(np.abs(out["score"]).max() <= 3000)


if __name__ == "__main__":
    if "--stockfish" in sys.argv:
        k = sys.argv.index("--stockfish"); SF = sys.argv[k + 1]; del sys.argv[k : k + 2]
    unittest.main()
