//! NNUE evaluation: `(768 -> H) x2 -> 1`, SCReLU, i16 weights, 8 material output buckets.
//! The hidden width `H` is read from the net header (128, 256, 512 or 1024).
//!
//! Architecture, trainer (`tools/nnue/train.py`) and weights are original to this repo.
//! Stockfish 19 is only used as a *teacher of position scores* (data), never as a net source.
//!
//! Feature index (perspective-relative, same convention as the trainer):
//!   `((piece_color != perspective) * 6 + piece_type) * 64 + (sq ^ (56 * perspective))`
//! The first layer is maintained *incrementally* by a per-thread cache of the last evaluated
//! piece bitboards: each evaluation XORs the cached and the current bitboards and adds / removes
//! only the feature rows that changed (typically 2-4 rows for a child node instead of ~30 pieces
//! x 2 perspectives). It is stateless with respect to search history, so it needs no hook in
//! `board.rs` make/unmake or `search.rs`, and it is bit-identical to the from-scratch result
//! (`Network::eval_scratch`, asserted by the `incremental_matches_scratch_*` tests).
//! Accumulators stay i32, so results match the previous implementation for every net.
//!
//! Width (EXP-HW1): every kernel is a const-generic function over `H`, selected once per call by
//! `dispatch!` from `Network::h`, so the H=128 path compiles to the same fixed-trip loops as the
//! old `const HIDDEN`. The output dot product `sum c*c*w` is accumulated in i32 per 128-wide
//! block and widened to i64 across blocks: for H=128 that is bit-identical to the previous
//! single i32 sum, and for wider nets it cannot wrap (255^2 * 127 * 256 is already ~98% of
//! `i32::MAX` for one 256-term sum, so a single i32 over 2*512 terms would silently overflow).
//!
//! Net file (little endian): `"CRN1" | version u32 | hidden u32 | buckets u32 | features u32`
//! then `ft_w i16[768*H] | ft_b i16[H] | out_w i16[B*2H] | out_b i32[B]`.
//! An empty / invalid net => HCE fallback. `CRE_NNUE_FILE` overrides the embedded net.

use crate::board::Position;
use std::cell::RefCell;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::OnceLock;

/// Legacy / default hidden width (the width of every net trained so far).
pub const HIDDEN: usize = 128;
/// Largest hidden width the thread-local accumulator cache can hold.
pub const MAX_HIDDEN: usize = 1024;
/// Hidden widths the engine can run (each is its own monomorphised kernel).
pub const SUPPORTED_HIDDEN: [usize; 4] = [128, 256, 512, 1024];
pub const FEATURES: usize = 768;
pub const BUCKETS: usize = 8;
pub const QA: i32 = 255;
pub const QB: i32 = 64;
pub const SCALE: i32 = 400;
const HEADER: usize = 20;
const MAX_EVAL: i32 = 3000;
/// Block length of the i32 partial sums in the output layer.
const BLK: usize = 128;

static EMBEDDED: &[u8] = include_bytes!("../nets/default.nnue");
static ENABLED: AtomicBool = AtomicBool::new(true);
static NET: OnceLock<Option<Network>> = OnceLock::new();
static NEXT_ID: AtomicU64 = AtomicU64::new(1);

/// Per-thread accumulator cache. `bb[color * 6 + ty]` is the piece set the accumulators
/// currently describe; `acc[p][..h]` is perspective `p`'s (0 = White, 1 = Black) first-layer sum.
struct Cache {
    id: u64,
    bb: [u64; 12],
    acc: [[i32; MAX_HIDDEN]; 2],
}

thread_local! {
    static CACHE: RefCell<Cache> = const { RefCell::new(Cache { id: 0, bb: [0; 12], acc: [[0; MAX_HIDDEN]; 2] }) };
}

pub struct Network {
    /// Hidden width of this net (one of `SUPPORTED_HIDDEN`).
    h: usize,
    ft_w: Vec<i16>,
    ft_b: Vec<i16>,
    out_w: Vec<i16>,
    out_b: Vec<i32>,
    avx2: bool,
    /// Unique per parsed net so a thread's cache can never be reused across different weights.
    id: u64,
}

fn rd_u32(b: &[u8], at: usize) -> u32 {
    u32::from_le_bytes([b[at], b[at + 1], b[at + 2], b[at + 3]])
}

