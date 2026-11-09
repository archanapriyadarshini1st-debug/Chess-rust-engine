//! Tiny opening book + Stockfish-teacher book.
//!
//! Teacher lines come from `datasets/teacher_book.txt` (FEN + UCI move), written
//! by `scripts/stockfish_match.py --teacher` after games vs Stockfish 19 MAX
//! at a real time control (never 100–120 ms).

use crate::board::{parse_uci_move, Position};
use crate::types::Move;
use std::collections::HashMap;
use std::fs;
use std::sync::OnceLock;

static TEACHER: OnceLock<HashMap<u64, Move>> = OnceLock::new();

/// Built-in first-move / reply book. Only used when the teacher book misses.
fn opening_move(pos: &Position) -> Option<Move> {
    let fen = pos.to_fen();
    let fen_core = fen.split(" moves").next().unwrap_or(&fen);
    // key: first 4 FEN fields (placement, side, castle, ep)
    let parts: Vec<&str> = fen_core.split_whitespace().collect();
    if parts.len() < 2 {
        return None;
    }
    let key = format!("{} {}", parts[0], parts[1]);
    let uci = match key.as_str() {
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w" => "d2d4",
        "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b" => "d7d5",
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b" => "e7e5",
        "rnbqkbnr/ppp1pppp/8/3p4/3P4/8/PPP1PPPP/RNBQKBNR w" => "c2c4",
        "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w" => "g1f3",
        "rnbqkb1r/pppppppp/5n2/8/3P4/8/PPP1PPPP/RNBQKBNR w" => "c2c4",
        _ => return None,
    };
    parse_uci_move(pos, uci)
}

fn load_teacher() -> HashMap<u64, Move> {
    let mut map = HashMap::new();
    for path in ["datasets/teacher_book.txt", "teacher_book.txt"] {
        let Ok(text) = fs::read_to_string(path) else {
            continue;
        };
        for line in text.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            let Some((fen, mv)) = line.split_once('|') else {
                continue;
            };
            let fen = fen.trim();
            let mv = mv.trim();
            if let Some(pos) = Position::from_fen(fen) {
                if let Some(m) = parse_uci_move(&pos, mv) {
                    map.insert(pos.hash, m);
                }
            }
        }
    }
    map
}

/// Probe teacher book first (SF19 labels), then a few opening replies.
pub fn probe(pos: &Position) -> Option<Move> {
    let book = TEACHER.get_or_init(load_teacher);
    if let Some(&mv) = book.get(&pos.hash) {
        return Some(mv);
    }
    opening_move(pos)
}
