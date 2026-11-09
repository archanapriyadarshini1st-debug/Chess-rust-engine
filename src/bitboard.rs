//! Bitboard helpers and LERF constants.

use crate::types::Square;

#[derive(Clone, Copy, PartialEq, Eq, Default, Debug)]
pub struct Bitboard(pub u64);

impl Bitboard {
    pub const EMPTY: Bitboard = Bitboard(0);
    pub const ALL: Bitboard = Bitboard(!0);

    #[inline]
    pub const fn from_sq(sq: Square) -> Bitboard {
        Bitboard(1u64 << sq.0)
    }

    #[inline]
    pub const fn is_empty(self) -> bool {
        self.0 == 0
    }

    #[inline]
    pub const fn several(self) -> bool {
        self.0 & self.0.wrapping_sub(1) != 0
    }

    #[inline]
    pub const fn popcount(self) -> u32 {
        self.0.count_ones()
    }

    #[inline]
    pub const fn lsb(self) -> Square {
        Square(self.0.trailing_zeros() as u8)
    }

    #[inline]
    pub const fn msb(self) -> Square {
        Square((63 - self.0.leading_zeros()) as u8)
    }

    #[inline]
    pub fn pop_lsb(&mut self) -> Square {
        let s = self.lsb();
        self.0 &= self.0.wrapping_sub(1);
        s
    }

    #[inline]
    pub const fn contains(self, sq: Square) -> bool {
        self.0 & (1u64 << sq.0) != 0
    }

    #[inline]
    pub const fn north(self) -> Bitboard {
        Bitboard(self.0 << 8)
    }

    #[inline]
    pub const fn south(self) -> Bitboard {
        Bitboard(self.0 >> 8)
    }

    #[inline]
    pub const fn east(self) -> Bitboard {
        Bitboard((self.0 & !FILE_H) << 1)
    }

    #[inline]
    pub const fn west(self) -> Bitboard {
        Bitboard((self.0 & !FILE_A) >> 1)
    }

    #[inline]
    pub const fn ne(self) -> Bitboard {
        Bitboard((self.0 & !FILE_H) << 9)
    }

    #[inline]
    pub const fn nw(self) -> Bitboard {
        Bitboard((self.0 & !FILE_A) << 7)
    }

    #[inline]
    pub const fn se(self) -> Bitboard {
        Bitboard((self.0 & !FILE_H) >> 7)
    }

    #[inline]
    pub const fn sw(self) -> Bitboard {
        Bitboard((self.0 & !FILE_A) >> 9)
    }
}

impl std::ops::BitOr for Bitboard {
    type Output = Bitboard;
    #[inline]
    fn bitor(self, rhs: Bitboard) -> Bitboard {
        Bitboard(self.0 | rhs.0)
    }
}
impl std::ops::BitAnd for Bitboard {
    type Output = Bitboard;
    #[inline]
    fn bitand(self, rhs: Bitboard) -> Bitboard {
        Bitboard(self.0 & rhs.0)
    }
}
impl std::ops::BitXor for Bitboard {
    type Output = Bitboard;
    #[inline]
    fn bitxor(self, rhs: Bitboard) -> Bitboard {
        Bitboard(self.0 ^ rhs.0)
    }
}
impl std::ops::Not for Bitboard {
    type Output = Bitboard;
    #[inline]
    fn not(self) -> Bitboard {
        Bitboard(!self.0)
    }
}
impl std::ops::BitOrAssign for Bitboard {
    #[inline]
    fn bitor_assign(&mut self, rhs: Bitboard) {
        self.0 |= rhs.0;
    }
}
impl std::ops::BitAndAssign for Bitboard {
    #[inline]
    fn bitand_assign(&mut self, rhs: Bitboard) {
        self.0 &= rhs.0;
    }
}
impl std::ops::BitXorAssign for Bitboard {
    #[inline]
    fn bitxor_assign(&mut self, rhs: Bitboard) {
        self.0 ^= rhs.0;
    }
}

impl Iterator for Bitboard {
    type Item = Square;
    #[inline]
    fn next(&mut self) -> Option<Square> {
        if self.0 == 0 {
            None
        } else {
            Some(self.pop_lsb())
        }
    }
}

pub const FILE_A: u64 = 0x0101_0101_0101_0101;
pub const FILE_B: u64 = FILE_A << 1;
pub const FILE_C: u64 = FILE_A << 2;
pub const FILE_D: u64 = FILE_A << 3;
pub const FILE_E: u64 = FILE_A << 4;
pub const FILE_F: u64 = FILE_A << 5;
pub const FILE_G: u64 = FILE_A << 6;
pub const FILE_H: u64 = FILE_A << 7;

pub const RANK_1: u64 = 0xFF;
pub const RANK_2: u64 = RANK_1 << 8;
pub const RANK_3: u64 = RANK_1 << 16;
pub const RANK_4: u64 = RANK_1 << 24;
pub const RANK_5: u64 = RANK_1 << 32;
pub const RANK_6: u64 = RANK_1 << 40;
pub const RANK_7: u64 = RANK_1 << 48;
pub const RANK_8: u64 = RANK_1 << 56;

pub const FILES: [u64; 8] = [
    FILE_A, FILE_B, FILE_C, FILE_D, FILE_E, FILE_F, FILE_G, FILE_H,
];
pub const RANKS: [u64; 8] = [
    RANK_1, RANK_2, RANK_3, RANK_4, RANK_5, RANK_6, RANK_7, RANK_8,
];

/// Adjacent files (for isolated / passed pawn masks).
pub const ADJACENT_FILES: [u64; 8] = [
    FILE_B,
    FILE_A | FILE_C,
    FILE_B | FILE_D,
    FILE_C | FILE_E,
    FILE_D | FILE_F,
    FILE_E | FILE_G,
    FILE_F | FILE_H,
    FILE_G,
];
