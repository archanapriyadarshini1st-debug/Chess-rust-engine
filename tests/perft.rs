use chess_rust_engine::board::Position;
use chess_rust_engine::perft::{perft, SUITE};

#[test]
fn startpos_depth_4() {
    let pos = Position::startpos();
    assert_eq!(perft(&pos, 1), 20);
    assert_eq!(perft(&pos, 2), 400);
    assert_eq!(perft(&pos, 3), 8_902);
    assert_eq!(perft(&pos, 4), 197_281);
}

#[test]
fn cpw_suite() {
    for case in SUITE {
        let pos = Position::from_fen(case.fen).expect(case.fen);
        let n = perft(&pos, case.depth);
        assert_eq!(n, case.nodes, "fen={} depth={}", case.fen, case.depth);
    }
}

#[test]
fn fen_roundtrip_startpos() {
    let pos = Position::startpos();
    let fen = pos.to_fen();
    let pos2 = Position::from_fen(&fen).unwrap();
    assert_eq!(pos.hash, pos2.hash);
    assert_eq!(perft(&pos, 3), perft(&pos2, 3));
}

#[test]
fn kiwipete_depth_3() {
    let pos = Position::from_fen(
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    )
    .unwrap();
    assert_eq!(perft(&pos, 1), 48);
    assert_eq!(perft(&pos, 2), 2039);
    assert_eq!(perft(&pos, 3), 97_862);
}
