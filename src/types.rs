//! Core chess types: colors, pieces, squares, and packed 16-bit moves.
//!
//! Square mapping is Little-Endian Rank-File (LERF): a1 = 0, h1 = 7, a8 = 56, h8 = 63.
//! This is the same mapping Reckless, Viridithas, Stockfish and most bitboard engines use.

use std::fmt;

pub const MAX_MOVES: usize = 218;
pub const MAX_PLY: usize = 128;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Color {
    White = 0,
    Black = 1,
}

impl Color {
    #[inline]
    pub const fn flip(self) -> Color {
        match self {
            Color::White => Color::Black,
            Color::Black => Color::White,
        }
    }

    #[inline]
    pub const fn index(self) -> usize {
        self as usize
    }

    #[inline]
    pub const fn from_index(i: usize) -> Color {
        if i == 0 {
            Color::White
        } else {
            Color::Black
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum PieceType {
    Pawn = 0,
    Knight = 1,
    Bishop = 2,
    Rook = 3,
    Queen = 4,
    King = 5,
}

impl PieceType {
    #[inline]
    pub const fn index(self) -> usize {
        self as usize
    }

    #[inline]
    pub const fn from_index(i: usize) -> PieceType {
        match i {
            0 => PieceType::Pawn,
            1 => PieceType::Knight,
            2 => PieceType::Bishop,
            3 => PieceType::Rook,
            4 => PieceType::Queen,
            _ => PieceType::King,
        }
    }

    pub const fn from_promo_char(c: u8) -> Option<PieceType> {
        match c {
            b'n' | b'N' => Some(PieceType::Knight),
            b'b' | b'B' => Some(PieceType::Bishop),
            b'r' | b'R' => Some(PieceType::Rook),
            b'q' | b'Q' => Some(PieceType::Queen),
            _ => None,
        }
    }

    pub const fn promo_char(self) -> u8 {
        match self {
            PieceType::Knight => b'n',
            PieceType::Bishop => b'b',
            PieceType::Rook => b'r',
            PieceType::Queen => b'q',
            _ => b'?',
        }
    }
}

/// Packed piece: 0–5 white P–K, 6–11 black P–K, 12 = empty.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Piece(pub u8);

impl Piece {
    pub const NONE: Piece = Piece(12);

    #[inline]
    pub const fn new(color: Color, ty: PieceType) -> Piece {
        Piece(ty as u8 + (color as u8) * 6)
    }

    #[inline]
    pub const fn is_none(self) -> bool {
        self.0 >= 12
    }

    #[inline]
    pub const fn color(self) -> Color {
        if self.0 < 6 {
            Color::White
        } else {
            Color::Black
        }
    }

    #[inline]
    pub const fn ty(self) -> PieceType {
        PieceType::from_index((self.0 % 6) as usize)
    }

    #[inline]
    pub const fn index(self) -> usize {
        self.0 as usize
    }

    pub const fn from_fen(c: u8) -> Option<Piece> {
        let (color, ty) = match c {
            b'P' => (Color::White, PieceType::Pawn),
            b'N' => (Color::White, PieceType::Knight),
            b'B' => (Color::White, PieceType::Bishop),
            b'R' => (Color::White, PieceType::Rook),
            b'Q' => (Color::White, PieceType::Queen),
            b'K' => (Color::White, PieceType::King),
            b'p' => (Color::Black, PieceType::Pawn),
            b'n' => (Color::Black, PieceType::Knight),
            b'b' => (Color::Black, PieceType::Bishop),
            b'r' => (Color::Black, PieceType::Rook),
            b'q' => (Color::Black, PieceType::Queen),
            b'k' => (Color::Black, PieceType::King),
            _ => return None,
        };
        Some(Piece::new(color, ty))
    }

    pub const fn fen_char(self) -> u8 {
        const CHARS: [u8; 12] = [
            b'P', b'N', b'B', b'R', b'Q', b'K', b'p', b'n', b'b', b'r', b'q', b'k',
        ];
        if self.0 < 12 {
            CHARS[self.0 as usize]
        } else {
            b'.'
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Debug)]
pub struct Square(pub u8);

impl Square {
    pub const A1: Square = Square(0);
    pub const B1: Square = Square(1);
    pub const C1: Square = Square(2);
    pub const D1: Square = Square(3);
    pub const E1: Square = Square(4);
    pub const F1: Square = Square(5);
    pub const G1: Square = Square(6);
    pub const H1: Square = Square(7);
    pub const A8: Square = Square(56);
    pub const B8: Square = Square(57);
    pub const C8: Square = Square(58);
    pub const D8: Square = Square(59);
    pub const E8: Square = Square(60);
    pub const F8: Square = Square(61);
    pub const G8: Square = Square(62);
    pub const H8: Square = Square(63);

    #[inline]
    pub const fn new(idx: u8) -> Square {
        Square(idx)
    }

    #[inline]
    pub const fn from_file_rank(file: u8, rank: u8) -> Square {
        Square(file + rank * 8)
    }

    #[inline]
    pub const fn file(self) -> u8 {
        self.0 & 7
    }

    #[inline]
    pub const fn rank(self) -> u8 {
        self.0 >> 3
    }

    #[inline]
    pub const fn index(self) -> usize {
        self.0 as usize
    }

    #[inline]
    pub const fn bb(self) -> u64 {
        1u64 << self.0
    }

    #[inline]
    pub const fn flip(self) -> Square {
        Square(self.0 ^ 56)
    }

    pub fn from_uci(s: &str) -> Option<Square> {
        let b = s.as_bytes();
        if b.len() < 2 {
            return None;
        }
        let file = b[0];
        let rank = b[1];
        if !(b'a'..=b'h').contains(&file) || !(b'1'..=b'8').contains(&rank) {
            return None;
        }
        Some(Square::from_file_rank(file - b'a', rank - b'1'))
    }

    pub fn uci(self) -> [u8; 2] {
        [b'a' + self.file(), b'1' + self.rank()]
    }
}

impl fmt::Display for Square {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let u = self.uci();
        write!(f, "{}{}", u[0] as char, u[1] as char)
    }
}

pub const WK: u8 = 1;
pub const WQ: u8 = 2;
pub const BK: u8 = 4;
pub const BQ: u8 = 8;

/// 16-bit move: from (0–5), to (6–11), flags (12–15).
/// Flag layout matches the Chess Programming Wiki from-to encoding.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct Move(pub u16);

pub const FLAG_QUIET: u16 = 0;
pub const FLAG_DOUBLE: u16 = 1;
pub const FLAG_KING_CASTLE: u16 = 2;
pub const FLAG_QUEEN_CASTLE: u16 = 3;
pub const FLAG_CAPTURE: u16 = 4;
pub const FLAG_EP: u16 = 5;
pub const FLAG_PROMO_N: u16 = 8;
pub const FLAG_PROMO_B: u16 = 9;
pub const FLAG_PROMO_R: u16 = 10;
pub const FLAG_PROMO_Q: u16 = 11;
pub const FLAG_PROMO_CAP_N: u16 = 12;
pub const FLAG_PROMO_CAP_B: u16 = 13;
pub const FLAG_PROMO_CAP_R: u16 = 14;
pub const FLAG_PROMO_CAP_Q: u16 = 15;

impl Move {
    pub const NONE: Move = Move(0);

    #[inline]
    pub const fn new(from: Square, to: Square, flags: u16) -> Move {
        Move((from.0 as u16) | ((to.0 as u16) << 6) | (flags << 12))
    }

    #[inline]
    pub const fn from(self) -> Square {
        Square((self.0 & 63) as u8)
    }

    #[inline]
    pub const fn to(self) -> Square {
        Square(((self.0 >> 6) & 63) as u8)
    }

    #[inline]
    pub const fn flags(self) -> u16 {
        self.0 >> 12
    }

    #[inline]
    pub const fn is_none(self) -> bool {
        self.0 == 0
    }

    #[inline]
    pub const fn is_capture(self) -> bool {
        let f = self.flags();
        f == FLAG_CAPTURE || f == FLAG_EP || f >= FLAG_PROMO_CAP_N
    }

    #[inline]
    pub const fn is_promo(self) -> bool {
        self.flags() >= FLAG_PROMO_N
    }

    #[inline]
    pub const fn is_ep(self) -> bool {
        self.flags() == FLAG_EP
    }

    #[inline]
    pub const fn is_castle(self) -> bool {
        let f = self.flags();
        f == FLAG_KING_CASTLE || f == FLAG_QUEEN_CASTLE
    }

    #[inline]
    pub const fn is_double(self) -> bool {
        self.flags() == FLAG_DOUBLE
    }

    #[inline]
    pub const fn promo_piece(self) -> PieceType {
        match self.flags() & 3 {
            0 => PieceType::Knight,
            1 => PieceType::Bishop,
            2 => PieceType::Rook,
            _ => PieceType::Queen,
        }
    }

    pub fn to_uci(self) -> String {
        if self.is_none() {
            return "0000".to_string();
        }
        let f = self.from().uci();
        let t = self.to().uci();
        if self.is_promo() {
            format!(
                "{}{}{}{}{}",
                f[0] as char,
                f[1] as char,
                t[0] as char,
                t[1] as char,
                self.promo_piece().promo_char() as char
            )
        } else {
            format!(
                "{}{}{}{}",
                f[0] as char, f[1] as char, t[0] as char, t[1] as char
            )
        }
    }
}

impl fmt::Display for Move {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.to_uci())
    }
}

/// Scores in centipawns. Mate scores are MATE - ply.
pub const INF: i32 = 32_000;
pub const MATE: i32 = 31_000;
pub const MATE_IN_MAX: i32 = MATE - MAX_PLY as i32;
pub const DRAW: i32 = 0;

#[inline]
pub fn mate_in(ply: i32) -> i32 {
    MATE - ply
}

#[inline]
pub fn mated_in(ply: i32) -> i32 {
    -MATE + ply
}

#[inline]
pub fn is_mate_score(s: i32) -> bool {
    s.abs() >= MATE_IN_MAX
}
