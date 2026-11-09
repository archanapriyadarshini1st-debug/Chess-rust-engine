//! Perspective NNUE: `(768 → H)×2 → 1` with SCReLU and i16 weights.
//!
//! Feature set is 12×64 (piece-type × square) from the side-to-move’s view and
//! from the opponent’s view. Reckless / Viridithas / Stockfish all use this
//! family; the weights here are **ours**, trained on our data, never a SF net.
//!
//! Full accumulator refresh is cheap at H=64 (~30 pieces × 64 adds). Incremental
//! updates can land later once the net SPRTs.

use crate::board::Position;
use crate::types::{Color, Piece, Square};
use std::fs;
use std::sync::OnceLock;

pub const FEATURES: usize = 768;
pub const HIDDEN: usize = 64;
pub const QA: i32 = 255;
pub const QB: i32 = 64;
pub const SCALE: i32 = 400;

const MAGIC: &[u8; 4] = b"CRN1";

#[derive(Clone)]
pub struct Nnue {
    /// Row-major `[hidden][feature]`
    pub w1: Vec<i16>,
    pub b1: [i16; HIDDEN],
    pub w2: [i16; HIDDEN * 2],
    pub b2: i16,
}

static NET: OnceLock<Option<Nnue>> = OnceLock::new();

pub fn net() -> Option<&'static Nnue> {
    NET.get_or_init(load).as_ref()
}

fn load() -> Option<Nnue> {
    // HCE A/B: CRE_NO_NNUE=1  or  CRE_NNUE=/path/to/net.bin
    if std::env::var_os("CRE_NO_NNUE").is_some() {
        return None;
    }
    let mut paths: Vec<String> = Vec::new();
    if let Ok(p) = std::env::var("CRE_NNUE") {
        paths.push(p);
    }
    paths.extend([
        "nets/v1.bin".into(),
        "./v1.bin".into(),
        "v1.bin".into(),
        concat!(env!("CARGO_MANIFEST_DIR"), "/nets/v1.bin").into(),
    ]);
    for path in paths {
        if let Ok(bytes) = fs::read(&path) {
            if let Some(n) = parse(&bytes) {
                println!("info string nnue loaded {} ({} bytes)", path, bytes.len());
                return Some(n);
            }
        }
    }
    None
}

pub fn parse(bytes: &[u8]) -> Option<Nnue> {
    if bytes.len() < 4 + 4 {
        return None;
    }
    if &bytes[0..4] != MAGIC {
        return None;
    }
    let h = u32::from_le_bytes(bytes[4..8].try_into().ok()?) as usize;
    if h != HIDDEN {
        return None;
    }
    let need = 8 + HIDDEN * FEATURES * 2 + HIDDEN * 2 + HIDDEN * 2 * 2 + 2;
    if bytes.len() < need {
        return None;
    }
    let mut o = 8;
    let mut w1 = vec![0i16; HIDDEN * FEATURES];
    for w in w1.iter_mut() {
        *w = i16::from_le_bytes(bytes[o..o + 2].try_into().ok()?);
        o += 2;
    }
    let mut b1 = [0i16; HIDDEN];
    for b in b1.iter_mut() {
        *b = i16::from_le_bytes(bytes[o..o + 2].try_into().ok()?);
        o += 2;
    }
    let mut w2 = [0i16; HIDDEN * 2];
    for w in w2.iter_mut() {
        *w = i16::from_le_bytes(bytes[o..o + 2].try_into().ok()?);
        o += 2;
    }
    let b2 = i16::from_le_bytes(bytes[o..o + 2].try_into().ok()?);
    Some(Nnue { w1, b1, w2, b2 })
}

#[inline]
pub(crate) fn feature(stm: Color, piece: Piece, sq: Square) -> usize {
    let sq = if stm == Color::White {
        sq.index()
    } else {
        sq.index() ^ 56
    };
    let side = if piece.color() == stm { 0 } else { 6 };
    (side + piece.ty().index()) * 64 + sq
}

