//! Pseudo-legal generation plus a legality filter.
//!
//! Pseudo-legal + king-safety filter is the Reckless approach and is simpler
//! than fully legal generation with pin masks. Copy-make makes the filter cheap.

use crate::attacks::{
    bishop_attacks, king_attacks, knight_attacks, pawn_attacks, queen_attacks, rook_attacks,
};
use crate::bitboard::{RANK_2, RANK_7};
use crate::types::{
    Color, Move, PieceType, Square, BK, BQ, FLAG_CAPTURE, FLAG_DOUBLE, FLAG_EP, FLAG_KING_CASTLE,
    FLAG_PROMO_B, FLAG_PROMO_CAP_B, FLAG_PROMO_CAP_N, FLAG_PROMO_CAP_Q, FLAG_PROMO_CAP_R,
    FLAG_PROMO_N, FLAG_PROMO_Q, FLAG_PROMO_R, FLAG_QUEEN_CASTLE, FLAG_QUIET, MAX_MOVES, WK, WQ,
};
use crate::board::Position;

#[inline]
fn push(list: &mut [Move; MAX_MOVES], n: &mut usize, mv: Move) {
    list[*n] = mv;
    *n += 1;
}

fn add_promos(list: &mut [Move; MAX_MOVES], n: &mut usize, from: Square, to: Square, cap: bool) {
    if cap {
        push(list, n, Move::new(from, to, FLAG_PROMO_CAP_Q));
        push(list, n, Move::new(from, to, FLAG_PROMO_CAP_N));
        push(list, n, Move::new(from, to, FLAG_PROMO_CAP_R));
        push(list, n, Move::new(from, to, FLAG_PROMO_CAP_B));
    } else {
        push(list, n, Move::new(from, to, FLAG_PROMO_Q));
        push(list, n, Move::new(from, to, FLAG_PROMO_N));
        push(list, n, Move::new(from, to, FLAG_PROMO_R));
        push(list, n, Move::new(from, to, FLAG_PROMO_B));
    }
}