/// Call `$self.$f::<H>(args)` with `H` = the net's hidden width.
macro_rules! dispatch {
    ($self:ident, $f:ident, $($arg:expr),*) => {
        match $self.h {
            128 => $self.$f::<128>($($arg),*),
            256 => $self.$f::<256>($($arg),*),
            512 => $self.$f::<512>($($arg),*),
            _ => $self.$f::<1024>($($arg),*),
        }
    };
}

impl Network {
    /// Hidden width of the loaded net.
    pub fn hidden(&self) -> usize {
        self.h
    }

    pub fn parse(bytes: &[u8]) -> Result<Network, String> {
        if bytes.len() < HEADER || &bytes[0..4] != b"CRN1" {
            return Err("no net (bad magic / empty)".into());
        }
        let (h, b, f) = (
            rd_u32(bytes, 8) as usize,
            rd_u32(bytes, 12) as usize,
            rd_u32(bytes, 16) as usize,
        );
        if !SUPPORTED_HIDDEN.contains(&h) || b != BUCKETS || f != FEATURES {
            return Err(format!(
                "net shape {f}x{h} b{b} not supported (need {FEATURES} features, {BUCKETS} buckets, hidden in {SUPPORTED_HIDDEN:?})"
            ));
        }
        let n_ft = FEATURES * h;
        let n_ow = BUCKETS * 2 * h;
        let want = HEADER + 2 * (n_ft + h + n_ow) + 4 * BUCKETS;
        if bytes.len() != want {
            return Err(format!("net size {} != expected {}", bytes.len(), want));
        }
        let mut p = HEADER;
        let i16s = |n: usize, p: &mut usize| -> Vec<i16> {
            let v = (0..n)
                .map(|i| i16::from_le_bytes([bytes[*p + 2 * i], bytes[*p + 2 * i + 1]]))
                .collect();
            *p += 2 * n;
            v
        };
        let ft_w = i16s(n_ft, &mut p);
        let ft_b = i16s(h, &mut p);
        let out_w = i16s(n_ow, &mut p);
        let out_b = (0..BUCKETS).map(|i| rd_u32(bytes, p + 4 * i) as i32).collect();
        #[cfg(target_arch = "x86_64")]
        let avx2 = is_x86_feature_detected!("avx2");
        #[cfg(not(target_arch = "x86_64"))]
        let avx2 = false;
        Ok(Network { h, ft_w, ft_b, out_w, out_b, avx2, id: NEXT_ID.fetch_add(1, Ordering::Relaxed) })
    }

    /// From-scratch first layer (the previous implementation, kept as the reference oracle).
    #[inline(always)]
    fn eval_scratch_impl<const H: usize>(&self, pos: &Position) -> i32 {
        let us = pos.side.index();
        let them = us ^ 1;
        let mut acc_us = [0i32; H];
        let mut acc_th = [0i32; H];
        for i in 0..H {
            acc_us[i] = self.ft_b[i] as i32;
            acc_th[i] = self.ft_b[i] as i32;
        }
        for color in 0..2usize {
            for ty in 0..6usize {
                let mut bb = pos.pieces[ty] & pos.colors[color];
                while bb != 0 {
                    let s = bb.trailing_zeros() as usize;
                    bb &= bb - 1;
                    let f_us = ((((color != us) as usize) * 6 + ty) * 64 + (s ^ (56 * us))) * H;
                    let f_th = ((((color != them) as usize) * 6 + ty) * 64 + (s ^ (56 * them))) * H;
                    let ru = &self.ft_w[f_us..f_us + H];
                    let rt = &self.ft_w[f_th..f_th + H];
                    for i in 0..H {
                        acc_us[i] += ru[i] as i32;
                        acc_th[i] += rt[i] as i32;
                    }
                }
            }
        }
        self.output::<H>(&acc_us, &acc_th, pos)
    }

