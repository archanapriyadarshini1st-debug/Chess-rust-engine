//! Deterministic Zobrist keys generated with SplitMix64 from a fixed seed.

use crate::types::Square;

pub struct Zobrist {
    pub piece: [[u64; 64]; 12],
    pub castle: [u64; 16],
    pub ep: [u64; 8],
    pub side: u64,
}

pub static ZOBRIST: Zobrist = Zobrist::new();

const fn splitmix(mut x: u64) -> (u64, u64) {
    x = x.wrapping_add(0x9E37_79B9_7F4A_7C15);
    let mut z = x;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^= z >> 31;
    (x, z)
}

impl Zobrist {
    const fn new() -> Zobrist {
        let mut state = 0xC0FF_EE12_3456_789A;
        let mut piece = [[0u64; 64]; 12];
        let mut p = 0;
        while p < 12 {
            let mut sq = 0;
            while sq < 64 {
                let (s, z) = splitmix(state);
                state = s;
                piece[p][sq] = z;
                sq += 1;
            }
            p += 1;
        }
        let mut castle = [0u64; 16];
        let mut i = 0;
        while i < 16 {
            let (s, z) = splitmix(state);
            state = s;
            castle[i] = z;
            i += 1;
        }
        let mut ep = [0u64; 8];
        i = 0;
        while i < 8 {
            let (s, z) = splitmix(state);
            state = s;
            ep[i] = z;
            i += 1;
        }
        let (s, side) = splitmix(state);
        let _ = s;
        Zobrist {
            piece,
            castle,
            ep,
            side,
        }
    }

    #[inline]
    pub const fn piece_key(&self, piece_idx: usize, sq: Square) -> u64 {
        self.piece[piece_idx][sq.index()]
    }
}
