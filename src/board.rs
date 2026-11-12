//! Copy-make bitboard position: FEN, make, attacks, checks.
//!
//! Reckless switched from make/unmake to copy-make for simpler code and similar
//! (often better) speed. A Position is ~200 bytes and Copy.

use crate::attacks::{
    bishop_attacks, king_attacks, knight_attacks, pawn_attacks, rook_attacks,
};
use crate::bitboard::Bitboard;
use crate::types::{
    Color, Move, Piece, PieceType, Square, BK, BQ, FLAG_CAPTURE, FLAG_DOUBLE, FLAG_EP,
    FLAG_KING_CASTLE, FLAG_PROMO_CAP_B, FLAG_PROMO_CAP_N, FLAG_PROMO_CAP_Q, FLAG_PROMO_CAP_R,
    FLAG_PROMO_N, FLAG_QUEEN_CASTLE, WK, WQ,
};
use crate::zobrist::ZOBRIST;

pub const START_FEN: &str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

/// Squares whose occupation / capture changes a given castling right.
const CASTLE_MASK: [u8; 64] = {
    let mut m = [0x0Fu8; 64];
    m[Square::A1.0 as usize] = !WQ;
    m[Square::H1.0 as usize] = !WK;
    m[Square::E1.0 as usize] = !(WK | WQ);
    m[Square::A8.0 as usize] = !BQ;
    m[Square::H8.0 as usize] = !BK;
    m[Square::E8.0 as usize] = !(BK | BQ);
    m
};

#[derive(Clone, Copy, Debug)]
pub struct Position {
    pub pieces: [u64; 6],
    pub colors: [u64; 2],
    pub mailbox: [Piece; 64],
    pub side: Color,
    pub castling: u8,
    pub ep: Option<Square>,
    pub halfmove: u16,
    pub fullmove: u16,
    pub hash: u64,
}

impl Position {
    pub fn empty() -> Position {
        Position {
            pieces: [0; 6],
            colors: [0; 2],
            mailbox: [Piece::NONE; 64],
            side: Color::White,
            castling: 0,
            ep: None,
            halfmove: 0,
            fullmove: 1,
            hash: 0,
        }
    }

    pub fn startpos() -> Position {
        Position::from_fen(START_FEN).expect("start fen")
    }

    #[inline]
    pub fn occ(&self) -> u64 {
        self.colors[0] | self.colors[1]
    }

    #[inline]
    pub fn us(&self) -> Color {
        self.side
    }

    #[inline]
    pub fn them(&self) -> Color {
        self.side.flip()
    }

    #[inline]
    pub fn piece_on(&self, sq: Square) -> Piece {
        self.mailbox[sq.index()]
    }

    #[inline]
    pub fn bb(&self, color: Color, ty: PieceType) -> u64 {
        self.pieces[ty.index()] & self.colors[color.index()]
    }

    #[inline]
    pub fn king_sq(&self, color: Color) -> Square {
        Bitboard(self.bb(color, PieceType::King)).lsb()
    }

    pub fn place(&mut self, sq: Square, piece: Piece) {
        debug_assert!(self.mailbox[sq.index()].is_none());
        self.mailbox[sq.index()] = piece;
        self.pieces[piece.ty().index()] |= sq.bb();
        self.colors[piece.color().index()] |= sq.bb();
        self.hash ^= ZOBRIST.piece[piece.index()][sq.index()];
    }

    pub fn take(&mut self, sq: Square) -> Piece {
        let piece = self.mailbox[sq.index()];
        debug_assert!(!piece.is_none());
        self.mailbox[sq.index()] = Piece::NONE;
        self.pieces[piece.ty().index()] ^= sq.bb();
        self.colors[piece.color().index()] ^= sq.bb();
        self.hash ^= ZOBRIST.piece[piece.index()][sq.index()];
        piece
    }