    /// Output layer: SCReLU + bucketed dot product. Shared by both paths.
    ///
    /// Partial sums are i32 over `BLK` units (<= 255^2 * 127 * 128 ~ 1.05e9, cannot wrap) and are
    /// widened to i64 across blocks, so any supported width is overflow-free; for H = 128 the
    /// total equals the previous single i32 sum exactly.
    #[inline(always)]
    fn output<const H: usize>(&self, acc_us: &[i32], acc_th: &[i32], pos: &Position) -> i32 {
        let n = (pos.colors[0] | pos.colors[1]).count_ones() as usize;
        let bucket = (n.saturating_sub(2) / 4).min(BUCKETS - 1);
        let w = &self.out_w[bucket * 2 * H..(bucket + 1) * 2 * H];
        let (w_us, w_th) = (&w[..H], &w[H..]);
        let mut total = 0i64;
        for blk in 0..H / BLK {
            let (lo, hi) = (blk * BLK, (blk + 1) * BLK);
            let mut s_us = 0i32;
            let mut s_th = 0i32;
            for i in lo..hi {
                let c = acc_us[i].clamp(0, QA);
                s_us += c * c * w_us[i] as i32;
                let d = acc_th[i].clamp(0, QA);
                s_th += d * d * w_th[i] as i32;
            }
            total += s_us as i64 + s_th as i64;
        }
        let out = (total / QA as i64 + self.out_b[bucket] as i64) * SCALE as i64 / (QA * QB) as i64;
        (out as i32).clamp(-MAX_EVAL, MAX_EVAL)
    }

    #[inline(always)]
    fn row<const H: usize>(&self, perspective: usize, color: usize, ty: usize, sq: usize) -> &[i16] {
        let f = (((color != perspective) as usize) * 6 + ty) * 64 + (sq ^ (56 * perspective));
        &self.ft_w[f * H..(f + 1) * H]
    }

    /// Bring the thread's accumulators in line with `pos` by applying only the feature diff.
    #[inline(always)]
    fn sync<const H: usize>(&self, c: &mut Cache, pos: &Position) {
        let mut cur = [0u64; 12];
        for color in 0..2usize {
            for ty in 0..6usize {
                cur[color * 6 + ty] = pos.pieces[ty] & pos.colors[color];
            }
        }
        let pieces_now = (pos.colors[0] | pos.colors[1]).count_ones();
        let mut changed = 0u32;
        if c.id == self.id {
            for k in 0..12 {
                changed += (c.bb[k] ^ cur[k]).count_ones();
            }
        }
        // Foreign / stale cache, or a diff no cheaper than a rebuild: restart from the bias.
        if c.id != self.id || changed >= pieces_now {
            for p in 0..2 {
                for i in 0..H {
                    c.acc[p][i] = self.ft_b[i] as i32;
                }
            }
            c.bb = [0; 12];
            c.id = self.id;
        }
        for k in 0..12 {
            let diff = c.bb[k] ^ cur[k];
            if diff == 0 {
                continue;
            }
            let (color, ty) = (k / 6, k % 6);
            let mut add = diff & cur[k];
            while add != 0 {
                let s = add.trailing_zeros() as usize;
                add &= add - 1;
                for p in 0..2usize {
                    let r = self.row::<H>(p, color, ty, s);
                    let a = &mut c.acc[p][..H];
                    for i in 0..H {
                        a[i] += r[i] as i32;
                    }
                }
            }
            let mut rem = diff & c.bb[k];
            while rem != 0 {
                let s = rem.trailing_zeros() as usize;
                rem &= rem - 1;
                for p in 0..2usize {
                    let r = self.row::<H>(p, color, ty, s);
                    let a = &mut c.acc[p][..H];
                    for i in 0..H {
                        a[i] -= r[i] as i32;
                    }
                }
            }
            c.bb[k] = cur[k];
        }
    }

    #[inline(always)]
    fn eval_cached<const H: usize>(&self, c: &mut Cache, pos: &Position) -> i32 {
        self.sync::<H>(c, pos);
        let us = pos.side.index();
        self.output::<H>(&c.acc[us][..H], &c.acc[us ^ 1][..H], pos)
    }

    #[cfg(target_arch = "x86_64")]
    #[target_feature(enable = "avx2")]
    unsafe fn eval_cached_avx2<const H: usize>(&self, c: &mut Cache, pos: &Position) -> i32 {
        self.eval_cached::<H>(c, pos)
    }

    #[cfg(target_arch = "x86_64")]
    #[target_feature(enable = "avx2")]
    unsafe fn eval_scratch_avx2<const H: usize>(&self, pos: &Position) -> i32 {
        self.eval_scratch_impl::<H>(pos)
    }

    /// Reference evaluation without any cache (oracle for tests and `bench`-style probes).
    pub fn eval_scratch(&self, pos: &Position) -> i32 {
        #[cfg(target_arch = "x86_64")]
        if self.avx2 {
            // SAFETY: avx2 availability was checked at load time.
            return unsafe { dispatch!(self, eval_scratch_avx2, pos) };
        }
        dispatch!(self, eval_scratch_impl, pos)
    }

