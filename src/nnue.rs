//! NNUE evaluation: `(768 -> H) x2 -> 1`, SCReLU, i16 weights, 8 material output buckets.
//!
//! Architecture, trainer (`tools/nnue/train.py`) and weights are original to this repo.
//! Stockfish 19 is only used as a *teacher of position scores* (data), never as a net source.
//!
//! Feature index (perspective-relative, same convention as the trainer):
//!   `((piece_color != perspective) * 6 + piece_type) * 64 + (sq ^ (56 * perspective))`
//! The first layer is recomputed from scratch per evaluation (cheap for H=128 with AVX2);
//! incremental accumulators are a later optimisation and need no change to the net format.
//!
//! Net file (little endian): `"CRN1" | version u32 | hidden u32 | buckets u32 | features u32`
//! then `ft_w i16[768*H] | ft_b i16[H] | out_w i16[B*2H] | out_b i32[B]`.
//! An empty / invalid net => HCE fallback. `CRE_NNUE_FILE` overrides the embedded net.
//!
//! ## CRN2: king-bucketed, file-mirrored inputs (EXP-KB1)
//! Magic `CRN2`, same header, `features = 768 * KB_BUCKETS`. Per perspective the feature row is
//! `bucket * 768 + <CRN1 index with the square xor-ed by the mirror mask>`, where the bucket and mask
//! come from that perspective's own king: `ksq = king_sq ^ (56 * persp)`; if `file(ksq) >= 4` every
//! square of that perspective is mirrored (`^ 7`) and so is the king; `bucket = KB_TABLE[rank*4 + file]`
//! on the mirrored king. CRN1 nets keep bucket 0 / mask 0, i.e. bit-identical legacy indexing.
//! Left-right mirrored positions therefore evaluate identically (tested). Reference material: the
//! public descriptions of king-bucketed NNUE inputs in Stockfish / Viridithas / Reckless docs; no
//! third-party code is used.

use crate::board::Position;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;

pub const HIDDEN: usize = 128;
pub const FEATURES: usize = 768;
pub const BUCKETS: usize = 8;
/// Number of king buckets in a CRN2 net (rows of the feature table = `FEATURES * KB_BUCKETS`).
pub const KB_BUCKETS: usize = 8;
/// Indexed by `rank * 4 + mirrored_file` of the perspective-relative king (a1 = rank 0, file 0..3).
/// Must stay identical to `KB_TABLE` in `tools/nnue/train.py` and `tools/nnue/parity_check.py`.
pub const KB_TABLE: [u8; 32] = [
    0, 0, 1, 1, // rank 1
    2, 2, 3, 3, // rank 2
    4, 4, 5, 5, // rank 3
    4, 4, 5, 5, // rank 4
    6, 6, 6, 6, // rank 5
    6, 6, 6, 6, // rank 6
    7, 7, 7, 7, // rank 7
    7, 7, 7, 7, // rank 8
];
pub const QA: i32 = 255;
pub const QB: i32 = 64;
pub const SCALE: i32 = 400;
const HEADER: usize = 20;
const MAX_EVAL: i32 = 3000;

static EMBEDDED: &[u8] = include_bytes!("../nets/default.nnue");
static ENABLED: AtomicBool = AtomicBool::new(true);
static NET: OnceLock<Option<Network>> = OnceLock::new();

pub struct Network {
    ft_w: Vec<i16>,
    ft_b: Vec<i16>,
    out_w: Vec<i16>,
    out_b: Vec<i32>,
    avx2: bool,
    /// true for CRN2 (king-bucketed + mirrored inputs).
    kb: bool,
}

fn rd_u32(b: &[u8], at: usize) -> u32 {
    u32::from_le_bytes([b[at], b[at + 1], b[at + 2], b[at + 3]])
}

impl Network {
    pub fn parse(bytes: &[u8]) -> Result<Network, String> {
        if bytes.len() < HEADER || (&bytes[0..4] != b"CRN1" && &bytes[0..4] != b"CRN2") {
            return Err("no net (bad magic / empty)".into());
        }
        let kb = &bytes[0..4] == b"CRN2";
        let (h, b, f) = (
            rd_u32(bytes, 8) as usize,
            rd_u32(bytes, 12) as usize,
            rd_u32(bytes, 16) as usize,
        );
        let want_f = if kb { FEATURES * KB_BUCKETS } else { FEATURES };
        if h != HIDDEN || b != BUCKETS || f != want_f {
            return Err(format!("net shape {f}x{h} b{b} != built-in {want_f}x{HIDDEN} b{BUCKETS}"));
        }
        let n_ft = want_f * HIDDEN;
        let n_ow = BUCKETS * 2 * HIDDEN;
        let want = HEADER + 2 * (n_ft + HIDDEN + n_ow) + 4 * BUCKETS;
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
        let ft_b = i16s(HIDDEN, &mut p);
        let out_w = i16s(n_ow, &mut p);
        let out_b = (0..BUCKETS).map(|i| rd_u32(bytes, p + 4 * i) as i32).collect();
        #[cfg(target_arch = "x86_64")]
        let avx2 = is_x86_feature_detected!("avx2");
        #[cfg(not(target_arch = "x86_64"))]
        let avx2 = false;
        Ok(Network { ft_w, ft_b, out_w, out_b, avx2, kb })
    }

