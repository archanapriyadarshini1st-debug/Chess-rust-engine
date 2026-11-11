//! Checkmate must beat the fifty-move rule (FIDE 5.2.1 / 9.3).
//! Before this fix `is_draw()` returned DRAW at halfmove >= 100 before looking
//! for mate, so a mate-in-1 delivered on the 100th half-move was scored 0.

use chess_rust_engine::board::Position;
use chess_rust_engine::search::{iterative_deepening, ThreadData};
use chess_rust_engine::time::{Limits, TimeManager};
use chess_rust_engine::tt::TranspositionTable;
use std::sync::Arc;

fn search(fen: &str, depth: i32) -> (String, i32) {
    let _ = chess_rust_engine::attacks::tables();
    let pos = Position::from_fen(fen).expect("fen");
    let tt = Arc::new(TranspositionTable::new(1));
    let limits = Limits { depth: Some(depth), ..Default::default() };
    let tm = Arc::new(TimeManager::new(limits, true, 0));
    let mut td = ThreadData::new(tt, tm);
    td.silent = true;
    let r = iterative_deepening(&pos, &mut td, false);
    (r.best.to_uci(), r.score)
}

#[test]
fn mate_on_the_hundredth_halfmove_is_still_mate() {
    // Qf7-g7# is the only mate. halfmove=99, so the mating move makes it 100.
    let (best, score) = search("7k/5Q2/6K1/8/8/8/8/8 w - - 99 100", 6);
    assert_eq!(best, "f7g7", "must play the mate, not a drawing move");
    assert!(score > 30_000, "expected a mate score, got {score}");
}

#[test]
fn control_same_position_halfmove_zero() {
    let (best, score) = search("7k/5Q2/6K1/8/8/8/8/8 w - - 0 100", 6);
    assert_eq!(best, "f7g7");
    assert!(score > 30_000, "expected a mate score, got {score}");
}

#[test]
fn fifty_move_rule_still_draws_when_not_mate() {
    // Winning KQ vs K, but already at halfmove 100 after a non-mating move:
    // searching from a position with halfmove=100 and no check must be a draw.
    let (_best, score) = search("7k/8/5K2/8/8/8/8/6Q1 b - - 100 120", 4);
    assert_eq!(score, 0, "halfmove>=100 and not mated is a draw, got {score}");
}

#[test]
fn check_with_an_escape_at_100_is_a_draw_not_a_mate() {
    // Every white move makes halfmove 100. Ra8+ gives check but Kg7 escapes,
    // so it is NOT mate: the fifty-move draw applies and no mate may be claimed.
    let (_best, score) = search("7k/8/8/8/8/8/6K1/R7 w - - 99 100", 5);
    assert_eq!(score, 0, "got {score}");
}