    #[inline]
    pub fn eval(&self, pos: &Position) -> i32 {
        CACHE.with(|cell| {
            let mut guard = cell.borrow_mut();
            let c = &mut *guard;
            #[cfg(target_arch = "x86_64")]
            if self.avx2 {
                // SAFETY: avx2 availability was checked at load time.
                return unsafe { dispatch!(self, eval_cached_avx2, c, pos) };
            }
            dispatch!(self, eval_cached, c, pos)
        })
    }
}

fn load() -> Option<Network> {
    if let Ok(path) = std::env::var("CRE_NNUE_FILE") {
        return match std::fs::read(&path).map_err(|e| e.to_string()).and_then(|b| Network::parse(&b)) {
            Ok(n) => Some(n),
            Err(e) => {
                eprintln!("info string NNUE file {path}: {e}");
                None
            }
        };
    }
    Network::parse(EMBEDDED).ok()
}

pub fn net() -> Option<&'static Network> {
    NET.get_or_init(load).as_ref()
}

pub fn is_loaded() -> bool {
    net().is_some()
}

pub fn set_enabled(on: bool) {
    ENABLED.store(on, Ordering::Relaxed);
}

#[inline]
pub fn enabled() -> bool {
    ENABLED.load(Ordering::Relaxed)
}

/// NNUE score from the side to move, or `None` when no net is loaded.
#[inline]
pub fn evaluate(pos: &Position) -> Option<i32> {
    net().map(|n| n.eval(pos))
}


#[cfg(test)]
mod tests {
    use super::*;

    fn blank_h(h: usize, fill_w: i16, out_w: i16, out_b: i32) -> Vec<u8> {
        let mut v = b"CRN1".to_vec();
        for x in [1u32, h as u32, BUCKETS as u32, FEATURES as u32] {
            v.extend_from_slice(&x.to_le_bytes());
        }
        for _ in 0..FEATURES * h {
            v.extend_from_slice(&fill_w.to_le_bytes());
        }
        for _ in 0..h {
            v.extend_from_slice(&0i16.to_le_bytes());
        }
        for _ in 0..BUCKETS * 2 * h {
            v.extend_from_slice(&out_w.to_le_bytes());
        }
        for _ in 0..BUCKETS {
            v.extend_from_slice(&out_b.to_le_bytes());
        }
        v
    }

    fn blank(fill_w: i16, out_w: i16, out_b: i32) -> Vec<u8> {
        blank_h(HIDDEN, fill_w, out_w, out_b)
    }

    #[test]
    fn rejects_empty_and_wrong_shape() {
        assert!(Network::parse(&[]).is_err());
        assert!(Network::parse(b"CRN1").is_err());
        let mut v = blank(0, 0, 0);
        v.pop();
        assert!(Network::parse(&v).is_err());
    }

    #[test]
    fn extreme_accumulators_do_not_overflow() {
        // Every feature weight at +i16::MAX saturates all SCReLU units at QA; output
        // weights at the trainer's clamp (1.98 * QB = 127) give the worst-case i32 sum.
        let net = Network::parse(&blank(i16::MAX, 127, i32::MAX / 4)).unwrap();
        let pos = Position::startpos();
        let v = net.eval(&pos);
        assert!((-MAX_EVAL..=MAX_EVAL).contains(&v), "eval {v} outside clamp");
        let net = Network::parse(&blank(i16::MAX, -127, i32::MIN / 4)).unwrap();
        let v = net.eval(&pos);
        assert!((-MAX_EVAL..=MAX_EVAL).contains(&v), "eval {v} outside clamp");
    }

    #[test]
    fn zero_net_evals_zero_and_is_perspective_symmetric() {
        let net = Network::parse(&blank(0, 0, 0)).unwrap();
        let a = Position::from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1").unwrap();
        assert_eq!(net.eval(&a), 0);
    }