    /// (feature-row offset, square xor mask) of one perspective. `(0, 0)` for CRN1 nets.
    #[inline(always)]
    fn king_ctx(&self, pos: &Position, persp: usize) -> (usize, usize) {
        if !self.kb {
            return (0, 0);
        }
        let kbb = pos.pieces[5] & pos.colors[persp];
        let ksq = (if kbb == 0 { 0 } else { kbb.trailing_zeros() as usize }) ^ (56 * persp);
        let mask = if ksq & 7 >= 4 { 7 } else { 0 };
        let f = (ksq & 7) ^ mask;
        (KB_TABLE[(ksq >> 3) * 4 + f] as usize * FEATURES, mask)
    }

    #[inline(always)]
    fn eval_impl(&self, pos: &Position) -> i32 {
        let us = pos.side.index();
        let them = us ^ 1;
        let mut acc_us = [0i32; HIDDEN];
        let mut acc_th = [0i32; HIDDEN];
        for i in 0..HIDDEN {
            acc_us[i] = self.ft_b[i] as i32;
            acc_th[i] = self.ft_b[i] as i32;
        }
        let (off_us, mask_us) = self.king_ctx(pos, us);
        let (off_th, mask_th) = self.king_ctx(pos, them);
        for color in 0..2usize {
            for ty in 0..6usize {
                let mut bb = pos.pieces[ty] & pos.colors[color];
                while bb != 0 {
                    let s = bb.trailing_zeros() as usize;
                    bb &= bb - 1;
                    let f_us = (off_us + ((color != us) as usize * 6 + ty) * 64 + ((s ^ (56 * us)) ^ mask_us)) * HIDDEN;
                    let f_th = (off_th + ((color != them) as usize * 6 + ty) * 64 + ((s ^ (56 * them)) ^ mask_th)) * HIDDEN;
                    let ru = &self.ft_w[f_us..f_us + HIDDEN];
                    let rt = &self.ft_w[f_th..f_th + HIDDEN];
                    for i in 0..HIDDEN {
                        acc_us[i] += ru[i] as i32;
                        acc_th[i] += rt[i] as i32;
                    }
                }
            }
        }
        let n = (pos.colors[0] | pos.colors[1]).count_ones() as usize;
        let bucket = (n.saturating_sub(2) / 4).min(BUCKETS - 1);
        let w = &self.out_w[bucket * 2 * HIDDEN..(bucket + 1) * 2 * HIDDEN];
        let mut sum = 0i32;
        for i in 0..HIDDEN {
            let c = acc_us[i].clamp(0, QA);
            sum += c * c * w[i] as i32;
            let d = acc_th[i].clamp(0, QA);
            sum += d * d * w[HIDDEN + i] as i32;
        }
        let out = (sum / QA + self.out_b[bucket]) as i64 * SCALE as i64 / (QA * QB) as i64;
        (out as i32).clamp(-MAX_EVAL, MAX_EVAL)
    }

    #[cfg(target_arch = "x86_64")]
    #[target_feature(enable = "avx2")]
    unsafe fn eval_avx2(&self, pos: &Position) -> i32 {
        self.eval_impl(pos)
    }

