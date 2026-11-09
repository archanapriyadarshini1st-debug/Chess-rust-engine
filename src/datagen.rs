//! Self-play datagen for NNUE. Depth-limited search, never 100–120 ms teacher
//! games. Positions are quiet, |eval| < 1500, not in check.

use crate::board::Position;
use crate::movegen::legal_moves;
use crate::search::{iterative_deepening, ThreadData};
use crate::time::{Limits, TimeManager};
use crate::tt::TranspositionTable;
use crate::types::{Color, Move, MAX_MOVES};
use std::fs::File;
use std::io::{BufWriter, Write};
use std::sync::Arc;
use std::time::Instant;

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.0 = x;
        x
    }
    fn u32(&mut self, n: u32) -> u32 {
        (self.next() % n as u64) as u32
    }
}

fn load_openings() -> Vec<String> {
    let mut v = vec![
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1".into(),
    ];
    for path in ["tools/openings.epd", "openings.epd"] {
        if let Ok(text) = std::fs::read_to_string(path) {
            for line in text.lines() {
                let line = line.trim();
                if line.is_empty() {
                    continue;
                }
                let fen = line.split(';').next().unwrap_or(line).trim();
                // EPD is 4 fields; add stm clocks
                let parts: Vec<&str> = fen.split_whitespace().collect();
                if parts.len() >= 4 {
                    v.push(format!("{} {} {} {} 0 1", parts[0], parts[1], parts[2], parts[3]));
                }
            }
            break;
        }
    }
    v
}

pub fn run(n: usize, depth: i32, out_path: &str) {
    let openings = load_openings();
    let tt = Arc::new(TranspositionTable::new(16));
    let mut rng = Rng(0xC0FF_EE12_3456_789A);
    let file = File::create(out_path).expect("datagen out");
    let mut w = BufWriter::new(file);
    let start = Instant::now();
    let mut written = 0usize;
    let mut games = 0u32;

    while written < n {
        games += 1;
        let fen = &openings[rng.u32(openings.len() as u32) as usize];
        let mut pos = Position::from_fen(fen).unwrap_or_else(Position::startpos);
        // scramble a few random legal moves for diversity
        let scramble = 2 + rng.u32(10) as i32;
        for _ in 0..scramble {
            let mut moves = [Move::NONE; MAX_MOVES];
            let k = legal_moves(&pos, &mut moves);
            if k == 0 {
                break;
            }
            let mv = moves[rng.u32(k as u32) as usize];
            pos.make(mv);
            if pos.was_illegal() {
                break;
            }
        }
        let mut samples: Vec<(String, i32, Color)> = Vec::new();
        let mut result_white = 0.5f32;
        for _ply in 0..160 {
            if pos.halfmove >= 100 {
                result_white = 0.5;
                break;
            }
            let mut moves = [Move::NONE; MAX_MOVES];
            let k = legal_moves(&pos, &mut moves);
            if k == 0 {
                result_white = if pos.in_check() {
                    if pos.side == Color::White {
                        0.0
                    } else {
                        1.0
                    }
                } else {
                    0.5
                };
                break;
            }
            let limits = Limits {
                depth: Some(depth),
                infinite: false,
                ..Default::default()
            };
            let tm = Arc::new(TimeManager::new(limits, pos.side == Color::White, 0));
            let mut td = ThreadData::new(tt.clone(), tm);
            td.silent = true;
            let res = iterative_deepening(&pos, &mut td, false);
            if res.best.is_none() {
                break;
            }
            let in_check = pos.in_check();
            let noisy = res.best.is_capture() || res.best.is_promo();
            if !in_check && !noisy && res.score.abs() < 1500 && k > 1 {
                samples.push((pos.to_fen(), res.score, pos.side));
            }
            // 12% random to leave book / avoid loops
            let mv = if rng.u32(100) < 12 {
                moves[rng.u32(k as u32) as usize]
            } else {
                res.best
            };
            pos.make(mv);
            if pos.was_illegal() {
                break;
            }
            if res.score.abs() > 12_000 {
                result_white = if pos.side == Color::White { 0.0 } else { 1.0 };
                break;
            }
        }
        for (fen, cp, stm) in samples {
            if written >= n {
                break;
            }
            let wdl = if stm == Color::White {
                result_white
            } else {
                1.0 - result_white
            };
            let _ = writeln!(w, "{} | {} | {:.1}", fen, cp, wdl);
            written += 1;
        }
        tt.clear();
        if games % 25 == 0 {
            eprintln!(
                "datagen games {} positions {} ({:.1}/s)",
                games,
                written,
                written as f64 / start.elapsed().as_secs_f64().max(0.001)
            );
        }
    }
    let _ = w.flush();
    eprintln!(
        "datagen done {} positions in {:.1}s -> {}",
        written,
        start.elapsed().as_secs_f64(),
        out_path
    );
}

/// Dump HCE eval for FENs on stdin (one per line). Used to distill PeSTO.
pub fn dump_hce() {
    use std::io::{self, BufRead};
    let stdin = io::stdin();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        let fen = line.trim();
        if fen.is_empty() {
            continue;
        }
        if let Some(pos) = Position::from_fen(fen) {
            println!("{} | {}", fen, crate::eval::evaluate_hce(&pos));
        }
    }
}
