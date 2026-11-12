//! EXP-HX1 guards (Agent HX): the four default-off search toggles must
//! (a) default to 0, (b) never change the default search, (c) with each toggle on,
//! finish and return a legal best move on tactical / endgame positions.
//! Params are process-global atomics, so everything runs in ONE test fn.
use chess_rust_engine::board::Position;
use chess_rust_engine::movegen::legal_moves;
use chess_rust_engine::params;
use chess_rust_engine::search::{iterative_deepening, ThreadData};
use chess_rust_engine::time::{Limits, TimeManager};
use chess_rust_engine::tt::TranspositionTable;
use chess_rust_engine::types::{Color, Move, MAX_MOVES};
use std::sync::Arc;

const FENS: [&str; 6] = [
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "r2q1rk1/pP1p2pp/Q4n2/bbp1p3/Np6/1B3NBn/pPPP1PPP/R3K2R b KQ - 0 1",
    "2r3k1/1q1nbppp/r3p3/3pP3/pPpP4/P1Q2N2/2RN1PPP/2R4K b - b3 0 23",
    "8/5k2/8/8/8/8/1K6/1B6 w - - 0 1",
];

fn run(fen: &str, depth: i32) -> (Move, u64, bool) {
    let pos = Position::from_fen(fen).unwrap();
    let tt = Arc::new(TranspositionTable::new(8));
    let limits = Limits { depth: Some(depth), infinite: false, ..Default::default() };
    let tm = Arc::new(TimeManager::new(limits, pos.side == Color::White, 0));
    let mut td = ThreadData::new(tt, tm);
    td.silent = true;
    let r = iterative_deepening(&pos, &mut td, false);
    let mut l = [Move::NONE; MAX_MOVES];
    let n = legal_moves(&pos, &mut l);
    (r.best, td.nodes, (0..n).any(|i| l[i] == r.best))
}

#[test]
fn hx_toggles_default_off_and_stay_legal() {
    params::reset();
    for name in ["XThreatOrd", "XPawnHist", "XConthist4", "XDblExt"] {
        assert_eq!(params::get(name), Some(0), "{name} must default to 0");
    }
    // default search is deterministic and unchanged by merely compiling the toggles in
    let base: Vec<(Move, u64)> = FENS.iter().map(|f| { let (m, n, ok) = run(f, 7); assert!(ok); (m, n) }).collect();
    let again: Vec<(Move, u64)> = FENS.iter().map(|f| { let (m, n, _) = run(f, 7); (m, n) }).collect();
    assert_eq!(base, again, "default search must be deterministic");

    for name in ["XThreatOrd", "XPawnHist", "XConthist4", "XDblExt"] {
        params::reset();
        assert!(params::set(name, 1));
        for f in FENS {
            let (_m, nodes, ok) = run(f, 8);
            assert!(ok, "{name}: illegal best move on {f}");
            assert!(nodes > 0 && nodes < 50_000_000, "{name}: node explosion on {f}: {nodes}");
        }
    }
    params::reset();
    let after: Vec<(Move, u64)> = FENS.iter().map(|f| { let (m, n, _) = run(f, 7); (m, n) }).collect();
    assert_eq!(base, after, "resetting toggles must restore the exact default search");
}