    #[inline]
    pub fn eval(&self, pos: &Position) -> i32 {
        #[cfg(target_arch = "x86_64")]
        if self.avx2 {
            // SAFETY: avx2 availability was checked at load time.
            return unsafe { self.eval_avx2(pos) };
        }
        self.eval_impl(pos)
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

    fn blank(fill_w: i16, out_w: i16, out_b: i32) -> Vec<u8> {
        let mut v = b"CRN1".to_vec();
        for x in [1u32, HIDDEN as u32, BUCKETS as u32, FEATURES as u32] {
            v.extend_from_slice(&x.to_le_bytes());
        }
        for _ in 0..FEATURES * HIDDEN {
            v.extend_from_slice(&fill_w.to_le_bytes());
        }
        for _ in 0..HIDDEN {
            v.extend_from_slice(&0i16.to_le_bytes());
        }
        for _ in 0..BUCKETS * 2 * HIDDEN {
            v.extend_from_slice(&out_w.to_le_bytes());
        }
        for _ in 0..BUCKETS {
            v.extend_from_slice(&out_b.to_le_bytes());
        }
        v
    }

    /// Deterministic pseudo-random CRN1/CRN2 net (LCG), moderate weights so SCReLU is not saturated.
    fn random_net(magic: &[u8; 4], seed: u64) -> Vec<u8> {
        let rows = if magic == b"CRN2" { FEATURES * KB_BUCKETS } else { FEATURES };
        let mut st = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        let mut next = move |range: i64| -> i64 {
            st = st.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            ((st >> 33) as i64 % (2 * range + 1)) - range
        };
        let mut v = magic.to_vec();
        for x in [1u32, HIDDEN as u32, BUCKETS as u32, rows as u32] {
            v.extend_from_slice(&x.to_le_bytes());
        }
        for _ in 0..rows * HIDDEN {
            v.extend_from_slice(&(next(40) as i16).to_le_bytes());
        }
        for _ in 0..HIDDEN {
            v.extend_from_slice(&(next(60) as i16).to_le_bytes());
        }
        for _ in 0..BUCKETS * 2 * HIDDEN {
            v.extend_from_slice(&(next(30) as i16).to_le_bytes());
        }
        for _ in 0..BUCKETS {
            v.extend_from_slice(&(next(2000) as i32).to_le_bytes());
        }
        v
    }

    fn mirror_fen(fen: &str) -> String {
        let mut it = fen.split(' ');
        let board: Vec<String> = it.next().unwrap().split('/').map(|r| r.chars().rev().collect()).collect();
        let rest: Vec<&str> = it.collect();
        // castling / ep fields do not enter the net; keep them unchanged (the eval ignores them).
        format!("{} {}", board.join("/"), rest.join(" "))
    }

    const FENS: &[&str] = &[
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 2 2",
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w - - 0 1",
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1",
        "6k1/5ppp/8/8/8/8/5PPP/3R2K1 b - - 0 1",
        "2r3k1/1b3pp1/p3p2p/1p2P3/3P4/1B3N2/P4PPP/4R1K1 w - - 0 1",
    ];

    #[test]
    fn crn2_constant_net_equals_crn1_constant_net() {
        // With identical rows everywhere the king bucket cannot matter.
        let a = Network::parse(&blank(7, 3, 11)).unwrap();
        let mut b2 = blank(7, 3, 11);
        b2[0..4].copy_from_slice(b"CRN2");
        // widen the feature table to KB_BUCKETS copies of the same constant rows
        let head = 20;
        let ft_bytes = FEATURES * HIDDEN * 2;
        let rest = b2[head + ft_bytes..].to_vec();
        let mut wide = b2[..head].to_vec();
        wide[16..20].copy_from_slice(&((FEATURES * KB_BUCKETS) as u32).to_le_bytes());
        for _ in 0..KB_BUCKETS {
            wide.extend_from_slice(&b2[head..head + ft_bytes]);
        }
        wide.extend_from_slice(&rest);
        let b = Network::parse(&wide).unwrap();
        for f in FENS {
            let pos = Position::from_fen(f).unwrap();
            assert_eq!(a.eval(&pos), b.eval(&pos), "{f}");
        }
    }

    #[test]
    fn crn2_is_left_right_mirror_invariant() {
        let net = Network::parse(&random_net(b"CRN2", 7)).unwrap();
        for f in FENS {
            let a = Position::from_fen(f).unwrap();
            let m = Position::from_fen(&mirror_fen(f)).unwrap();
            assert_eq!(net.eval(&a), net.eval(&m), "mirror changed eval: {f}");
        }
    }

    #[test]
    fn crn2_actually_uses_king_buckets() {
        // Table sanity (every entry is a valid bucket) plus: moving the white king into another
        // bucket changes a random CRN2 net's output.
        let net = Network::parse(&random_net(b"CRN2", 3)).unwrap();
        let a = Position::from_fen("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1").unwrap();
        let c = Position::from_fen("4k3/8/8/8/8/8/4P3/K7 w - - 0 1").unwrap();
        assert_ne!(net.eval(&a), net.eval(&c));
        for f in 0..32 {
            assert!((KB_TABLE[f] as usize) < KB_BUCKETS);
        }
    }

    #[test]
    fn crn1_indexing_unchanged() {
        // CRN1 must keep (offset 0, mask 0): a CRN1 net is NOT mirror invariant in general.
        let net = Network::parse(&random_net(b"CRN1", 5)).unwrap();
        assert!(!net.kb);
        let a = Position::from_fen("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 2 2").unwrap();
        let m = Position::from_fen(&mirror_fen("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 2 2")).unwrap();
        assert_ne!(net.eval(&a), net.eval(&m));
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
}
