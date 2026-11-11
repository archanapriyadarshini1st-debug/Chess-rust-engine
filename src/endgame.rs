//! Endgame / draw knowledge applied on top of the raw evaluation (EXP-EG1).
//!
//! `evaluate()` used to return the raw HCE/NNUE score everywhere. That is wrong
//! in two well-known families of positions, both of which matter against a
//! stronger opponent (we grab a "winning" eval we cannot convert, or we refuse
//! a draw we should take):
//!
//! 1. **Material that cannot win.** A side with no pawns and no more than a
//!    minor piece of non-pawn material lead (KRKB, KRKN, KBBKN ...), two knights
//!    vs a bare king, opposite-coloured bishops, and K+B+rook-pawn with the
//!    wrong bishop. These are scaled towards zero. Winning material (KQK, KRK,
//!    KBBK, KBNK ...) is deliberately *not* touched.
//! 2. **Fifty-move rule.** A big score at halfmove 90 is not worth its face
//!    value; it is damped linearly so the engine prefers a capture / pawn move
//!    that resets the clock.
//!
//! The functions are pure and never increase `|v|` or flip its sign. They are
//! applied in `eval::evaluate()` only; the Texel tuner and the HCE teacher call
//! `evaluate_hce*` directly and are unaffected.
//!
//! Ideas are the standard public ones (Chess Programming Wiki "Draw Evaluation",
//! "Opposite-colored bishops", "Wrong bishop"); the code is independent.

use crate::board::Position;
use crate::types::{Color, PieceType};
use std::sync::atomic::{AtomicI32, Ordering};

/// Bit 0: fifty-move damping. Bit 1: material-based draw scaling.
pub const FIFTY: i32 = 1;
pub const MATERIAL: i32 = 2;
pub const DEFAULT_MASK: i32 = FIFTY | MATERIAL;

static MASK: AtomicI32 = AtomicI32::new(DEFAULT_MASK);

pub fn set_mask(m: i32) {
    MASK.store(m.clamp(0, 3), Ordering::Relaxed);
}

#[inline(always)]
pub fn mask() -> i32 {
    MASK.load(Ordering::Relaxed)
}

const LIGHT_SQUARES: u64 = 0x55AA_55AA_55AA_55AA;
const FILE_A: u64 = 0x0101_0101_0101_0101;
const FILE_H: u64 = FILE_A << 7;

const N_V: i32 = 320;
const B_V: i32 = 330;
const R_V: i32 = 500;
const Q_V: i32 = 950;

/// Scale `v` (side-to-move perspective) with the globally selected mask.
#[inline]
pub fn apply(pos: &Position, v: i32) -> i32 {
    scale(pos, v, mask())
}

/// Scale `v` with an explicit mask (used by tests / ablations).
#[inline]
pub fn scale(pos: &Position, v: i32, mask: i32) -> i32 {
    if mask == 0 || v == 0 {
        return v;
    }
    let mut v = v;
    if mask & MATERIAL != 0 {
        v = material_scale(pos, v);
    }
    if mask & FIFTY != 0 {
        let hm = (pos.halfmove as i32).min(100);
        v = v * (200 - hm) / 200;
    }
    v
}

#[inline(always)]
fn cnt(pos: &Position, c: Color, t: PieceType) -> i32 {
    pos.bb(c, t).count_ones() as i32
}

