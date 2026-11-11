//! `datagen-bin`: multi-threaded self-play data generator that writes the trainer's 28-byte
//! binary records directly (no text -> binary conversion step) plus a per-record **game id**
//! sidecar, so train/validation can be split *by game* (position-hash splits leak neighbouring
//! positions of one game across the split, see Chess-rust-engine#1 EXP-I2).
//!
//! Differences from the legacy single-threaded `datagen` (which is left untouched, its output
//! stays bit-identical):
//!  * N worker threads, one TT each, one `ThreadData` per *game* instead of per *move*
//!    (the legacy path allocates ~1.3 MB of history tables for every single search).
//!  * Real game history is passed to the search (`hash_hist`), so repetitions are seen. The legacy
//!    path searches every move with an empty history.
//!  * Game-end detection: mate, stalemate, 50-move, insufficient material, 3-fold repetition.
//!  * Score adjudication (win: both sides' searches agree on >= 1000 cp for 4 plies; draw: |cp| <= 8
//!    for 10 plies after ply 60). `CRE_DATAGEN_ADJ=0` disables it.
//!  * Games that hit the ply cap without a result are **discarded**, not labelled as draws.
//!  * Opening balance filter: a game whose first search is outside +-`CRE_DATAGEN_BAL` cp is dropped.
//!  * Provenance sidecar `<out>.meta.json`.
//!
//! Record (identical to `tools/nnue/train.py`, little endian, 28 bytes):
//!   `occ u64 | 16 bytes = 32 piece nibbles in ascending-square order (piece = color*6+type) |
//!    stm u8 (0 white, 1 black) | score i16 (side-to-move POV, cp) | wdl u8 (side-to-move POV: 0 loss, 1 draw, 2 win)`
//! Sidecar `<out>.gid`: `u32` little endian per record, the game id (unique per game, same for all of its records).
//!
//! Environment: `CRE_DATAGEN_SEED`, `CRE_DATAGEN_ADJ` (default 1), `CRE_DATAGEN_BAL` (default 450),
//! `CRE_DATAGEN_RANDOM_PCT` (default 3), `CRE_DATAGEN_NODES` (optional hard node cap per search),
//! `CRE_DATAGEN_BOOK` (EPD, default `tools/openings_book.epd` when present).