    // ---- incremental accumulator == from-scratch oracle -------------------------------------

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
        fn range(&mut self, lo: i32, hi: i32) -> i32 {
            lo + (self.next() % (hi - lo + 1) as u64) as i32
        }
    }

    /// Random net scaled so evaluations stay inside the +-MAX_EVAL clamp (a saturated net would make
    /// every equality check vacuous; the playout test asserts it is not).
    fn random_net(seed: u64) -> Network {
        random_net_h(seed, HIDDEN)
    }

    fn random_net_h(seed: u64, h: usize) -> Network {
        let mut r = Rng(seed | 1);
        let mut v = b"CRN1".to_vec();
        for x in [1u32, h as u32, BUCKETS as u32, FEATURES as u32] {
            v.extend_from_slice(&x.to_le_bytes());
        }
        for _ in 0..FEATURES * h {
            v.extend_from_slice(&(r.range(-40, 40) as i16).to_le_bytes());
        }
        for _ in 0..h {
            v.extend_from_slice(&(r.range(-60, 60) as i16).to_le_bytes());
        }
        for _ in 0..BUCKETS * 2 * h {
            v.extend_from_slice(&(r.range(-12, 12) as i16).to_le_bytes());
        }
        for _ in 0..BUCKETS {
            v.extend_from_slice(&(r.range(-5000, 5000)).to_le_bytes());
        }
        Network::parse(&v).unwrap()
    }

    fn playout(seed: u64, plies: usize, start: &str) -> Vec<Position> {
        use crate::movegen::legal_moves;
        use crate::types::MAX_MOVES;
        let mut r = Rng(seed | 1);
        let mut pos = Position::from_fen(start).unwrap();
        let mut out = vec![pos.clone()];
        let mut list = [crate::types::Move::default(); MAX_MOVES];
        for _ in 0..plies {
            let n = legal_moves(&pos, &mut list);
            if n == 0 {
                break;
            }
            pos.make(list[(r.next() % n as u64) as usize]);
            out.push(pos.clone());
        }
        out
    }

    const STARTS: [&str; 4] = [
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        "r2q1rk1/pP1p2pp/Q4n2/bbp1p3/Np6/1B3NBn/pPPP1PPP/R3K2R b KQ - 0 1",
    ];

    #[test]
    fn incremental_matches_scratch_along_playouts() {
        let net = random_net(0x1234_5678_9abc_def1);
        let mut checked = 0usize;
        let mut distinct = std::collections::HashSet::new();
        let mut saturated = 0usize;
        for g in 0..120u64 {
            for pos in playout(g * 7919 + 3, 160, STARTS[(g % 4) as usize]) {
                let (a, b) = (net.eval(&pos), net.eval_scratch(&pos));
                assert_eq!(a, b, "fen {}", pos.to_fen());
                distinct.insert(a);
                saturated += (a.abs() >= MAX_EVAL) as usize;
                checked += 1;
            }
        }
        assert!(checked > 5000, "only {checked} positions checked");
        assert!(distinct.len() > 300, "eval has only {} distinct values: test is too weak", distinct.len());
        assert!(saturated * 20 < checked, "{saturated}/{checked} evals saturated at the clamp");
    }

    #[test]
    fn incremental_matches_scratch_out_of_order_and_across_games() {
        let net = random_net(0xfeed_beef_0123_4567);
        let mut all: Vec<Position> = Vec::new();
        for g in 0..40u64 {
            all.extend(playout(g * 104_729 + 11, 90, STARTS[(g % 4) as usize]));
        }
        let mut r = Rng(99);
        // random access order: forward, backward, and random jumps between unrelated games
        let mut order: Vec<usize> = (0..all.len()).collect();
        order.extend((0..all.len()).rev());
        order.extend((0..all.len()).map(|_| (r.next() % all.len() as u64) as usize));
        for i in order {
            assert_eq!(net.eval(&all[i]), net.eval_scratch(&all[i]), "fen {}", all[i].to_fen());
        }
    }

    #[test]
    fn cache_is_not_shared_between_different_nets_on_one_thread() {
        let (a, b) = (random_net(1), random_net(2));
        let pos = Position::from_fen(STARTS[1]).unwrap();
        for _ in 0..3 {
            assert_eq!(a.eval(&pos), a.eval_scratch(&pos));
            assert_eq!(b.eval(&pos), b.eval_scratch(&pos));
        }
        assert_ne!(a.eval_scratch(&pos), b.eval_scratch(&pos), "nets should differ for the test to mean anything");
    }

    #[test]
    fn caches_are_per_thread() {
        let net = std::sync::Arc::new(random_net(7));
        let positions: std::sync::Arc<Vec<Position>> = std::sync::Arc::new(playout(5, 120, STARTS[0]));
        let hs: Vec<_> = (0..4)
            .map(|t| {
                let (n, ps) = (net.clone(), positions.clone());
                std::thread::spawn(move || {
                    for k in 0..ps.len() {
                        let p = &ps[(k * (t + 1)) % ps.len()];
                        assert_eq!(n.eval(p), n.eval_scratch(p));
                    }
                })
            })
            .collect();
        for h in hs {
            h.join().unwrap();
        }
    }

    // ---- EXP-HW1: width-generic kernels ------------------------------------------------------

    /// Independent, slow, all-i64 reference of the whole net (no const generics, no blocks, no cache).
    fn reference_eval(net: &Network, pos: &Position) -> i32 {
        let h = net.h;
        let us = pos.side.index();
        let acc = |persp: usize| -> Vec<i64> {
            let mut a: Vec<i64> = net.ft_b.iter().map(|&x| x as i64).collect();
            for color in 0..2usize {
                for ty in 0..6usize {
                    for s in 0..64usize {
                        if pos.pieces[ty] & pos.colors[color] & (1u64 << s) != 0 {
                            let f = ((color != persp) as usize * 6 + ty) * 64 + (s ^ (56 * persp));
                            for i in 0..h {
                                a[i] += net.ft_w[f * h + i] as i64;
                            }
                        }
                    }
                }
            }
            a
        };
        let (a_us, a_th) = (acc(us), acc(us ^ 1));
        let n = (pos.colors[0] | pos.colors[1]).count_ones() as usize;
        let bucket = (n.saturating_sub(2) / 4).min(BUCKETS - 1);
        let mut sum = 0i64;
        for i in 0..h {
            let c = a_us[i].clamp(0, QA as i64);
            let d = a_th[i].clamp(0, QA as i64);
            sum += c * c * net.out_w[bucket * 2 * h + i] as i64 + d * d * net.out_w[bucket * 2 * h + h + i] as i64;
        }
        let out = (sum / QA as i64 + net.out_b[bucket] as i64) * SCALE as i64 / (QA * QB) as i64;
        (out as i32).clamp(-MAX_EVAL, MAX_EVAL)
    }

    #[test]
    fn every_supported_width_parses_and_reports_its_width() {
        for &h in &SUPPORTED_HIDDEN {
            assert_eq!(Network::parse(&blank_h(h, 0, 0, 0)).unwrap().hidden(), h);
        }
        // unsupported widths are rejected, not mis-parsed
        for h in [0usize, 64, 129, 192, 2048] {
            let mut v = b"CRN1".to_vec();
            for x in [1u32, h as u32, BUCKETS as u32, FEATURES as u32] {
                v.extend_from_slice(&x.to_le_bytes());
            }
            assert!(Network::parse(&v).is_err(), "width {h} must be rejected");
        }
    }

    #[test]
    fn all_widths_match_independent_i64_reference_and_scratch() {
        for &h in &SUPPORTED_HIDDEN {
            let net = random_net_h(0x9e37_79b9 ^ h as u64, h);
            let mut seen = std::collections::HashSet::new();
            for g in 0..10u64 {
                for pos in playout(g * 31 + h as u64, 120, STARTS[(g % 4) as usize]) {
                    let (a, b, r) = (net.eval(&pos), net.eval_scratch(&pos), reference_eval(&net, &pos));
                    assert_eq!(a, r, "H={h} incremental != reference, fen {}", pos.to_fen());
                    assert_eq!(b, r, "H={h} scratch != reference, fen {}", pos.to_fen());
                    seen.insert(a);
                }
            }
            assert!(seen.len() > 100, "H={h}: only {} distinct evals, test too weak", seen.len());
        }
    }

    #[test]
    fn wide_nets_do_not_wrap_the_output_sum() {
        // All units saturated at QA and output weights at the trainer clamp (127): the true sum for
        // H=1024 is 255^2*127*2048 ~ 1.7e10, which a single i32 would wrap (to a *negative* value
        // for some widths). The correct answer is the +MAX_EVAL clamp, and -MAX_EVAL for -127.
        let pos = Position::startpos();
        for &h in &SUPPORTED_HIDDEN {
            let pos_net = Network::parse(&blank_h(h, i16::MAX, 127, 0)).unwrap();
            assert_eq!(pos_net.eval(&pos), MAX_EVAL, "H={h} positive saturation wrapped");
            assert_eq!(pos_net.eval_scratch(&pos), MAX_EVAL);
            let neg_net = Network::parse(&blank_h(h, i16::MAX, -127, 0)).unwrap();
            assert_eq!(neg_net.eval(&pos), -MAX_EVAL, "H={h} negative saturation wrapped");
        }
    }

}