    /// Reject positions the search cannot handle (EXP-GP2) and repair harmless
    /// inconsistencies. A GUI or fuzzer that sends a position without a king,
    /// with the side NOT to move in check, or with pawns on the back rank used to
    /// make the engine panic (index out of range in the attack tables), which
    /// forfeits the game. Returns false when the position is unusable.
    fn sanitize(&mut self) -> bool {
        for c in [Color::White, Color::Black] {
            if self.bb(c, PieceType::King).count_ones() != 1 {
                return false;
            }
            if self.bb(c, PieceType::Pawn).count_ones() > 8 || self.colors[c.index()].count_ones() > 16 {
                return false;
            }
        }
        if self.pieces[PieceType::Pawn.index()] & 0xFF00_0000_0000_00FF != 0 {
            return false;
        }
        // The side that just moved can never be left in check.
        if self.in_check_for(self.side.flip()) {
            return false;
        }
        // Castling rights only make sense with the king and rook on their home squares.
        let mut ok = 0u8;
        let wk = self.piece_on(Square::E1) == Piece::new(Color::White, PieceType::King);
        let bk = self.piece_on(Square::E8) == Piece::new(Color::Black, PieceType::King);
        let wr = Piece::new(Color::White, PieceType::Rook);
        let br = Piece::new(Color::Black, PieceType::Rook);
        if wk && self.piece_on(Square::H1) == wr {
            ok |= WK;
        }
        if wk && self.piece_on(Square::A1) == wr {
            ok |= WQ;
        }
        if bk && self.piece_on(Square::H8) == br {
            ok |= BK;
        }
        if bk && self.piece_on(Square::A8) == br {
            ok |= BQ;
        }
        self.castling &= ok;
        // An en-passant square must be empty, on the right rank, with the pawn behind it.
        if let Some(ep) = self.ep {
            let (rank, pawn_rank, victim) = if self.side == Color::White {
                (5u8, 4u8, Piece::new(Color::Black, PieceType::Pawn))
            } else {
                (2u8, 3u8, Piece::new(Color::White, PieceType::Pawn))
            };
            let behind = Square::from_file_rank(ep.file(), pawn_rank);
            if ep.rank() != rank || !self.piece_on(ep).is_none() || self.piece_on(behind) != victim {
                self.ep = None;
            }
        }
        true
    }

    pub fn from_fen(fen: &str) -> Option<Position> {
        let mut pos = Position::empty();
        let mut parts = fen.split_whitespace();
        let board = parts.next()?;
        let mut rank: i32 = 7;
        let mut file: i32 = 0;
        for c in board.bytes() {
            match c {
                b'/' => {
                    if file != 8 || rank == 0 {
                        // rank may be 0 at the very end; handled below
                    }
                    rank -= 1;
                    file = 0;
                    if rank < 0 {
                        return None;
                    }
                }
                b'1'..=b'8' => {
                    file += (c - b'0') as i32;
                    if file > 8 {
                        return None;
                    }
                }
                _ => {
                    if file >= 8 {
                        return None;
                    }
                    let piece = Piece::from_fen(c)?;
                    pos.place(Square::from_file_rank(file as u8, rank as u8), piece);
                    file += 1;
                }
            }
        }
        if rank != 0 || file != 8 {
            return None;
        }

        match parts.next()?.as_bytes() {
            b"w" => pos.side = Color::White,
            b"b" => pos.side = Color::Black,
            _ => return None,
        }

        let castle = parts.next()?;
        if castle.as_bytes() != b"-" {
            for c in castle.bytes() {
                pos.castling |= match c {
                    b'K' => WK,
                    b'Q' => WQ,
                    b'k' => BK,
                    b'q' => BQ,
                    _ => return None,
                };
            }
        }

        let ep = parts.next()?;
        if ep.as_bytes() != b"-" {
            pos.ep = Some(Square::from_uci(ep)?);
        }

        if let Some(hm) = parts.next() {
            pos.halfmove = hm.parse().ok()?;
        }
        if let Some(fm) = parts.next() {
            pos.fullmove = fm.parse().ok()?;
        }

        if !pos.sanitize() {
            return None;
        }

        pos.hash ^= ZOBRIST.castle[pos.castling as usize];
        if let Some(ep) = pos.ep {
            pos.hash ^= ZOBRIST.ep[ep.file() as usize];
        }
        if pos.side == Color::Black {
            pos.hash ^= ZOBRIST.side;
        }
        Some(pos)
    }