use crate::board::Position;
use crate::datagen::load_openings;
use crate::movegen::legal_moves;
use crate::search::{iterative_deepening, ThreadData};
use crate::time::{Limits, TimeManager};
use crate::tt::TranspositionTable;
use crate::types::{is_mate_score, Color, Move, MAX_MOVES};
use std::fs::File;
use std::io::{BufWriter, Write};
use std::sync::atomic::{AtomicU32, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

pub const REC_LEN: usize = 28;

const MAX_GAME_PLY: usize = 400;
const WIN_CP: i32 = 1000;
const WIN_PLIES: usize = 4;
const DRAW_CP: i32 = 8;
const DRAW_PLIES: usize = 10;
const DRAW_MIN_PLY: usize = 60;
const MAX_SAMPLE_CP: i32 = 2500;

/// Pack a position into the 28-byte trainer record. `score` is side-to-move POV, `wdl` 0/1/2.
pub fn pack_record(pos: &Position, score: i32, wdl: u8) -> [u8; REC_LEN] {
    let mut rec = [0u8; REC_LEN];
    let mut occ = 0u64;
    let mut nib = [0u8; 32];
    let mut n = 0usize;
    for sq in 0..64 {
        let p = pos.mailbox[sq];
        if !p.is_none() {
            occ |= 1u64 << sq;
            nib[n] = p.0;
            n += 1;
        }
    }
    rec[0..8].copy_from_slice(&occ.to_le_bytes());
    for i in 0..16 {
        rec[8 + i] = nib[2 * i] | (nib[2 * i + 1] << 4);
    }
    rec[24] = if pos.side == Color::White { 0 } else { 1 };
    rec[25..27].copy_from_slice(&(score.clamp(-32000, 32000) as i16).to_le_bytes());
    rec[27] = wdl;
    rec
}

/// Inverse of [`pack_record`]: (position without castling/ep info, score, wdl).
pub fn unpack_record(rec: &[u8; REC_LEN]) -> Option<(Position, i32, u8)> {
    let occ = u64::from_le_bytes(rec[0..8].try_into().ok()?);
    let mut nib = [0u8; 32];
    for i in 0..16 {
        nib[2 * i] = rec[8 + i] & 15;
        nib[2 * i + 1] = rec[8 + i] >> 4;
    }
    let letters = b"PNBRQKpnbrqk";
    // Nibbles are stored in ascending-square order (a1 = 0); map them back onto squares first.
    let mut on_sq = [255u8; 64];
    let mut k = 0usize;
    for sq in 0..64 {
        if occ >> sq & 1 == 1 {
            let n = *nib.get(k)?;
            if n >= 12 {
                return None;
            }
            on_sq[sq] = n;
            k += 1;
        }
    }
    let mut fen = String::new();
    for rank in (0..8).rev() {
        let mut empty = 0;
        for file in 0..8 {
            let n = on_sq[rank * 8 + file];
            if n == 255 {
                empty += 1;
            } else {
                if empty > 0 {
                    fen.push_str(&empty.to_string());
                    empty = 0;
                }
                fen.push(letters[n as usize] as char);
            }
        }
        if empty > 0 {
            fen.push_str(&empty.to_string());
        }
        if rank > 0 {
            fen.push('/');
        }
    }
    fen.push_str(if rec[24] == 0 { " w - - 0 1" } else { " b - - 0 1" });
    let pos = Position::from_fen(&fen)?;
    let score = i16::from_le_bytes([rec[25], rec[26]]) as i32;
    Some((pos, score, rec[27]))
}

struct Rng(u64);
impl Rng {
    fn new(seed: u64) -> Rng {
        Rng(seed.max(1))
    }
    fn next(&mut self) -> u64 {
        // splitmix64
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
    fn below(&mut self, n: u32) -> u32 {
        (self.next() % n.max(1) as u64) as u32
    }
}

struct Out {
    rec: BufWriter<File>,
    gid: BufWriter<File>,
    wdl_hist: [u64; 3],
}

struct Shared {
    target: usize,
    depth: i32,
    nodes: Option<u64>,
    adjudicate: bool,
    balance_cp: i32,
    random_pct: u32,
    openings: Vec<String>,
    written: AtomicUsize,
    next_gid: AtomicU32,
    games_played: AtomicU64,
    games_dropped_balance: AtomicU64,
    games_dropped_unfinished: AtomicU64,
    out: Mutex<Out>,
    start: Instant,
}

enum Outcome {
    /// result from White's point of view: 0 loss, 1 draw, 2 win
    Done(u8),
    Dropped,
    Unfinished,
}

fn env_i32(name: &str, default: i32) -> i32 {
    std::env::var(name).ok().and_then(|v| v.trim().parse().ok()).unwrap_or(default)
}

fn play_game(sh: &Shared, rng: &mut Rng, tt: &Arc<TranspositionTable>) -> (Outcome, Vec<(Position, i32)>) {
    let fen = &sh.openings[rng.below(sh.openings.len() as u32) as usize];
    let mut pos = Position::from_fen(fen).unwrap_or_else(Position::startpos);
    let mut hist: Vec<u64> = Vec::with_capacity(512);
    let mut ply_total = 0usize;

    // Short random scramble from a real book line (2..=5 plies), then the balance filter below.
    let scramble = 2 + rng.below(4) as usize;
    for _ in 0..scramble {
        let mut moves = [Move::NONE; MAX_MOVES];
        let k = legal_moves(&pos, &mut moves);
        if k == 0 {
            break;
        }
        hist.push(pos.hash);
        pos.make(moves[rng.below(k as u32) as usize]);
        ply_total += 1;
    }

    tt.clear();
    let dummy = Arc::new(TimeManager::new(Limits::default(), true, 0));
    let mut td = ThreadData::new(tt.clone(), dummy);
    td.silent = true;

    let mut samples: Vec<(Position, i32)> = Vec::new();
    let mut white_pov: Vec<i32> = Vec::new();
    let mut first = true;

    loop {
        if ply_total >= MAX_GAME_PLY {
            return (Outcome::Unfinished, samples);
        }
        let mut moves = [Move::NONE; MAX_MOVES];
        let k = legal_moves(&pos, &mut moves);
        if k == 0 {
            let r = if pos.in_check() {
                if pos.side == Color::White { 0 } else { 2 }
            } else {
                1
            };
            return (Outcome::Done(r), samples);
        }
        if pos.halfmove >= 100 || pos.is_insufficient_material() {
            return (Outcome::Done(1), samples);
        }
        {
            let look = pos.halfmove as usize;
            let start = hist.len().saturating_sub(look);
            if hist[start..].iter().filter(|&&h| h == pos.hash).count() >= 2 {
                return (Outcome::Done(1), samples);
            }
        }

        let limits = Limits { depth: Some(sh.depth), nodes: sh.nodes, infinite: false, ..Default::default() };
        td.time = Arc::new(TimeManager::new(limits, pos.side == Color::White, 0));
        td.hash_hist.clear();
        td.hash_hist.extend_from_slice(&hist);
        let res = iterative_deepening(&pos, &mut td, false);
        if res.best.is_none() {
            return (Outcome::Unfinished, samples);
        }
        let s = res.score;

        if first {
            first = false;
            if s.abs() > sh.balance_cp {
                return (Outcome::Dropped, samples);
            }
        }

        // Decisive mate score: the side to move wins / loses.
        if is_mate_score(s) {
            let stm_wins = s > 0;
            let white_wins = (pos.side == Color::White) == stm_wins;
            return (Outcome::Done(if white_wins { 2 } else { 0 }), samples);
        }

        let noisy = res.best.is_capture() || res.best.is_promo();
        if !pos.in_check() && !noisy && s.abs() <= MAX_SAMPLE_CP && k > 1 {
            samples.push((pos, s));
        }

        let w = if pos.side == Color::White { s } else { -s };
        white_pov.push(w);
        if sh.adjudicate {
            let n = white_pov.len();
            if n >= WIN_PLIES {
                let t = &white_pov[n - WIN_PLIES..];
                if t.iter().all(|&x| x >= WIN_CP) {
                    return (Outcome::Done(2), samples);
                }
                if t.iter().all(|&x| x <= -WIN_CP) {
                    return (Outcome::Done(0), samples);
                }
            }
            if n >= DRAW_PLIES && ply_total >= DRAW_MIN_PLY && white_pov[n - DRAW_PLIES..].iter().all(|&x| x.abs() <= DRAW_CP) {
                return (Outcome::Done(1), samples);
            }
        }

        let mv = if rng.below(100) < sh.random_pct { moves[rng.below(k as u32) as usize] } else { res.best };
        hist.push(pos.hash);
        pos.make(mv);
        ply_total += 1;
    }
}

fn worker(sh: Arc<Shared>, idx: usize, seed: u64) {
    let mut rng = Rng::new(seed ^ ((idx as u64 + 1).wrapping_mul(0xD6E8_FEB8_6659_FD93)));
    let tt = Arc::new(TranspositionTable::new(16));
    let mut last_report = Instant::now();
    while sh.written.load(Ordering::Relaxed) < sh.target {
        let (outcome, samples) = play_game(&sh, &mut rng, &tt);
        match outcome {
            Outcome::Dropped => {
                sh.games_dropped_balance.fetch_add(1, Ordering::Relaxed);
            }
            Outcome::Unfinished => {
                sh.games_dropped_unfinished.fetch_add(1, Ordering::Relaxed);
            }
            Outcome::Done(white_result) => {
                sh.games_played.fetch_add(1, Ordering::Relaxed);
                if samples.is_empty() {
                    continue;
                }
                let gid = sh.next_gid.fetch_add(1, Ordering::Relaxed);
                let mut bytes = Vec::with_capacity(samples.len() * REC_LEN);
                let mut hist = [0u64; 3];
                for (p, s) in &samples {
                    let wdl = if p.side == Color::White { white_result } else { 2 - white_result };
                    hist[wdl as usize] += 1;
                    bytes.extend_from_slice(&pack_record(p, *s, wdl));
                }
                let gids: Vec<u8> = (0..samples.len()).flat_map(|_| gid.to_le_bytes()).collect();
                {
                    let mut o = sh.out.lock().unwrap();
                    o.rec.write_all(&bytes).expect("write rec");
                    o.gid.write_all(&gids).expect("write gid");
                    for i in 0..3 {
                        o.wdl_hist[i] += hist[i];
                    }
                }
                sh.written.fetch_add(samples.len(), Ordering::Relaxed);
            }
        }
        if idx == 0 && last_report.elapsed().as_secs() >= 15 {
            last_report = Instant::now();
            let w = sh.written.load(Ordering::Relaxed);
            eprintln!(
                "datagen-bin positions {} / {} games {} ({:.0} pos/s)",
                w,
                sh.target,
                sh.games_played.load(Ordering::Relaxed),
                w as f64 / sh.start.elapsed().as_secs_f64().max(0.001)
            );
        }
    }
}

pub fn run(n: usize, depth: i32, out_path: &str, threads: usize) {
    let threads = threads.max(1);
    let mut openings = load_openings();
    let book = std::env::var("CRE_DATAGEN_BOOK").unwrap_or_else(|_| "tools/openings_book.epd".into());
    if let Ok(text) = std::fs::read_to_string(&book) {
        for line in text.lines() {
            let parts: Vec<&str> = line.split(';').next().unwrap_or("").split_whitespace().collect();
            if parts.len() >= 4 {
                openings.push(format!("{} {} {} {} 0 1", parts[0], parts[1], parts[2], parts[3]));
            }
        }
    }
    let seed = std::env::var("CRE_DATAGEN_SEED")
        .ok()
        .and_then(|v| v.trim().parse::<u64>().ok())
        .map(|v| v.wrapping_add(1).wrapping_mul(0x9E37_79B9_7F4A_7C15) ^ 0xC0FF_EE12_3456_789A)
        .unwrap_or(0xC0FF_EE12_3456_789A);
    let adjudicate = env_i32("CRE_DATAGEN_ADJ", 1) != 0;
    let balance_cp = env_i32("CRE_DATAGEN_BAL", 450);
    let random_pct = env_i32("CRE_DATAGEN_RANDOM_PCT", 3).clamp(0, 100) as u32;
    let nodes = std::env::var("CRE_DATAGEN_NODES").ok().and_then(|v| v.trim().parse::<u64>().ok());

    let rec = BufWriter::with_capacity(1 << 20, File::create(out_path).expect("datagen-bin out"));
    let gid = BufWriter::with_capacity(1 << 18, File::create(format!("{out_path}.gid")).expect("gid out"));
    let sh = Arc::new(Shared {
        target: n,
        depth,
        nodes,
        adjudicate,
        balance_cp,
        random_pct,
        openings,
        written: AtomicUsize::new(0),
        next_gid: AtomicU32::new(0),
        games_played: AtomicU64::new(0),
        games_dropped_balance: AtomicU64::new(0),
        games_dropped_unfinished: AtomicU64::new(0),
        out: Mutex::new(Out { rec, gid, wdl_hist: [0; 3] }),
        start: Instant::now(),
    });

    let mut hs = Vec::new();
    for t in 0..threads {
        let s = sh.clone();
        hs.push(std::thread::Builder::new().stack_size(64 << 20).spawn(move || worker(s, t, seed)).expect("spawn"));
    }
    for h in hs {
        h.join().expect("worker panicked");
    }
    let o = &mut *sh.out.lock().unwrap();
    o.rec.flush().expect("flush");
    o.gid.flush().expect("flush");
    let secs = sh.start.elapsed().as_secs_f64();
    let written = sh.written.load(Ordering::Relaxed);
    let meta = format!(
        "{{\n  \"tool\": \"datagen-bin\",\n  \"engine_version\": \"{}\",\n  \"record_bytes\": {},\n  \"positions\": {},\n  \"games\": {},\n  \"games_dropped_unbalanced\": {},\n  \"games_dropped_unfinished\": {},\n  \"wdl_stm_loss_draw_win\": [{}, {}, {}],\n  \"depth\": {},\n  \"nodes_cap\": {},\n  \"threads\": {},\n  \"seed_env\": {},\n  \"adjudication\": {},\n  \"balance_cp\": {},\n  \"random_move_pct\": {},\n  \"nnue_active\": {},\n  \"book\": \"{}\",\n  \"openings\": {},\n  \"seconds\": {:.1},\n  \"positions_per_second\": {:.1}\n}}\n",
        env!("CARGO_PKG_VERSION"),
        REC_LEN,
        written,
        sh.games_played.load(Ordering::Relaxed),
        sh.games_dropped_balance.load(Ordering::Relaxed),
        sh.games_dropped_unfinished.load(Ordering::Relaxed),
        o.wdl_hist[0],
        o.wdl_hist[1],
        o.wdl_hist[2],
        depth,
        nodes.map(|v| v.to_string()).unwrap_or_else(|| "null".into()),
        threads,
        std::env::var("CRE_DATAGEN_SEED").ok().map(|v| format!("\"{v}\"")).unwrap_or_else(|| "null".into()),
        adjudicate,
        balance_cp,
        random_pct,
        crate::nnue::enabled() && crate::nnue::is_loaded(),
        book,
        sh.openings.len(),
        secs,
        written as f64 / secs.max(0.001),
    );
    let _ = std::fs::write(format!("{out_path}.meta.json"), meta);
    eprintln!("datagen-bin done {} positions in {:.1}s ({:.0}/s) -> {}", written, secs, written as f64 / secs.max(0.001), out_path);
}
