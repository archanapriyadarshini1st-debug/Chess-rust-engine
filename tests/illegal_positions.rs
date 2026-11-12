//! EXP-GP2: positions that used to panic the engine (king missing, side NOT to move in
//! check, pawns on the back rank) must be rejected by `from_fen`, and harmless
//! inconsistencies (stale castling rights, bogus en-passant square) must be repaired.
//! A panic inside a game is a forfeit, so this is a correctness test, not a strength test.

use chess_rust_engine::board::Position;

fn parse(fen: &str) -> Option<Position> {
    let _ = chess_rust_engine::attacks::tables();
    Position::from_fen(fen)
}

#[test]
fn rejects_unusable_positions() {
    let bad = [
        // no black king
        "8/8/8/8/8/8/8/4K3 w - - 0 1",
        // no white king
        "4k3/8/8/8/8/8/8/8 w - - 0 1",
        // two white kings
        "4k3/8/8/8/8/8/8/K3K3 w - - 0 1",
        // white to move but black (the side that just moved) is in check from the rook
        "4k3/8/8/8/8/8/8/4RK2 w - - 0 1",
        // black to move but white is in check
        "4k3/8/8/8/8/8/8/4K2r b - - 0 1",
        // pawn on the first / last rank
        "4k3/8/8/8/8/8/8/P3K3 w - - 0 1",
        "p3k3/8/8/8/8/8/8/4K3 w - - 0 1",
        // nine pawns
        "4k3/8/8/8/8/PPPPPPPP/P7/4K3 w - - 0 1",
    ];
    for fen in bad {
        assert!(parse(fen).is_none(), "should be rejected: {fen}");
    }
}

#[test]
fn accepts_normal_positions() {
    let good = [
        chess_rust_engine::board::START_FEN,
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        "4k3/8/8/8/8/8/8/4K3 b - - 0 1",
    ];
    for fen in good {
        let p = parse(fen).unwrap_or_else(|| panic!("should parse: {fen}"));
        assert_eq!(p.to_fen().split_whitespace().next(), fen.split_whitespace().next());
    }
}

#[test]
fn repairs_stale_castling_and_bogus_ep() {
    // Castling rights claimed but rooks/kings are not at home -> dropped.
    let p = parse("4k3/8/8/8/8/8/8/4K3 w KQkq - 0 1").unwrap();
    assert_eq!(p.to_fen().split_whitespace().nth(2), Some("-"));
    // En-passant square with no pawn behind it -> dropped.
    let p = parse("4k3/8/8/8/8/8/8/4K3 w - e6 0 1").unwrap();
    assert_eq!(p.to_fen().split_whitespace().nth(3), Some("-"));
    // A real en-passant square is kept.
    let p = parse("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1").unwrap();
    assert_eq!(p.to_fen().split_whitespace().nth(3), Some("d6"));
}
