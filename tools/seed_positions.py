#!/usr/bin/env python3
"""Classic material / endgame FENs so the first net actually sees a queen."""
from __future__ import annotations

import chess

KINGS = [chess.E1, chess.E8, chess.A1, chess.H8, chess.C3, chess.F6, chess.A8, chess.H1]


def kxk(piece: str, squares) -> list[str]:
    out = []
    for wk in (chess.E1, chess.A1, chess.G1, chess.C2):
        for bk in (chess.E8, chess.A8, chess.H8, chess.C7, chess.A5):
            if wk == bk:
                continue
            for sq in squares:
                if sq in (wk, bk):
                    continue
                b = chess.Board(None)
                b.set_piece_at(wk, chess.Piece.from_symbol("K"))
                b.set_piece_at(bk, chess.Piece.from_symbol("k"))
                b.set_piece_at(sq, chess.Piece.from_symbol(piece))
                b.turn = chess.WHITE
                if b.is_valid() and not b.is_check():
                    out.append(b.fen())
                b.turn = chess.BLACK
                if b.is_valid() and not b.is_check():
                    out.append(b.fen())
    return out


def start_minus(symbol: str) -> list[str]:
    out = []
    start = chess.Board()
    for sq, p in start.piece_map().items():
        if p.symbol() == symbol:
            b = start.copy()
            b.remove_piece_at(sq)
            if b.is_valid():
                out.append(b.fen())
                b.turn = chess.BLACK
                if b.is_valid():
                    out.append(b.fen())
    return out


def extra_piece(symbol: str, squares) -> list[str]:
    out = []
    for sq in squares:
        b = chess.Board()
        if b.piece_at(sq) is not None:
            continue
        b.set_piece_at(sq, chess.Piece.from_symbol(symbol))
        if b.is_valid() and not b.is_check():
            out.append(b.fen())
    return out


def main() -> None:
    fens: list[str] = []
    fens.append(chess.Board().fen())
    fens += kxk("Q", [chess.H1, chess.A4, chess.D5, chess.H8, chess.A2, chess.F3])
    fens += kxk("R", [chess.A1, chess.H4, chess.D5, chess.A8, chess.E3])
    fens += kxk("P", [chess.E2, chess.E7, chess.A2, chess.H7, chess.C4, chess.D5])
    fens += kxk("B", [chess.C1, chess.F4, chess.A6])
    fens += kxk("N", [chess.B1, chess.F5, chess.C3])
    for sym in "QRBNP":
        fens += start_minus(sym)
        fens += start_minus(sym.lower())
    fens += extra_piece("Q", [chess.A3, chess.C4, chess.F5])
    fens += extra_piece("q", [chess.A6, chess.C5, chess.F4])
    fens += extra_piece("R", [chess.A3, chess.E4])
    fens += extra_piece("N", [chess.C4, chess.F5])
    # quiet middlegame-ish
    fens.append("r1bq1rk1/pp2ppbp/2np1np1/8/3NP3/2N1B3/PPPQ1PPP/R3KB1R w KQ - 0 9")
    fens.append("rnbqkb1r/pp3ppp/2p1pn2/3p4/2PP4/2N2N2/PP2PPPP/R1BQKB1R w KQkq - 0 6")
    seen = set()
    n = 0
    for fen in fens:
        board = fen.split()[0]
        key = fen
        if key in seen:
            continue
        seen.add(key)
        print(fen)
        n += 1
    print(f"# {n} unique fens", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
