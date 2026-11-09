//! Perft — the move-generator test rig. Numbers from the Chess Programming Wiki.

use crate::board::Position;
use crate::movegen::pseudo_legal;
use crate::types::{Move, MAX_MOVES};

pub fn perft(pos: &Position, depth: u32) -> u64 {
    if depth == 0 {
        return 1;
    }
    let mut list = [Move::NONE; MAX_MOVES];
    let n = pseudo_legal(pos, &mut list);
    if depth == 1 {
        let mut count = 0u64;
        for i in 0..n {
            let mut np = *pos;
            np.make(list[i]);
            if !np.was_illegal() {
                count += 1;
            }
        }
        return count;
    }
    let mut nodes = 0u64;
    for i in 0..n {
        let mut np = *pos;
        np.make(list[i]);
        if np.was_illegal() {
            continue;
        }
        nodes += perft(&np, depth - 1);
    }
    nodes
}

pub fn divide(pos: &Position, depth: u32) -> u64 {
    let mut list = [Move::NONE; MAX_MOVES];
    let n = crate::movegen::legal_moves(pos, &mut list);
    let mut total = 0u64;
    for i in 0..n {
        let mut np = *pos;
        np.make(list[i]);
        let c = if depth <= 1 { 1 } else { perft(&np, depth - 1) };
        total += c;
        println!("{}: {}", list[i], c);
    }
    println!("total: {}", total);
    total
}

pub struct PerftCase {
    pub fen: &'static str,
    pub depth: u32,
    pub nodes: u64,
}

/// Standard CPW perft suite (startpos, Kiwipete, pos3–6).
pub const SUITE: &[PerftCase] = &[
    PerftCase {
        fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        depth: 5,
        nodes: 4_865_609,
    },
    PerftCase {
        fen: "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        depth: 4,
        nodes: 4_085_603,
    },
    PerftCase {
        fen: "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        depth: 5,
        nodes: 674_624,
    },
    PerftCase {
        fen: "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
        depth: 4,
        nodes: 422_333,
    },
    PerftCase {
        fen: "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
        depth: 4,
        nodes: 2_103_487,
    },
    PerftCase {
        fen: "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
        depth: 4,
        nodes: 3_894_594,
    },
];