/// Draw-ish scaling from the material signature. Cheap early exit: positions
/// with more than 12 men are left alone.
fn material_scale(pos: &Position, v: i32) -> i32 {
    let occ = pos.occ();
    if occ.count_ones() > 12 {
        return v;
    }
    let strong = if v > 0 { pos.side } else { pos.side.flip() };
    let weak = strong.flip();

    let sp = cnt(pos, strong, PieceType::Pawn);
    let wp = cnt(pos, weak, PieceType::Pawn);
    let sn = cnt(pos, strong, PieceType::Knight);
    let sb = cnt(pos, strong, PieceType::Bishop);
    let sr = cnt(pos, strong, PieceType::Rook);
    let sq = cnt(pos, strong, PieceType::Queen);
    let wn = cnt(pos, weak, PieceType::Knight);
    let wb = cnt(pos, weak, PieceType::Bishop);
    let wr = cnt(pos, weak, PieceType::Rook);
    let wq = cnt(pos, weak, PieceType::Queen);

    let s_npm = sn * N_V + sb * B_V + sr * R_V + sq * Q_V;
    let w_npm = wn * N_V + wb * B_V + wr * R_V + wq * Q_V;

    if sp == 0 {
        // No pawns and less than ~a minor piece ahead: cannot force mate/promote.
        if s_npm - w_npm <= B_V {
            return v / 16;
        }
        // Two knights alone cannot force mate against a bare king.
        if sn == 2 && sb + sr + sq == 0 && w_npm == 0 && wp == 0 {
            return v / 16;
        }
        return v;
    }

    // Opposite-coloured bishops, nothing else but pawns.
    if sn + sr + sq + wn + wr + wq == 0 && sb == 1 && wb == 1 {
        let s_light = pos.bb(strong, PieceType::Bishop) & LIGHT_SQUARES != 0;
        let w_light = pos.bb(weak, PieceType::Bishop) & LIGHT_SQUARES != 0;
        if s_light != w_light {
            let s64 = (36 + 7 * sp).min(64);
            return v * s64 / 64;
        }
        return v;
    }

    // K + B + rook pawn(s) with the wrong-coloured bishop vs a bare king that
    // can reach the corner.
    if sb == 1 && sn + sr + sq == 0 && w_npm == 0 && wp == 0 {
        let spawns = pos.bb(strong, PieceType::Pawn);
        let on_a = spawns & !FILE_A == 0;
        let on_h = spawns & !FILE_H == 0;
        if on_a || on_h {
            let promo_file: u8 = if on_a { 0 } else { 7 };
            let promo_rank: u8 = if strong == Color::White { 7 } else { 0 };
            let promo_light = (promo_file + promo_rank) % 2 == 1;
            let bishop_light = pos.bb(strong, PieceType::Bishop) & LIGHT_SQUARES != 0;
            if promo_light != bishop_light {
                let wk = pos.king_sq(weak);
                let df = (wk.file() as i32 - promo_file as i32).abs();
                let dr = (wk.rank() as i32 - promo_rank as i32).abs();
                if df.max(dr) <= 1 {
                    return v / 16;
                }
            }
        }
    }
    v
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::movegen::legal_moves;
    use crate::types::{Move, MAX_MOVES};

    fn p(fen: &str) -> Position {
        Position::from_fen(fen).expect("fen")
    }

    const V: i32 = 400;

    fn m(fen: &str) -> i32 {
        scale(&p(fen), V, MATERIAL)
    }

    #[test]
    fn pawnless_non_winning_material_is_drawish() {
        assert!(m("8/8/4k3/8/3b4/8/3K4/3R4 w - - 0 1") <= V / 8); // KRKB
        assert!(m("8/8/4k3/8/3n4/8/3K4/3R4 w - - 0 1") <= V / 8); // KRKN
        assert!(m("8/8/4k3/8/8/8/3K4/3NN3 w - - 0 1") <= V / 8); // KNNK
    }

    #[test]
    fn real_wins_are_not_scaled() {
        assert_eq!(m("8/8/4k3/8/8/8/3K4/3Q4 w - - 0 1"), V); // KQK
        assert_eq!(m("8/8/4k3/8/8/8/3K4/3R4 w - - 0 1"), V); // KRK
        assert_eq!(m("8/8/4k3/8/8/8/3K4/2BB4 w - - 0 1"), V); // KBBK
        assert_eq!(m("8/8/4k3/8/8/8/3K4/2BN4 w - - 0 1"), V); // KBNK
        assert_eq!(m("8/8/4k3/8/8/8/P2K4/3R4 w - - 0 1"), V); // KRPK
        assert_eq!(m("8/8/4k3/8/8/8/3K4/2BQ4 w - - 0 1"), V); // KQBK
    }

    #[test]
    fn opposite_coloured_bishops_are_damped_same_coloured_are_not() {
        // White bishop c1 (dark), black bishop c8 (light): opposite.
        let ocb = m("2b5/8/4k3/8/8/4P3/3K4/2B5 w - - 0 1");
        assert!(ocb < V && ocb > V / 2, "{}", ocb);
        // Black bishop g7 (dark) vs white c1 (dark): same colour.
        let same = m("8/6b1/4k3/8/8/4P3/3K4/2B5 w - - 0 1");
        assert_eq!(same, V);
    }

    #[test]
    fn wrong_bishop_rook_pawn() {
        // h8 is a DARK square: the light-squared f1 bishop is the wrong one.
        assert!(m("6k1/8/8/8/8/8/3K3P/5B2 w - - 0 1") <= V / 8);
        // Dark-squared c1 bishop controls h8: it wins, not scaled.
        assert_eq!(m("6k1/8/8/8/8/8/3K3P/2B5 w - - 0 1"), V);
        // Wrong bishop but black king far from the corner: not scaled.
        assert_eq!(m("8/8/8/8/k7/8/3K3P/5B2 w - - 0 1"), V);
    }

    #[test]
    fn fifty_move_damping_is_linear_and_identity_at_zero() {
        let a = p("8/8/4k3/8/8/8/3K4/3R4 w - - 0 1");
        assert_eq!(scale(&a, 400, FIFTY), 400);
        let b = p("8/8/4k3/8/8/8/3K4/3R4 w - - 100 80");
        assert_eq!(scale(&b, 400, FIFTY), 200);
        let c = p("8/8/4k3/8/8/8/3K4/3R4 w - - 50 60");
        assert_eq!(scale(&c, 400, FIFTY), 300);
        assert_eq!(scale(&c, -400, FIFTY), -300);
    }

    fn mirror(pos: &Position) -> Position {
        let fen = pos.to_fen();
        let mut it = fen.split(' ');
        let board = it.next().unwrap();
        let stm = it.next().unwrap();
        let hm = it.nth(2).unwrap_or("0");
        let ranks: Vec<String> = board
            .split('/')
            .rev()
            .map(|r| {
                r.chars()
                    .map(|c| {
                        if c.is_ascii_uppercase() {
                            c.to_ascii_lowercase()
                        } else if c.is_ascii_lowercase() {
                            c.to_ascii_uppercase()
                        } else {
                            c
                        }
                    })
                    .collect()
            })
            .collect();
        let nstm = if stm == "w" { "b" } else { "w" };
        Position::from_fen(&format!("{} {} - - {} 1", ranks.join("/"), nstm, hm)).unwrap()
    }

    /// Random playouts: scaling never grows |v|, never flips sign, is
    /// colour-symmetric, and is exactly the identity above 12 men.
    #[test]
    fn invariants_on_random_playouts() {
        let mut seed: u64 = 0x9E37_79B9_7F4A_7C15;
        let mut rnd = || {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            seed
        };
        let mut checked = 0u32;
        let mut scaled_material = 0u32;
        for _game in 0..300 {
            let mut pos = Position::startpos();
            for _ply in 0..220 {
                let mut list = [Move::NONE; MAX_MOVES];
                let n = legal_moves(&pos, &mut list);
                if n == 0 {
                    break;
                }
                pos.make(list[(rnd() % n as u64) as usize]);
                for &v in &[1i32, 37, 400, -400, 1500, -23] {
                    let s = scale(&pos, v, DEFAULT_MASK);
                    assert!(s.abs() <= v.abs(), "grew {} -> {}", v, s);
                    assert!(s == 0 || s.signum() == v.signum(), "sign flip");
                    let mir = mirror(&pos);
                    assert_eq!(s, scale(&mir, v, DEFAULT_MASK), "asymmetric: {}", pos.to_fen());
                    if material_scale(&pos, v) != v {
                        scaled_material += 1;
                    }
                    if pos.occ().count_ones() > 12 {
                        assert_eq!(material_scale(&pos, v), v);
                    }
                    checked += 1;
                }
            }
        }
        assert!(checked > 10_000);
        eprintln!("checked {} scalings, {} material-scaled", checked, scaled_material);
    }
}