pub fn pseudo_legal(pos: &Position, list: &mut [Move; MAX_MOVES]) -> usize {
    let mut n = 0;
    let us = pos.side;
    let them = us.flip();
    let occ = pos.occ();
    let ours = pos.colors[us.index()];
    let theirs = pos.colors[them.index()];
    let empty = !occ;

    // Pawns
    let pawns = pos.bb(us, PieceType::Pawn);
    if us == Color::White {
        let single = (pawns << 8) & empty;
        let double = ((single & (RANK_2 << 8)) << 8) & empty;
        let mut bb = single;
        while bb != 0 {
            let to = Square(bb.trailing_zeros() as u8);
            bb &= bb - 1;
            let from = Square(to.0 - 8);
            if to.0 >= 56 {
                add_promos(list, &mut n, from, to, false);
            } else {
                push(list, &mut n, Move::new(from, to, FLAG_QUIET));
            }
        }
        let mut bb = double;
        while bb != 0 {
            let to = Square(bb.trailing_zeros() as u8);
            bb &= bb - 1;
            let from = Square(to.0 - 16);
            push(list, &mut n, Move::new(from, to, FLAG_DOUBLE));
        }
        let mut p = pawns;
        while p != 0 {
            let from = Square(p.trailing_zeros() as u8);
            p &= p - 1;
            let mut att = pawn_attacks(Color::White, from) & theirs;
            while att != 0 {
                let to = Square(att.trailing_zeros() as u8);
                att &= att - 1;
                if to.0 >= 56 {
                    add_promos(list, &mut n, from, to, true);
                } else {
                    push(list, &mut n, Move::new(from, to, FLAG_CAPTURE));
                }
            }
        }
        if let Some(ep) = pos.ep {
            let mut p = pawns;
            while p != 0 {
                let from = Square(p.trailing_zeros() as u8);
                p &= p - 1;
                if pawn_attacks(Color::White, from) & ep.bb() != 0 {
                    push(list, &mut n, Move::new(from, ep, FLAG_EP));
                }
            }
        }
    } else {
        let single = (pawns >> 8) & empty;
        let double = ((single & (RANK_7 >> 8)) >> 8) & empty;
        let mut bb = single;
        while bb != 0 {
            let to = Square(bb.trailing_zeros() as u8);
            bb &= bb - 1;
            let from = Square(to.0 + 8);
            if to.0 < 8 {
                add_promos(list, &mut n, from, to, false);
            } else {
                push(list, &mut n, Move::new(from, to, FLAG_QUIET));
            }
        }
        let mut bb = double;
        while bb != 0 {
            let to = Square(bb.trailing_zeros() as u8);
            bb &= bb - 1;
            let from = Square(to.0 + 16);
            push(list, &mut n, Move::new(from, to, FLAG_DOUBLE));
        }
        let mut p = pawns;
        while p != 0 {
            let from = Square(p.trailing_zeros() as u8);
            p &= p - 1;
            let mut att = pawn_attacks(Color::Black, from) & theirs;
            while att != 0 {
                let to = Square(att.trailing_zeros() as u8);
                att &= att - 1;
                if to.0 < 8 {
                    add_promos(list, &mut n, from, to, true);
                } else {
                    push(list, &mut n, Move::new(from, to, FLAG_CAPTURE));
                }
            }
        }
        if let Some(ep) = pos.ep {
            let mut p = pawns;
            while p != 0 {
                let from = Square(p.trailing_zeros() as u8);
                p &= p - 1;
                if pawn_attacks(Color::Black, from) & ep.bb() != 0 {
                    push(list, &mut n, Move::new(from, ep, FLAG_EP));
                }
            }
        }
    }

    // Knights
    let mut kn = pos.bb(us, PieceType::Knight);
    while kn != 0 {
        let from = Square(kn.trailing_zeros() as u8);
        kn &= kn - 1;
        let mut att = knight_attacks(from) & !ours;
        while att != 0 {
            let to = Square(att.trailing_zeros() as u8);
            att &= att - 1;
            let flag = if theirs & to.bb() != 0 {
                FLAG_CAPTURE
            } else {
                FLAG_QUIET
            };
            push(list, &mut n, Move::new(from, to, flag));
        }
    }

    // Bishops
    let mut bb = pos.bb(us, PieceType::Bishop);
    while bb != 0 {
        let from = Square(bb.trailing_zeros() as u8);
        bb &= bb - 1;
        let mut att = bishop_attacks(from, occ) & !ours;
        while att != 0 {
            let to = Square(att.trailing_zeros() as u8);
            att &= att - 1;
            let flag = if theirs & to.bb() != 0 {
                FLAG_CAPTURE
            } else {
                FLAG_QUIET
            };
            push(list, &mut n, Move::new(from, to, flag));
        }
    }

    // Rooks
    let mut bb = pos.bb(us, PieceType::Rook);
    while bb != 0 {
        let from = Square(bb.trailing_zeros() as u8);
        bb &= bb - 1;
        let mut att = rook_attacks(from, occ) & !ours;
        while att != 0 {
            let to = Square(att.trailing_zeros() as u8);
            att &= att - 1;
            let flag = if theirs & to.bb() != 0 {
                FLAG_CAPTURE
            } else {
                FLAG_QUIET
            };
            push(list, &mut n, Move::new(from, to, flag));
        }
    }

    // Queens
    let mut bb = pos.bb(us, PieceType::Queen);
    while bb != 0 {
        let from = Square(bb.trailing_zeros() as u8);
        bb &= bb - 1;
        let mut att = queen_attacks(from, occ) & !ours;
        while att != 0 {
            let to = Square(att.trailing_zeros() as u8);
            att &= att - 1;
            let flag = if theirs & to.bb() != 0 {
                FLAG_CAPTURE
            } else {
                FLAG_QUIET
            };
            push(list, &mut n, Move::new(from, to, flag));
        }
    }

    // King
    let from = pos.king_sq(us);
    let mut att = king_attacks(from) & !ours;
    while att != 0 {
        let to = Square(att.trailing_zeros() as u8);
        att &= att - 1;
        let flag = if theirs & to.bb() != 0 {
            FLAG_CAPTURE
        } else {
            FLAG_QUIET
        };
        push(list, &mut n, Move::new(from, to, flag));
    }

    // Castling. King must not be in check; path squares empty and unattacked.
    if !pos.in_check() {
        if us == Color::White {
            if pos.castling & WK != 0
                && occ & (Square::F1.bb() | Square::G1.bb()) == 0
                && !pos.attacked_by(Square::F1, them)
                && !pos.attacked_by(Square::G1, them)
            {
                push(
                    list,
                    &mut n,
                    Move::new(Square::E1, Square::G1, FLAG_KING_CASTLE),
                );
            }
            if pos.castling & WQ != 0
                && occ & (Square::B1.bb() | Square::C1.bb() | Square::D1.bb()) == 0
                && !pos.attacked_by(Square::D1, them)
                && !pos.attacked_by(Square::C1, them)
            {
                push(
                    list,
                    &mut n,
                    Move::new(Square::E1, Square::C1, FLAG_QUEEN_CASTLE),
                );
            }
        } else {
            if pos.castling & BK != 0
                && occ & (Square::F8.bb() | Square::G8.bb()) == 0
                && !pos.attacked_by(Square::F8, them)
                && !pos.attacked_by(Square::G8, them)
            {
                push(
                    list,
                    &mut n,
                    Move::new(Square::E8, Square::G8, FLAG_KING_CASTLE),
                );
            }
            if pos.castling & BQ != 0
                && occ & (Square::B8.bb() | Square::C8.bb() | Square::D8.bb()) == 0
                && !pos.attacked_by(Square::D8, them)
                && !pos.attacked_by(Square::C8, them)
            {
                push(
                    list,
                    &mut n,
                    Move::new(Square::E8, Square::C8, FLAG_QUEEN_CASTLE),
                );
            }
        }
    }

    n
}

pub fn legal_moves(pos: &Position, list: &mut [Move; MAX_MOVES]) -> usize {
    let n = pseudo_legal(pos, list);
    let mut w = 0;
    for i in 0..n {
        let mv = list[i];
        let mut np = *pos;
        np.make(mv);
        if !np.was_illegal() {
            list[w] = mv;
            w += 1;
        }
    }
    w
}

/// Captures + promotions + EP only (for quiescence).
pub fn noisy_moves(pos: &Position, list: &mut [Move; MAX_MOVES]) -> usize {
    let n = pseudo_legal(pos, list);
    let mut w = 0;
    for i in 0..n {
        let mv = list[i];
        if mv.is_capture() || mv.is_promo() {
            list[w] = mv;
            w += 1;
        }
    }
    w
}

pub fn has_legal_move(pos: &Position) -> bool {
    let mut list = [Move::NONE; MAX_MOVES];
    legal_moves(pos, &mut list) > 0
}
