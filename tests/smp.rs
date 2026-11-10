//! Lazy SMP correctness: multi-threaded search must terminate, return a legal
//! move, find forced mates, and `Threads=1` must stay bit-identical.

use chess_rust_engine::board::Position;
use chess_rust_engine::movegen::legal_moves;
use chess_rust_engine::search::{smp_search, ThreadData};
use chess_rust_engine::time::{Limits, TimeManager};
use chess_rust_engine::tt::TranspositionTable;
use chess_rust_engine::types::{is_mate_score, Color, Move, MAX_MOVES};
use std::sync::Arc;

fn run(fen: &str, depth: i32, threads: usize) -> (Move, i32, u64, Position) {
    let _ = chess_rust_engine::attacks::tables();
    let pos = Position::from_fen(fen).unwrap();
    let tt = Arc::new(TranspositionTable::new(16));
    let limits = Limits { depth: Some(depth), ..Default::default() };
    let tm = Arc::new(TimeManager::new(limits, pos.side == Color::White, 0));
    let mut td = ThreadData::new(tt, tm);
    td.silent = true;
    let r = smp_search(&pos, &mut td, threads, false);
    (r.best, r.score, r.nodes, pos)
}

fn is_legal(pos: &Position, mv: Move) -> bool {
    let mut l = [Move::NONE; MAX_MOVES];
    let n = legal_moves(pos, &mut l);
    (0..n).any(|i| l[i] == mv)
}

const POSITIONS: &[&str] = &[
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "r2q1rk1/pP1p2pp/Q4n2/bbp1p3/Np6/1B3NBn/pPPP1PPP/R3K2R b KQ - 0 1",
];

#[test]
fn smp_returns_legal_moves() {
    for fen in POSITIONS {
        for threads in [2, 4, 8] {
            let (best, _, nodes, pos) = run(fen, 9, threads);
            assert!(is_legal(&pos, best), "illegal {} with {} threads on {}", best, threads, fen);
            assert!(nodes > 0);
        }
    }
}

#[test]
fn smp_finds_mate_in_one() {
    // Back-rank mate: Rd8#.
    let (best, score, _, _) = run("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", 8, 4);
    assert_eq!(best.to_uci(), "d1d8");
    assert!(is_mate_score(score) && score > 0);
}

#[test]
fn single_thread_is_deterministic() {
    let fen = POSITIONS[1];
    let a = run(fen, 9, 1);
    let b = run(fen, 9, 1);
    assert_eq!((a.0, a.1, a.2), (b.0, b.1, b.2));
}