    pub fn to_fen(&self) -> String {
        let mut s = String::new();
        for rank in (0..8).rev() {
            let mut empty = 0u8;
            for file in 0..8 {
                let p = self.piece_on(Square::from_file_rank(file, rank));
                if p.is_none() {
                    empty += 1;
                } else {
                    if empty > 0 {
                        s.push((b'0' + empty) as char);
                        empty = 0;
                    }
                    s.push(p.fen_char() as char);
                }
            }
            if empty > 0 {
                s.push((b'0' + empty) as char);
            }
            if rank > 0 {
                s.push('/');
            }
        }
        s.push(' ');
        s.push(if self.side == Color::White { 'w' } else { 'b' });
        s.push(' ');
        if self.castling == 0 {
            s.push('-');
        } else {
            if self.castling & WK != 0 {
                s.push('K');
            }
            if self.castling & WQ != 0 {
                s.push('Q');
            }
            if self.castling & BK != 0 {
                s.push('k');
            }
            if self.castling & BQ != 0 {
                s.push('q');
            }
        }
        s.push(' ');
        if let Some(ep) = self.ep {
            let u = ep.uci();
            s.push(u[0] as char);
            s.push(u[1] as char);
        } else {
            s.push('-');
        }
        s.push(' ');
        s.push_str(&self.halfmove.to_string());
        s.push(' ');
        s.push_str(&self.fullmove.to_string());
        s
    }

    /// Pieces of `by` that attack `sq`.
    pub fn attackers_to(&self, sq: Square, occ: u64, by: Color) -> u64 {
        let themed = self.colors[by.index()];
        let pawns = pawn_attacks(by.flip(), sq) & self.pieces[PieceType::Pawn.index()];
        let knights = knight_attacks(sq) & self.pieces[PieceType::Knight.index()];
        let kings = king_attacks(sq) & self.pieces[PieceType::King.index()];
        let bishops = bishop_attacks(sq, occ)
            & (self.pieces[PieceType::Bishop.index()] | self.pieces[PieceType::Queen.index()]);
        let rooks = rook_attacks(sq, occ)
            & (self.pieces[PieceType::Rook.index()] | self.pieces[PieceType::Queen.index()]);
        (pawns | knights | kings | bishops | rooks) & themed
    }

    #[inline]
    pub fn attacked_by(&self, sq: Square, by: Color) -> bool {
        self.attackers_to(sq, self.occ(), by) != 0
    }

    #[inline]
    pub fn in_check(&self) -> bool {
        self.in_check_for(self.side)
    }

    #[inline]
    pub fn in_check_for(&self, color: Color) -> bool {
        self.attacked_by(self.king_sq(color), color.flip())
    }

    /// After `make`, true if the mover left their king in check.
    #[inline]
    pub fn was_illegal(&self) -> bool {
        self.in_check_for(self.side.flip())
    }

