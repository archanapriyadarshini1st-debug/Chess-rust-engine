//! Attack tables: leapers precomputed, sliders via ray + first-blocker.
//!
//! Slider generation uses the classic "precomputed ray XOR ray-beyond-blocker"
//! technique from the Chess Programming Wiki. Magics / PEXT are a later NPS
//! upgrade (see ROADMAP.md) but this is correct and already fast.

use crate::bitboard::Bitboard;
use crate::types::{Color, Square};
use std::sync::OnceLock;

const NORTH: usize = 0;
const SOUTH: usize = 1;
const EAST: usize = 2;
const WEST: usize = 3;
const NE: usize = 4;
const NW: usize = 5;
const SE: usize = 6;
const SW: usize = 7;

pub struct AttackTables {
    pub pawn: [[u64; 64]; 2],
    pub knight: [u64; 64],
    pub king: [u64; 64],
    rays: [[u64; 64]; 8],
    pub bishop_rays: [u64; 64],
    pub rook_rays: [u64; 64],
    /// Squares strictly in front of `sq` for `color` on the same file.
    pub forward_file: [[u64; 64]; 2],
    /// Passed-pawn span: front file + adjacent files, in front of the pawn.
    pub passed: [[u64; 64]; 2],
}

static TABLES: OnceLock<AttackTables> = OnceLock::new();

pub fn tables() -> &'static AttackTables {
    TABLES.get_or_init(AttackTables::init)
}

fn try_step(sq: i32, df: i32, dr: i32) -> Option<u8> {
    let f = sq % 8 + df;
    let r = sq / 8 + dr;
    if (0..8).contains(&f) && (0..8).contains(&r) {
        Some((r * 8 + f) as u8)
    } else {
        None
    }
}

fn walk_ray(sq: i32, df: i32, dr: i32) -> u64 {
    let mut bb = 0u64;
    let mut s = sq;
    while let Some(n) = try_step(s, df, dr) {
        bb |= 1u64 << n;
        s = n as i32;
    }
    bb
}

impl AttackTables {
    fn init() -> AttackTables {
        let mut pawn = [[0u64; 64]; 2];
        let mut knight = [0u64; 64];
        let mut king = [0u64; 64];
        let mut rays = [[0u64; 64]; 8];
        let mut bishop_rays = [0u64; 64];
        let mut rook_rays = [0u64; 64];
        let mut forward_file = [[0u64; 64]; 2];
        let mut passed = [[0u64; 64]; 2];

        const KNIGHT_D: [(i32, i32); 8] = [
            (1, 2),
            (2, 1),
            (2, -1),
            (1, -2),
            (-1, -2),
            (-2, -1),
            (-2, 1),
            (-1, 2),
        ];
        const KING_D: [(i32, i32); 8] = [
            (1, 0),
            (1, 1),
            (0, 1),
            (-1, 1),
            (-1, 0),
            (-1, -1),
            (0, -1),
            (1, -1),
        ];
        const RAY_D: [(i32, i32); 8] = [
            (0, 1),  // N
            (0, -1), // S
            (1, 0),  // E
            (-1, 0), // W
            (1, 1),  // NE
            (-1, 1), // NW
            (1, -1), // SE
            (-1, -1), // SW
        ];

        for sq in 0..64i32 {
            let i = sq as usize;
            if let Some(n) = try_step(sq, -1, 1) {
                pawn[0][i] |= 1u64 << n;
            }
            if let Some(n) = try_step(sq, 1, 1) {
                pawn[0][i] |= 1u64 << n;
            }
            if let Some(n) = try_step(sq, -1, -1) {
                pawn[1][i] |= 1u64 << n;
            }
            if let Some(n) = try_step(sq, 1, -1) {
                pawn[1][i] |= 1u64 << n;
            }
            for &(df, dr) in &KNIGHT_D {
                if let Some(n) = try_step(sq, df, dr) {
                    knight[i] |= 1u64 << n;
                }
            }
            for &(df, dr) in &KING_D {
                if let Some(n) = try_step(sq, df, dr) {
                    king[i] |= 1u64 << n;
                }
            }
            for dir in 0..8 {
                rays[dir][i] = walk_ray(sq, RAY_D[dir].0, RAY_D[dir].1);
            }
            bishop_rays[i] = rays[NE][i] | rays[NW][i] | rays[SE][i] | rays[SW][i];
            rook_rays[i] = rays[NORTH][i] | rays[SOUTH][i] | rays[EAST][i] | rays[WEST][i];

            let file = sq % 8;
            let rank = sq / 8;
            for r in (rank + 1)..8 {
                forward_file[0][i] |= 1u64 << (r * 8 + file);
            }
            for r in 0..rank {
                forward_file[1][i] |= 1u64 << (r * 8 + file);
            }
            let mut span = 0u64;
            for f in (file - 1).max(0)..=(file + 1).min(7) {
                for r in (rank + 1)..8 {
                    span |= 1u64 << (r * 8 + f);
                }
            }
            passed[0][i] = span;
            span = 0;
            for f in (file - 1).max(0)..=(file + 1).min(7) {
                for r in 0..rank {
                    span |= 1u64 << (r * 8 + f);
                }
            }
            passed[1][i] = span;
        }

        AttackTables {
            pawn,
            knight,
            king,
            rays,
            bishop_rays,
            rook_rays,
            forward_file,
            passed,
        }
    }
}

#[inline]
fn positive_ray(ray: u64, beyond: &[u64; 64], occ: u64) -> u64 {
    let blockers = ray & occ;
    if blockers == 0 {
        ray
    } else {
        ray ^ beyond[blockers.trailing_zeros() as usize]
    }
}

#[inline]
fn negative_ray(ray: u64, beyond: &[u64; 64], occ: u64) -> u64 {
    let blockers = ray & occ;
    if blockers == 0 {
        ray
    } else {
        ray ^ beyond[63 - blockers.leading_zeros() as usize]
    }
}

#[inline]
pub fn bishop_attacks(sq: Square, occ: u64) -> u64 {
    let t = tables();
    let i = sq.index();
    positive_ray(t.rays[NE][i], &t.rays[NE], occ)
        | positive_ray(t.rays[NW][i], &t.rays[NW], occ)
        | negative_ray(t.rays[SE][i], &t.rays[SE], occ)
        | negative_ray(t.rays[SW][i], &t.rays[SW], occ)
}

#[inline]
pub fn rook_attacks(sq: Square, occ: u64) -> u64 {
    let t = tables();
    let i = sq.index();
    positive_ray(t.rays[NORTH][i], &t.rays[NORTH], occ)
        | positive_ray(t.rays[EAST][i], &t.rays[EAST], occ)
        | negative_ray(t.rays[SOUTH][i], &t.rays[SOUTH], occ)
        | negative_ray(t.rays[WEST][i], &t.rays[WEST], occ)
}

#[inline]
pub fn queen_attacks(sq: Square, occ: u64) -> u64 {
    bishop_attacks(sq, occ) | rook_attacks(sq, occ)
}

#[inline]
pub fn pawn_attacks(color: Color, sq: Square) -> u64 {
    tables().pawn[color.index()][sq.index()]
}

#[inline]
pub fn knight_attacks(sq: Square) -> u64 {
    tables().knight[sq.index()]
}

#[inline]
pub fn king_attacks(sq: Square) -> u64 {
    tables().king[sq.index()]
}

#[inline]
pub fn pawn_attacks_bb(color: Color, pawns: u64) -> u64 {
    let bb = Bitboard(pawns);
    if color == Color::White {
        (bb.nw() | bb.ne()).0
    } else {
        (bb.sw() | bb.se()).0
    }
}
