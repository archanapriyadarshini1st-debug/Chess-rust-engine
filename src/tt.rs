//! Lockless transposition table (XOR-key verification, Stockfish-style).
//! Shared by Lazy SMP threads without a mutex.

use crate::types::{Move, INF};
use std::sync::atomic::{AtomicU64, Ordering};

pub const BOUND_NONE: u8 = 0;
pub const BOUND_LOWER: u8 = 1; // fail-high / beta
pub const BOUND_UPPER: u8 = 2; // fail-low / alpha
pub const BOUND_EXACT: u8 = 3;

const PACK_MOVE: u64 = 0xFFFF;
const PACK_DEPTH: u64 = 0xFF;
const PACK_BOUND: u64 = 0x3;
const PACK_AGE: u64 = 0x3F;

/// data layout: move 16 | score 16 | depth 8 | bound 2 | age 6 | unused 16
#[inline]
fn pack(mv: Move, score: i32, depth: i32, bound: u8, age: u8) -> u64 {
    let s = (score as i16) as u16 as u64;
    (mv.0 as u64)
        | (s << 16)
        | ((depth.clamp(0, 255) as u64) << 32)
        | ((bound as u64) << 40)
        | ((age as u64) << 42)
}

#[inline]
fn unpack(data: u64) -> (Move, i32, i32, u8, u8) {
    let mv = Move((data & PACK_MOVE) as u16);
    let score = ((data >> 16) as u16) as i16 as i32;
    let depth = ((data >> 32) & PACK_DEPTH) as i32;
    let bound = ((data >> 40) & PACK_BOUND) as u8;
    let age = ((data >> 42) & PACK_AGE) as u8;
    (mv, score, depth, bound, age)
}

struct Entry {
    key: AtomicU64,
    data: AtomicU64,
}

impl Entry {
    fn empty() -> Entry {
        Entry {
            key: AtomicU64::new(0),
            data: AtomicU64::new(0),
        }
    }
}

const BUCKET: usize = 4;

/// Four 16-byte entries = one 64-byte cache line, so a probe or store touches
/// exactly one line and a deep entry survives a burst of shallow stores.
#[repr(align(64))]
struct Bucket {
    e: [Entry; BUCKET],
}

pub struct TranspositionTable {
    table: Vec<Bucket>,
    mask: u64,
    age: std::sync::atomic::AtomicU8,
}

impl TranspositionTable {
    pub fn new(mb: usize) -> TranspositionTable {
        let bytes = mb.max(1) * 1024 * 1024;
        let bsize = std::mem::size_of::<Bucket>();
        let mut n = 1usize;
        while n * 2 * bsize <= bytes {
            n *= 2;
        }
        n = n.max(256);
        let mut table = Vec::with_capacity(n);
        for _ in 0..n {
            table.push(Bucket {
                e: [Entry::empty(), Entry::empty(), Entry::empty(), Entry::empty()],
            });
        }
        TranspositionTable {
            table,
            mask: (n - 1) as u64,
            age: std::sync::atomic::AtomicU8::new(1),
        }
    }

    pub fn resize(&mut self, mb: usize) {
        *self = TranspositionTable::new(mb);
    }

    pub fn clear(&self) {
        for b in &self.table {
            for e in &b.e {
                e.key.store(0, Ordering::Relaxed);
                e.data.store(0, Ordering::Relaxed);
            }
        }
    }

    pub fn new_search(&self) {
        // Age lives in 6 bits of the packed entry; keep the counter in the same
        // range, otherwise `old_age != age` is true for every entry once the
        // counter passes 63 (i.e. after ~63 searches of a game) and the
        // depth-preferred check is silently disabled.
        let a = self.age.load(Ordering::Relaxed);
        self.age.store((a + 1) & (PACK_AGE as u8), Ordering::Relaxed);
    }

    #[inline]
    fn idx(&self, hash: u64) -> usize {
        (hash & self.mask) as usize
    }

    /// Hint the CPU to pull this hash's bucket into cache. Called right after a
    /// move is made so the DRAM latency overlaps with the child node's setup
    /// (a pure performance hint: it never changes search results).
    #[inline(always)]
    pub fn prefetch(&self, hash: u64) {
        #[cfg(target_arch = "x86_64")]
        unsafe {
            use std::arch::x86_64::{_mm_prefetch, _MM_HINT_T0};
            let p = self.table.as_ptr().add(self.idx(hash)) as *const i8;
            _mm_prefetch(p, _MM_HINT_T0);
        }
        #[cfg(not(target_arch = "x86_64"))]
        let _ = hash;
    }

    pub fn probe(&self, hash: u64) -> Option<(Move, i32, i32, u8)> {
        let b = &self.table[self.idx(hash)];
        for e in &b.e {
            let key = e.key.load(Ordering::Relaxed);
            let data = e.data.load(Ordering::Relaxed);
            if key ^ data == hash {
                let (mv, score, depth, bound, _) = unpack(data);
                return Some((mv, score, depth, bound));
            }
        }
        None
    }