    pub fn make(&mut self, mv: Move) {
        let from = mv.from();
        let to = mv.to();
        let flags = mv.flags();
        let us = self.side;
        let piece = self.take(from);

        if let Some(ep) = self.ep {
            self.hash ^= ZOBRIST.ep[ep.file() as usize];
            self.ep = None;
        }

        self.halfmove += 1;
        if piece.ty() == PieceType::Pawn {
            self.halfmove = 0;
        }

        match flags {
            FLAG_CAPTURE | FLAG_PROMO_CAP_N | FLAG_PROMO_CAP_B | FLAG_PROMO_CAP_R
            | FLAG_PROMO_CAP_Q => {
                let _ = self.take(to);
                self.halfmove = 0;
            }
            FLAG_EP => {
                let cap = if us == Color::White {
                    Square(to.0 - 8)
                } else {
                    Square(to.0 + 8)
                };
                let _ = self.take(cap);
                self.halfmove = 0;
            }
            _ => {}
        }

        if flags == FLAG_KING_CASTLE {
            self.place(to, piece);
            if us == Color::White {
                let rook = self.take(Square::H1);
                self.place(Square::F1, rook);
            } else {
                let rook = self.take(Square::H8);
                self.place(Square::F8, rook);
            }
        } else if flags == FLAG_QUEEN_CASTLE {
            self.place(to, piece);
            if us == Color::White {
                let rook = self.take(Square::A1);
                self.place(Square::D1, rook);
            } else {
                let rook = self.take(Square::A8);
                self.place(Square::D8, rook);
            }
        } else if flags >= FLAG_PROMO_N {
            self.place(to, Piece::new(us, mv.promo_piece()));
        } else {
            self.place(to, piece);
        }

        if flags == FLAG_DOUBLE {
            let ep = Square(if us == Color::White {
                from.0 + 8
            } else {
                from.0 - 8
            });
            self.ep = Some(ep);
            self.hash ^= ZOBRIST.ep[ep.file() as usize];
        }

        let old_c = self.castling;
        self.castling &= CASTLE_MASK[from.index()] & CASTLE_MASK[to.index()];
        if old_c != self.castling {
            self.hash ^= ZOBRIST.castle[old_c as usize] ^ ZOBRIST.castle[self.castling as usize];
        }

        if us == Color::Black {
            self.fullmove += 1;
        }
        self.side = us.flip();
        self.hash ^= ZOBRIST.side;
    }

    pub fn display(&self) -> String {
        let mut s = String::new();
        s.push_str("  +-----------------+\n");
        for rank in (0..8).rev() {
            s.push_str(&format!("{} |", rank + 1));
            for file in 0..8 {
                let p = self.piece_on(Square::from_file_rank(file, rank));
                s.push(' ');
                s.push(p.fen_char() as char);
            }
            s.push_str(" |\n");
        }
        s.push_str("  +-----------------+\n    a b c d e f g h\n");
        s.push_str(&format!("fen: {}\n", self.to_fen()));
        s.push_str(&format!("key: {:016x}\n", self.hash));
        s
    }

    pub fn is_insufficient_material(&self) -> bool {
        let pawns_rooks_queens = self.pieces[PieceType::Pawn.index()]
            | self.pieces[PieceType::Rook.index()]
            | self.pieces[PieceType::Queen.index()];
        if pawns_rooks_queens != 0 {
            return false;
        }
        let minors =
            (self.pieces[PieceType::Knight.index()] | self.pieces[PieceType::Bishop.index()])
                .count_ones();
        minors <= 1
    }
}

/// Map a UCI move string onto a generated legal move (needed for flags).
pub fn parse_uci_move(pos: &Position, token: &str) -> Option<Move> {
    let b = token.as_bytes();
    if b.len() < 4 {
        return None;
    }
    let from = Square::from_uci(&token[0..2])?;
    let to = Square::from_uci(&token[2..4])?;
    let promo = if b.len() >= 5 {
        PieceType::from_promo_char(b[4])
    } else {
        None
    };
    let mut moves = [Move::NONE; crate::types::MAX_MOVES];
    let n = crate::movegen::legal_moves(pos, &mut moves);
    for i in 0..n {
        let mv = moves[i];
        if mv.from() == from && mv.to() == to {
            if let Some(p) = promo {
                if mv.is_promo() && mv.promo_piece() == p {
                    return Some(mv);
                }
            } else if !mv.is_promo() {
                return Some(mv);
            }
        }
    }
    None
}

