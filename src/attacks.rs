//! Attack tables: leapers precomputed, sliders via fancy magic bitboards.
//! Magics are found once at startup; rays are only used to build the tables.

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

#[derive(Clone, Copy)]
struct Magic {
    mask: u64,
    magic: u64,
    shift: u32,
    offset: u32,
}

pub struct AttackTables {
    pub pawn: [[u64; 64]; 2],
    pub knight: [u64; 64],
    pub king: [u64; 64],
    #[allow(dead_code)]
    rays: [[u64; 64]; 8],
    pub bishop_rays: [u64; 64],
    pub rook_rays: [u64; 64],
    /// Squares strictly in front of `sq` for `color` on the same file.
    pub forward_file: [[u64; 64]; 2],
    /// Passed-pawn span: front file + adjacent files, in front of the pawn.
    pub passed: [[u64; 64]; 2],
    bishop_magic: [Magic; 64],
    rook_magic: [Magic; 64],
    slider: Vec<u64>,
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

        let mut slider = Vec::new();
        let mut bishop_magic = [Magic {
            mask: 0,
            magic: 0,
            shift: 0,
            offset: 0,
        }; 64];
        let mut rook_magic = bishop_magic;
        fill_magics(
            &rays,
            false,
            &mut bishop_magic,
            &mut slider,
        );
        fill_magics(&rays, true, &mut rook_magic, &mut slider);

        AttackTables {
            pawn,
            knight,
            king,
            rays,
            bishop_rays,
            rook_rays,
            forward_file,
            passed,
            bishop_magic,
            rook_magic,
            slider,
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

fn slow_bishop(rays: &[[u64; 64]; 8], sq: usize, occ: u64) -> u64 {
    positive_ray(rays[NE][sq], &rays[NE], occ)
        | positive_ray(rays[NW][sq], &rays[NW], occ)
        | negative_ray(rays[SE][sq], &rays[SE], occ)
        | negative_ray(rays[SW][sq], &rays[SW], occ)
}

fn slow_rook(rays: &[[u64; 64]; 8], sq: usize, occ: u64) -> u64 {
    positive_ray(rays[NORTH][sq], &rays[NORTH], occ)
        | positive_ray(rays[EAST][sq], &rays[EAST], occ)
        | negative_ray(rays[SOUTH][sq], &rays[SOUTH], occ)
        | negative_ray(rays[WEST][sq], &rays[WEST], occ)
}

fn rook_relevant(sq: usize) -> u64 {
    let r = sq / 8;
    let f = sq % 8;
    let mut m = 0u64;
    for rf in (f + 1)..7 {
        m |= 1u64 << (r * 8 + rf);
    }
    for rf in 1..f {
        m |= 1u64 << (r * 8 + rf);
    }
    for rr in (r + 1)..7 {
        m |= 1u64 << (rr * 8 + f);
    }
    for rr in 1..r {
        m |= 1u64 << (rr * 8 + f);
    }
    m
}

fn bishop_relevant(sq: usize) -> u64 {
    let r = sq / 8;
    let f = sq % 8;
    let mut m = 0u64;
    let mut rr = r + 1;
    let mut ff = f + 1;
    while rr < 7 && ff < 7 {
        m |= 1u64 << (rr * 8 + ff);
        rr += 1;
        ff += 1;
    }
    rr = r + 1;
    ff = f.wrapping_sub(1);
    while rr < 7 && ff >= 1 && ff < 8 {
        m |= 1u64 << (rr * 8 + ff);
        rr += 1;
        ff -= 1;
    }
    rr = r.wrapping_sub(1);
    ff = f + 1;
    while rr >= 1 && rr < 8 && ff < 7 {
        m |= 1u64 << (rr * 8 + ff);
        rr -= 1;
        ff += 1;
    }
    rr = r.wrapping_sub(1);
    ff = f.wrapping_sub(1);
    while rr >= 1 && rr < 8 && ff >= 1 && ff < 8 {
        m |= 1u64 << (rr * 8 + ff);
        rr -= 1;
        ff -= 1;
    }
    m
}

fn occupancy_from_index(index: usize, mask: u64) -> u64 {
    let mut occ = 0u64;
    let mut bits = mask;
    let mut i = 0;
    while bits != 0 {
        let sq = bits.trailing_zeros();
        bits &= bits - 1;
        if index & (1 << i) != 0 {
            occ |= 1u64 << sq;
        }
        i += 1;
    }
    occ
}

fn fill_magics(rays: &[[u64; 64]; 8], rook: bool, out: &mut [Magic; 64], table: &mut Vec<u64>) {
    let mut rng: u64 = if rook {
        0xC0FF_EE12_3456_789A
    } else {
        0xDEAD_BEEF_CAFE_BABE
    };
    let next = |rng: &mut u64| -> u64 {
        *rng ^= *rng << 13;
        *rng ^= *rng >> 7;
        *rng ^= *rng << 17;
        *rng
    };
    for sq in 0..64 {
        let mask = if rook {
            rook_relevant(sq)
        } else {
            bishop_relevant(sq)
        };
        let bits = mask.count_ones();
        let size = 1usize << bits;
        let mut occupancies = vec![0u64; size];
        let mut attacks = vec![0u64; size];
        for i in 0..size {
            occupancies[i] = occupancy_from_index(i, mask);
            attacks[i] = if rook {
                slow_rook(rays, sq, occupancies[i])
            } else {
                slow_bishop(rays, sq, occupancies[i])
            };
        }
        let shift = 64 - bits;
        let offset = table.len() as u32;
        let mut used = vec![0u64; size];
        let mut magic = 0u64;
        'find: for _ in 0..100_000_000u32 {
            let a = next(&mut rng) & next(&mut rng) & next(&mut rng);
            if ((a.wrapping_mul(mask)) >> 56).count_ones() < 6 {
                continue;
            }
            used.fill(0);
            let mut ok = true;
            for i in 0..size {
                let idx = ((occupancies[i].wrapping_mul(a)) >> shift) as usize;
                if used[idx] == 0 {
                    used[idx] = attacks[i];
                } else if used[idx] != attacks[i] {
                    ok = false;
                    break;
                }
            }
            if ok {
                magic = a;
                break 'find;
            }
        }
        if magic == 0 {
            panic!("magic not found sq={} rook={}", sq, rook);
        }
        table.resize(table.len() + size, 0);
        for i in 0..size {
            let idx = ((occupancies[i].wrapping_mul(magic)) >> shift) as usize;
            table[offset as usize + idx] = attacks[i];
        }
        out[sq] = Magic {
            mask,
            magic,
            shift,
            offset,
        };
    }
}

#[inline]
fn magic_attacks(sq: Square, occ: u64, magics: &[Magic; 64], table: &[u64]) -> u64 {
    let m = magics[sq.index()];
    let idx = ((occ & m.mask).wrapping_mul(m.magic) >> m.shift) as usize;
    table[m.offset as usize + idx]
}

#[inline]
pub fn bishop_attacks(sq: Square, occ: u64) -> u64 {
    let t = tables();
    magic_attacks(sq, occ, &t.bishop_magic, &t.slider)
}

#[inline]
pub fn rook_attacks(sq: Square, occ: u64) -> u64 {
    let t = tables();
    magic_attacks(sq, occ, &t.rook_magic, &t.slider)
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