fn acc(pos: &Position, stm: Color, net: &Nnue) -> [i32; HIDDEN] {
    let mut a = [0i32; HIDDEN];
    for i in 0..HIDDEN {
        a[i] = net.b1[i] as i32;
    }
    for sq in 0..64u8 {
        let p = pos.piece_on(Square(sq));
        if p.is_none() {
            continue;
        }
        let f = feature(stm, p, Square(sq));
        // w1 is row-major [hidden][feature]
        for h in 0..HIDDEN {
            a[h] += net.w1[h * FEATURES + f] as i32;
        }
    }
    a
}

#[inline]
fn screlu(x: i32) -> i32 {
    let y = x.clamp(0, QA);
    y * y
}

/// Evaluation in centipawns from the side to move.
pub fn evaluate(pos: &Position) -> Option<i32> {
    let net = net()?;
    let stm = pos.side;
    let a_us = acc(pos, stm, net);
    let a_them = acc(pos, stm.flip(), net);
    let mut v = net.b2 as i64;
    for i in 0..HIDDEN {
        v += screlu(a_us[i]) as i64 * net.w2[i] as i64;
        v += screlu(a_them[i]) as i64 * net.w2[HIDDEN + i] as i64;
    }
    // v is in (QA^2 * QB) * (float output) units. SCALE maps 1.0 → 400 cp.
    // Must use i64: a queen-up position is ~8e6 raw * 400 which overflows i32.
    Some((v * SCALE as i64 / (QA as i64 * QA as i64 * QB as i64)) as i32)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{PieceType, Square};

    #[test]
    fn feature_white_pawn_a2() {
        let p = Piece::new(Color::White, PieceType::Pawn);
        assert_eq!(feature(Color::White, p, Square(8)), 8);
    }

    #[test]
    fn feature_black_pawn_a7_from_white() {
        let p = Piece::new(Color::Black, PieceType::Pawn);
        assert_eq!(feature(Color::White, p, Square(48)), 6 * 64 + 48);
    }

    #[test]
    fn feature_stm_black_flips_square() {
        // white pawn a2 seen by black: not-stm, sq ^= 56 → 48
        let p = Piece::new(Color::White, PieceType::Pawn);
        assert_eq!(feature(Color::Black, p, Square(8)), 6 * 64 + 48);
    }

    #[test]
    fn parse_rejects_short() {
        assert!(parse(b"CRN1").is_none());
        assert!(parse(b"XXXX").is_none());
    }

    #[test]
    fn kqk_features_and_eval() {
        use crate::board::Position;
        let pos = Position::from_fen("4k3/8/8/8/8/8/8/4K2Q w - - 0 1").unwrap();
        let mut fs = Vec::new();
        for sq in 0..64u8 {
            let p = pos.piece_on(Square(sq));
            if p.is_none() {
                continue;
            }
            fs.push((sq, p.ty().index(), p.color().index(), feature(pos.side, p, Square(sq))));
        }
        let mut feats: Vec<usize> = fs.iter().map(|x| x.3).collect();
        feats.sort();
        assert_eq!(feats, vec![263, 324, 764], "features {fs:?}");
        if let Ok(bytes) = std::fs::read("nets/hce-distill.bin") {
            let net = parse(&bytes).expect("net");
            let stm = pos.side;
            let a_us = acc(&pos, stm, &net);
            let a_them = acc(&pos, stm.flip(), &net);
            let mut them_f = Vec::new();
            for sq in 0..64u8 {
                let p = pos.piece_on(Square(sq));
                if p.is_none() {
                    continue;
                }
                them_f.push(feature(stm.flip(), p, Square(sq)));
            }
            them_f.sort();
            let mut v = net.b2 as i64;
            for i in 0..HIDDEN {
                v += screlu(a_us[i]) as i64 * net.w2[i] as i64;
                v += screlu(a_them[i]) as i64 * net.w2[HIDDEN + i] as i64;
            }
            let cp = (v * SCALE as i64 / (QA as i64 * QA as i64 * QB as i64)) as i32;
            assert_eq!(them_f, vec![324, 703, 764]);
            assert!(cp > 400, "KQK should be a queen ahead, got {cp}");
        }
    }
}