    pub fn store(&self, hash: u64, mv: Move, mut score: i32, depth: i32, bound: u8) {
        score = score.clamp(-INF + 1, INF - 1);
        let b = &self.table[self.idx(hash)];
        let age = self.age.load(Ordering::Relaxed);

        // 1) same position already in the bucket -> update in place.
        // 2) otherwise evict the entry with the lowest depth-minus-staleness.
        let mut victim = &b.e[0];
        let mut victim_val = i32::MAX;
        for e in &b.e {
            let old_data = e.data.load(Ordering::Relaxed);
            let old_key = e.key.load(Ordering::Relaxed);
            let (old_mv, _, old_depth, _, old_age) = unpack(old_data);
            if old_key ^ old_data == hash {
                if depth + 2 >= old_depth || old_age != age {
                    // Keep the previous best move when this store has none
                    // (fail-low node or quiescence store).
                    let mv = if mv.is_none() { old_mv } else { mv };
                    let data = pack(mv, score, depth, bound, age);
                    e.data.store(data, Ordering::Relaxed);
                    e.key.store(hash ^ data, Ordering::Relaxed);
                }
                return;
            }
            let rel_age = (age.wrapping_sub(old_age) & PACK_AGE as u8) as i32;
            let val = old_depth - 2 * rel_age;
            if val < victim_val {
                victim_val = val;
                victim = e;
            }
        }
        let data = pack(mv, score, depth, bound, age);
        victim.data.store(data, Ordering::Relaxed);
        victim.key.store(hash ^ data, Ordering::Relaxed);
    }
}

/// Adjust mate scores so they stay relative to the root when stored in the TT.
pub fn to_tt(score: i32, ply: i32) -> i32 {
    if score >= crate::types::MATE_IN_MAX {
        score + ply
    } else if score <= -crate::types::MATE_IN_MAX {
        score - ply
    } else {
        score
    }
}

pub fn from_tt(score: i32, ply: i32) -> i32 {
    if score >= crate::types::MATE_IN_MAX {
        score - ply
    } else if score <= -crate::types::MATE_IN_MAX {
        score + ply
    } else {
        score
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn table_uses_the_full_hash_budget() {
        for mb in [1usize, 16, 64] {
            let t = TranspositionTable::new(mb);
            let bytes = t.table.len() * std::mem::size_of::<Bucket>();
            let budget = mb * 1024 * 1024;
            assert!(bytes <= budget, "{mb} MB: table {bytes} exceeds budget");
            assert!(bytes * 2 > budget, "{mb} MB: table {bytes} wastes more than half");
        }
    }

    #[test]
    fn same_position_store_without_move_keeps_old_move() {
        let t = TranspositionTable::new(1);
        let h = 0xDEAD_BEEF_1234_5678u64;
        let mv = Move(0x1234);
        t.store(h, mv, 50, 6, BOUND_LOWER);
        // fail-low / qsearch style store: no move
        t.store(h, Move::NONE, -20, 7, BOUND_UPPER);
        let (m, s, d, b) = t.probe(h).unwrap();
        assert_eq!(m, mv);
        assert_eq!((s, d, b), (-20, 7, BOUND_UPPER));
    }

    #[test]
    fn different_position_does_not_inherit_move() {
        let t = TranspositionTable::new(1);
        let h1 = 0x1111u64;
        let h2 = h1 + (t.mask + 1); // same slot, different key
        t.store(h1, Move(0x4321), 10, 5, BOUND_EXACT);
        t.store(h2, Move::NONE, 0, 1, BOUND_UPPER);
        let (m, ..) = t.probe(h2).unwrap();
        assert!(m.is_none());
    }

    #[test]
    fn age_never_leaves_its_six_bit_field() {
        let t = TranspositionTable::new(1);
        let h = 0xABCDEFu64;
        t.store(h, Move(7), 1, 20, BOUND_EXACT);
        for _ in 0..300 {
            t.new_search();
            assert!(t.age.load(Ordering::Relaxed) as u64 <= PACK_AGE);
        }
        // An entry stored this search with a much shallower depth must not
        // evict a same-age deeper entry of the same position.
        t.store(h, Move(9), 2, 20, BOUND_EXACT);
        t.store(h, Move::NONE, 3, 2, BOUND_UPPER);
        let (m, _, d, _) = t.probe(h).unwrap();
        assert_eq!(d, 20);
        assert_eq!(m, Move(9));
    }

    #[test]
    fn deep_entry_survives_shallow_burst_in_same_bucket() {
        let t = TranspositionTable::new(1);
        let base = 0x77u64;
        let step = t.mask + 1; // same bucket, different key
        t.store(base, Move(0x55), 100, 18, BOUND_EXACT);
        for k in 1..=3 {
            t.store(base + k * step, Move::NONE, 0, 0, BOUND_UPPER);
        }
        let (m, _, d, _) = t.probe(base).expect("deep entry evicted by shallow burst");
        assert_eq!((m, d), (Move(0x55), 18));
    }

    #[test]
    fn stale_entry_is_evicted_first() {
        let t = TranspositionTable::new(1);
        let base = 0x99u64;
        let step = t.mask + 1;
        t.store(base, Move(1), 5, 30, BOUND_EXACT); // deep but about to go stale
        for _ in 0..40 {
            t.new_search();
        }
        for k in 1..=4 {
            t.store(base + k * step, Move(2), 1, 3, BOUND_EXACT);
        }
        // 4 fresh entries into a 4-way bucket: the stale deep one must be the casualty.
        assert!(t.probe(base).is_none());
        for k in 1..=4 {
            assert!(t.probe(base + k * step).is_some());
        }
    }
}
