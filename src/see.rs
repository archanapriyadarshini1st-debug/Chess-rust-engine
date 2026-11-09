//! Static Exchange Evaluation (SEE). Reckless, Stockfish and Viridithas all
//! use SEE to prune losing captures in both search and quiescence (~60–80 Elo).

use crate::attacks::{bishop_attacks, king_attacks, knight_attacks, pawn_attacks, rook_attacks};
use crate::board::Position;
use crate::eval::SEE_VALUE;
use crate::types::{Color, Move, PieceType, Square};

fn lva(pos: &Position, attackers: u64, color: Color) -> Option<(PieceType, Square)> {
    let ours = attackers & pos.colors[color.index()];
    if ours == 0 {
        return None;
    }
    for ty in 0..6 {
        let bb = ours & pos.pieces[ty];
        if bb != 0 {
            return Some((PieceType::from_index(ty), Square(bb.trailing_zeros() as u8)));
        }
    }
    None
}

fn xray_update(pos: &Position, occ: u64, from: Square, to: Square) -> u64 {
    let bishops = pos.pieces[PieceType::Bishop.index()] | pos.pieces[PieceType::Queen.index()];
    let rooks = pos.pieces[PieceType::Rook.index()] | pos.pieces[PieceType::Queen.index()];
    let mut extra = 0u64;
    extra |= bishop_attacks(to, occ) & bishops;
    extra |= rook_attacks(to, occ) & rooks;
    let _ = from;
    extra & occ
}

/// Returns true if the capture/promo is not a clear material loss (SEE >= threshold).
pub fn see_ge(pos: &Position, mv: Move, threshold: i32) -> bool {
    if mv.is_castle() {
        return threshold <= 0;
    }
    let from = mv.from();
    let to = mv.to();
    let us = pos.side;
    let mut piece = pos.piece_on(from);
    if piece.is_none() {
        return false;
    }

    let mut score = if mv.is_ep() {
        SEE_VALUE[PieceType::Pawn.index()]
    } else if !pos.piece_on(to).is_none() {
        SEE_VALUE[pos.piece_on(to).ty().index()]
    } else {
        0
    };
    if mv.is_promo() {
        score += SEE_VALUE[mv.promo_piece().index()] - SEE_VALUE[PieceType::Pawn.index()];
        piece = crate::types::Piece::new(us, mv.promo_piece());
    }
    score -= threshold;
    if score < 0 {
        return false;
    }

    score -= SEE_VALUE[piece.ty().index()];
    if score >= 0 {
        return true;
    }

    let mut occ = pos.occ() ^ from.bb();
    if mv.is_ep() {
        let cap = if us == Color::White {
            Square(to.0 - 8)
        } else {
            Square(to.0 + 8)
        };
        occ ^= cap.bb();
    }
    occ |= to.bb();

    let mut attackers = pos.attackers_to(to, occ, Color::White)
        | pos.attackers_to(to, occ, Color::Black);
    attackers &= occ;
    attackers |= xray_update(pos, occ, from, to);
    attackers &= occ;

    let mut side = us.flip();
    loop {
        let Some((ty, sq)) = lva(pos, attackers, side) else {
            break;
        };
        occ ^= sq.bb();
        attackers ^= sq.bb();
        if ty == PieceType::Pawn || ty == PieceType::Bishop || ty == PieceType::Queen {
            attackers |= bishop_attacks(to, occ)
                & (pos.pieces[PieceType::Bishop.index()] | pos.pieces[PieceType::Queen.index()])
                & occ;
        }
        if ty == PieceType::Rook || ty == PieceType::Queen {
            attackers |= rook_attacks(to, occ)
                & (pos.pieces[PieceType::Rook.index()] | pos.pieces[PieceType::Queen.index()])
                & occ;
        }
        attackers |= knight_attacks(to) & pos.pieces[PieceType::Knight.index()] & occ;
        attackers |= king_attacks(to) & pos.pieces[PieceType::King.index()] & occ;
        attackers |= pawn_attacks(side.flip(), to) & pos.pieces[PieceType::Pawn.index()] & occ;
        attackers &= occ;

        score = -score - 1 - SEE_VALUE[ty.index()];
        side = side.flip();
        if score >= 0 {
            if ty == PieceType::King && (attackers & pos.colors[side.index()]) != 0 {
                side = side.flip();
            }
            break;
        }
    }
    side != us
}
