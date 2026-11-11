//! Multithreaded sparse trainer for the CRN1 net `(768 -> 128) x2 -> 1`, SCReLU, 8 material
//! buckets (Agent NT, EXP-NT1).
//!
//! Drop-in sibling of `tools/nnue/train.py`: same 28-byte records, same loss
//! (MSE in sigmoid space against `lam*sigmoid(cp/400) + (1-lam)*wdl/2`), same Adam, same
//! `hash % val_mod` position-disjoint validation split, same dedupe, same best-validation
//! rollback, same `CRN1` output. The difference is speed: the first layer is a sparse
//! gather/scatter over <= 32 active rows instead of a dense matmul, samples are decoded on
//! the fly from the packed records, and the batch is split over `std::thread`s.
//!
//! Stockfish (or Lichess) is only a label source in the data; nothing here embeds a net.
//! Pure std, no dependencies. Deterministic for a fixed `--seed` and `--threads`.
//!
//! usage:
//!   nntrain train --data a.bin,b.bin --out net.bin [--epochs 20 | --minutes 60]
//!                 [--batch 16384] [--lr 2e-3] [--lam 0.75] [--val-mod 50] [--threads N]
//!                 [--seed 1] [--resume net.bin] [--limit N] [--no-dedupe]
//!   nntrain gen --out f.bin --n 1000000 [--seed 1] [--noise 40]   (HCE-labelled playouts, tests only)
//!   nntrain eval --net net.bin --data a.bin [--val-mod 50] [--lam 1.0]   (val loss, float)
//!   nntrain selftest

use chess_rust_engine::board::Position;
use chess_rust_engine::eval::evaluate;
use chess_rust_engine::movegen::legal_moves;
use chess_rust_engine::types::{Move, Square, MAX_MOVES};
use std::io::{Read, Write};
use std::time::Instant;

const H: usize = 128;
const FEATS: usize = 768;
const BUCKETS: usize = 8;
const QA: f32 = 255.0;
const QB: f32 = 64.0;
const SCALE: f32 = 400.0;
const REC: usize = 28;
const CLIP: f32 = 1.98;

type Rec = [u8; REC];

// ------------------------------------------------------------------ rng
struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E3779B97F4A7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        z ^ (z >> 31)
    }
    fn f32(&mut self) -> f32 {
        ((self.next() >> 40) as f32 + 0.5) / 16777216.0
    }
    fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }
    fn normal(&mut self) -> f32 {
        let (a, b) = (self.f32(), self.f32());
        (-2.0 * a.ln()).sqrt() * (2.0 * std::f32::consts::PI * b).cos()
    }
}

// ------------------------------------------------------------------ records
/// Identical to `pos_hash` in tools/nnue/train.py (so splits agree across both trainers).
fn pos_hash(r: &Rec) -> u64 {
    let u = |o: usize| u64::from_le_bytes(r[o..o + 8].try_into().unwrap());
    let (occ, p0, p1) = (u(0), u(8), u(16));
    let stm = r[24] as u64;
    let mut h = occ.wrapping_mul(0x9E3779B97F4A7C15);
    h ^= p0.wrapping_mul(0xC2B2AE3D27D4EB4F);
    h ^= p1.wrapping_mul(0x165667B19E3779F9);
    h ^= stm.wrapping_mul(0x27D4EB2F165667C5);
    h ^= h >> 31;
    h = h.wrapping_mul(0xBF58476D1CE4E5B9);
    h ^= h >> 29;
    h
}

struct Sample {
    fu: [u16; 32],
    ft: [u16; 32],
    n: usize,
    bucket: usize,
    score: f32,
    wdl: f32,
}

/// Same indexing as `decode()` in train.py / the engine's nnue.rs.
#[inline]
fn decode(r: &Rec) -> Sample {
    let occ = u64::from_le_bytes(r[0..8].try_into().unwrap());
    let stm = (r[24] & 1) as usize;
    let them = 1 - stm;
    let cnt = occ.count_ones() as usize;
    let mut s = Sample {
        fu: [0; 32],
        ft: [0; 32],
        n: cnt.min(32),
        bucket: (cnt.saturating_sub(2) / 4).min(BUCKETS - 1),
        score: i16::from_le_bytes([r[25], r[26]]) as f32,
        wdl: r[27] as f32 / 2.0,
    };
    let mut bb = occ;
    let mut k = 0;
    while bb != 0 && k < 32 {
        let sq = bb.trailing_zeros() as usize;
        bb &= bb - 1;
        let byte = r[8 + k / 2];
        let p = if k % 2 == 0 { byte & 15 } else { byte >> 4 } as usize;
        let (c, t) = (p / 6, p % 6);
        s.fu[k] = ((((c != stm) as usize) * 6 + t) * 64 + (sq ^ (56 * stm))) as u16;
        s.ft[k] = ((((c != them) as usize) * 6 + t) * 64 + (sq ^ (56 * them))) as u16;
        k += 1;
    }
    s
}

/// `*` wildcard match on one path component (enough for `data/*.bin`, like train.py's glob).
fn wild(pat: &[u8], s: &[u8]) -> bool {
    match pat.split_first() {
        None => s.is_empty(),
        Some((b'*', rest)) => (0..=s.len()).any(|i| wild(rest, &s[i..])),
        Some((c, rest)) => s.first() == Some(c) && wild(rest, &s[1..]),
    }
}

fn expand(g: &str) -> Vec<String> {
    if !g.contains('*') {
        return vec![g.to_string()];
    }
    let (dir, pat) = match g.rfind('/') {
        Some(i) => (&g[..i], &g[i + 1..]),
        None => (".", g),
    };
    let mut v: Vec<String> = std::fs::read_dir(dir)
        .map(|rd| {
            rd.filter_map(|e| e.ok())
                .filter(|e| wild(pat.as_bytes(), e.file_name().to_string_lossy().as_bytes()))
                .map(|e| e.path().to_string_lossy().to_string())
                .collect()
        })
        .unwrap_or_default();
    v.sort();
    v
}

fn load_records(spec: &str, limit: usize) -> (Vec<String>, Vec<Rec>) {
    let mut files: Vec<String> = Vec::new();
    for g in spec.split(',') {
        let g = g.trim();
        if !g.is_empty() {
            files.extend(expand(g));
        }
    }
    assert!(!files.is_empty(), "no data files match {spec:?}");
    files.sort();
    files.dedup();
    let mut out: Vec<Rec> = Vec::new();
    for f in &files {
        let mut fh = std::fs::File::open(f).unwrap_or_else(|e| panic!("open {f}: {e}"));
        let len = fh.metadata().unwrap().len() as usize;
        assert!(len % REC == 0, "{f}: size {len} is not a multiple of {REC}");
        out.reserve(len / REC);
        let mut buf = vec![0u8; REC * 65536];
        loop {
            let mut got = 0;
            while got < buf.len() {
                let n = fh.read(&mut buf[got..]).unwrap();
                if n == 0 {
                    break;
                }
                got += n;
            }
            if got == 0 {
                break;
            }
            for c in buf[..got].chunks_exact(REC) {
                out.push(c.try_into().unwrap());
            }
            if got < buf.len() {
                break;
            }
        }
        if limit > 0 && out.len() >= limit {
            out.truncate(limit);
            break;
        }
    }
    (files, out)
}

// ------------------------------------------------------------------ net
#[derive(Clone)]
struct Net {
    ft: Vec<f32>,   // [FEATS][H]
    ft_b: Vec<f32>, // [H]
    out_w: Vec<f32>, // [BUCKETS][2H]
    out_b: Vec<f32>, // [BUCKETS]
}

impl Net {
    fn zeros() -> Net {
        Net { ft: vec![0.0; FEATS * H], ft_b: vec![0.0; H], out_w: vec![0.0; BUCKETS * 2 * H], out_b: vec![0.0; BUCKETS] }
    }
    fn random(seed: u64) -> Net {
        let mut r = Rng(seed ^ 0xC0FFEE);
        let mut n = Net::zeros();
        for w in n.ft.iter_mut() {
            *w = r.normal() * 0.08;
        }
        for w in n.out_w.iter_mut() {
            *w = r.normal() * 0.05;
        }
        n
    }
    fn clip(&mut self) {
        for v in [&mut self.ft, &mut self.ft_b, &mut self.out_w] {
            for w in v.iter_mut() {
                *w = w.clamp(-CLIP, CLIP);
            }
        }
    }
    fn export(&self, path: &str) {
        let q = |x: f32, s: f32| (x * s).round_ties_even().clamp(-32767.0, 32767.0) as i16;
        let mut b: Vec<u8> = Vec::new();
        b.extend_from_slice(b"CRN1");
        for v in [1u32, H as u32, BUCKETS as u32, FEATS as u32] {
            b.extend_from_slice(&v.to_le_bytes());
        }
        for &w in &self.ft {
            b.extend_from_slice(&q(w, QA).to_le_bytes());
        }
        for &w in &self.ft_b {
            b.extend_from_slice(&q(w, QA).to_le_bytes());
        }
        for &w in &self.out_w {
            b.extend_from_slice(&q(w, QB).to_le_bytes());
        }
        for &w in &self.out_b {
            b.extend_from_slice(&((w * QA * QB).round_ties_even() as i32).to_le_bytes());
        }
        std::fs::write(path, &b).unwrap();
        println!("exported {path} ({} bytes)", b.len());
    }
    /// The net exactly as the engine will see it (i16/i32 round trip, no file).
    fn quantized(&self) -> Net {
        let q = |x: f32, sc: f32| (x * sc).round_ties_even().clamp(-32767.0, 32767.0) / sc;
        let mut n = self.clone();
        n.ft.iter_mut().for_each(|w| *w = q(*w, QA));
        n.ft_b.iter_mut().for_each(|w| *w = q(*w, QA));
        n.out_w.iter_mut().for_each(|w| *w = q(*w, QB));
        n.out_b.iter_mut().for_each(|w| *w = (*w * QA * QB).round_ties_even() / (QA * QB));
        n
    }
    fn load(path: &str) -> Net {
        let raw = std::fs::read(path).unwrap_or_else(|e| panic!("read {path}: {e}"));
        assert!(&raw[..4] == b"CRN1", "not a CRN1 net");
        let u = |o: usize| u32::from_le_bytes(raw[o..o + 4].try_into().unwrap()) as usize;
        assert_eq!((u(8), u(12), u(16)), (H, BUCKETS, FEATS), "net shape does not match this trainer");
        let mut o = 20;
        let mut n = Net::zeros();
        let rd16 = |dst: &mut Vec<f32>, scale: f32, o: &mut usize| {
            for w in dst.iter_mut() {
                *w = i16::from_le_bytes([raw[*o], raw[*o + 1]]) as f32 / scale;
                *o += 2;
            }
        };
        rd16(&mut n.ft, QA, &mut o);
        rd16(&mut n.ft_b, QA, &mut o);
        rd16(&mut n.out_w, QB, &mut o);
        for w in n.out_b.iter_mut() {
            *w = i32::from_le_bytes(raw[o..o + 4].try_into().unwrap()) as f32 / (QA * QB);
            o += 4;
        }
        assert_eq!(o, raw.len(), "trailing bytes in net file");
        n
    }
}

struct Grad {
    ft: Vec<f32>,
    ft_b: Vec<f32>,
    out_w: Vec<f32>,
    out_b: Vec<f32>,
    loss: f64,
}
impl Grad {
    fn new() -> Grad {
        Grad { ft: vec![0.0; FEATS * H], ft_b: vec![0.0; H], out_w: vec![0.0; BUCKETS * 2 * H], out_b: vec![0.0; BUCKETS], loss: 0.0 }
    }
    fn zero(&mut self) {
        for v in [&mut self.ft, &mut self.ft_b, &mut self.out_w, &mut self.out_b] {
            v.iter_mut().for_each(|x| *x = 0.0);
        }
        self.loss = 0.0;
    }
}

#[inline]
fn sigmoid(x: f32) -> f32 {
    1.0 / (1.0 + (-x).exp())
}

#[inline]
fn accumulate(net: &Net, feats: &[u16], n: usize) -> [f32; H] {
    let mut a = [0f32; H];
    a.copy_from_slice(&net.ft_b);
    for &f in &feats[..n] {
        let row = &net.ft[f as usize * H..f as usize * H + H];
        for j in 0..H {
            a[j] += row[j];
        }
    }
    a
}

#[inline]
fn target(s: &Sample, lam: f32) -> f32 {
    lam * sigmoid(s.score / SCALE) + (1.0 - lam) * s.wdl
}

/// Forward only: returns the raw output `o` (sigmoid space logit).
#[inline]
fn forward(net: &Net, s: &Sample) -> f32 {
    let au = accumulate(net, &s.fu, s.n);
    let at = accumulate(net, &s.ft, s.n);
    let w = &net.out_w[s.bucket * 2 * H..(s.bucket + 1) * 2 * H];
    let mut o = net.out_b[s.bucket];
    for j in 0..H {
        let c = au[j].clamp(0.0, 1.0);
        let d = at[j].clamp(0.0, 1.0);
        o += c * c * w[j] + d * d * w[H + j];
    }
    o
}

/// Forward + backward for one sample; gradient is scaled by `inv_b` (mean over the batch).
#[inline]
fn fwd_bwd(net: &Net, g: &mut Grad, s: &Sample, lam: f32, inv_b: f32) {
    let au = accumulate(net, &s.fu, s.n);
    let at = accumulate(net, &s.ft, s.n);
    let wb = s.bucket * 2 * H;
    let w = &net.out_w[wb..wb + 2 * H];
    let mut o = net.out_b[s.bucket];
    for j in 0..H {
        let c = au[j].clamp(0.0, 1.0);
        let d = at[j].clamp(0.0, 1.0);
        o += c * c * w[j] + d * d * w[H + j];
    }
    let p = sigmoid(o);
    let err = p - target(s, lam);
    g.loss += (err * err) as f64;
    let d_o = 2.0 * err * p * (1.0 - p) * inv_b;
    g.out_b[s.bucket] += d_o;
    let mut dau = [0f32; H];
    let mut dat = [0f32; H];
    {
        let gw = &mut g.out_w[wb..wb + 2 * H];
        for j in 0..H {
            let c = au[j].clamp(0.0, 1.0);
            let d = at[j].clamp(0.0, 1.0);
            gw[j] += d_o * c * c;
            gw[H + j] += d_o * d * d;
            dau[j] = if au[j] >= 0.0 && au[j] <= 1.0 { d_o * w[j] * 2.0 * c } else { 0.0 };
            dat[j] = if at[j] >= 0.0 && at[j] <= 1.0 { d_o * w[H + j] * 2.0 * d } else { 0.0 };
        }
    }
    for j in 0..H {
        g.ft_b[j] += dau[j] + dat[j];
    }
    for &f in &s.fu[..s.n] {
        let row = &mut g.ft[f as usize * H..f as usize * H + H];
        for j in 0..H {
            row[j] += dau[j];
        }
    }
    for &f in &s.ft[..s.n] {
        let row = &mut g.ft[f as usize * H..f as usize * H + H];
        for j in 0..H {
            row[j] += dat[j];
        }
    }
}

// ------------------------------------------------------------------ adam
struct Adam {
    m: Net,
    v: Net,
    t: i32,
}
impl Adam {
    fn new() -> Adam {
        Adam { m: Net::zeros(), v: Net::zeros(), t: 0 }
    }
    fn step(&mut self, net: &mut Net, g: &Grad, lr: f32) {
        self.t += 1;
        let (b1, b2, eps) = (0.9f32, 0.999f32, 1e-8f32);
        let c1 = 1.0 - b1.powi(self.t);
        let c2 = 1.0 - b2.powi(self.t);
        let step = lr * c2.sqrt() / c1;
        let upd = |w: &mut [f32], m: &mut [f32], v: &mut [f32], g: &[f32]| {
            for i in 0..w.len() {
                m[i] = b1 * m[i] + (1.0 - b1) * g[i];
                v[i] = b2 * v[i] + (1.0 - b2) * g[i] * g[i];
                w[i] -= step * m[i] / (v[i].sqrt() + eps * c2.sqrt());
            }
        };
        upd(&mut net.ft, &mut self.m.ft, &mut self.v.ft, &g.ft);
        upd(&mut net.ft_b, &mut self.m.ft_b, &mut self.v.ft_b, &g.ft_b);
        upd(&mut net.out_w, &mut self.m.out_w, &mut self.v.out_w, &g.out_w);
        upd(&mut net.out_b, &mut self.m.out_b, &mut self.v.out_b, &g.out_b);
        net.clip();
    }
}

fn val_loss(net: &Net, val: &[Rec], lam: f32, threads: usize) -> f64 {
    if val.is_empty() {
        return f64::NAN;
    }
    let chunk = (val.len() + threads - 1) / threads;
    let tot: f64 = std::thread::scope(|sc| {
        let hs: Vec<_> = val
            .chunks(chunk)
            .map(|c| {
                sc.spawn(move || {
                    let mut t = 0f64;
                    for r in c {
                        let s = decode(r);
                        let e = sigmoid(forward(net, &s)) - target(&s, lam);
                        t += (e * e) as f64;
                    }
                    t
                })
            })
            .collect();
        hs.into_iter().map(|h| h.join().unwrap()).sum()
    });
    tot / val.len() as f64
}

// ------------------------------------------------------------------ commands
fn arg<'a>(a: &'a [String], k: &str) -> Option<&'a str> {
    a.iter().position(|x| x == k).and_then(|i| a.get(i + 1)).map(|s| s.as_str())
}
fn argf<T: std::str::FromStr>(a: &[String], k: &str, d: T) -> T {
    arg(a, k).and_then(|s| s.parse().ok()).unwrap_or(d)
}

fn split(recs: Vec<Rec>, dedupe: bool, val_mod: u64) -> (Vec<Rec>, Vec<Rec>, usize) {
    let raw = recs.len();
    let mut keep: Vec<(u64, u32)> = recs.iter().enumerate().map(|(i, r)| (pos_hash(r), i as u32)).collect();
    if dedupe {
        keep.sort_unstable();
        keep.dedup_by_key(|x| x.0); // keeps the lowest index per hash
        keep.sort_unstable_by_key(|x| x.1);
    }
    let (mut tr, mut va) = (Vec::with_capacity(keep.len()), Vec::new());
    for (h, i) in keep {
        if h % val_mod == 0 {
            va.push(recs[i as usize]);
        } else {
            tr.push(recs[i as usize]);
        }
    }
    (tr, va, raw)
}

fn train(a: &[String]) {
    let data = arg(a, "--data").expect("--data");
    let out = arg(a, "--out").unwrap_or("net.bin").to_string();
    let epochs: usize = argf(a, "--epochs", 0);
    let minutes: f64 = argf(a, "--minutes", 0.0);
    let batch: usize = argf(a, "--batch", 16384);
    let lr0: f32 = argf(a, "--lr", 2e-3);
    let lam: f32 = argf(a, "--lam", 0.75);
    let val_mod: u64 = argf(a, "--val-mod", 50);
    let min_lr_frac: f32 = argf(a, "--min-lr-frac", 0.02);
    let threads: usize = argf(a, "--threads", std::thread::available_parallelism().map(|n| n.get()).unwrap_or(2));
    let seed: u64 = argf(a, "--seed", 1);
    let limit: usize = argf(a, "--limit", 0);
    assert!(epochs > 0 || minutes > 0.0, "give --epochs N or --minutes M");

    let t0 = Instant::now();
    let (files, recs) = load_records(data, limit);
    let (mut tr, va, raw) = split(recs, !a.iter().any(|x| x == "--no-dedupe"), val_mod);
    if va.len() < 1000 {
        eprintln!("only {} validation positions; need more data (or lower --val-mod)", va.len());
        std::process::exit(2);
    }
    let mut cnt = [0usize; 3];
    for r in tr.iter().chain(va.iter()) {
        cnt[(r[27] as usize).min(2)] += 1;
    }
    println!(
        "files={} raw={} unique={} (dedupe removed {}) train={} val={} loss/draw/win={}/{}/{} loaded in {:.1}s threads={threads} seed={seed}",
        files.len(), raw, tr.len() + va.len(), raw - tr.len() - va.len(), tr.len(), va.len(), cnt[0], cnt[1], cnt[2], t0.elapsed().as_secs_f64()
    );
    let mut rng = Rng(seed);
    for i in (1..tr.len()).rev() {
        tr.swap(i, rng.below(i + 1));
    }

    let mut net = match arg(a, "--resume") {
        Some(p) => {
            println!("resumed from {p}");
            Net::load(p)
        }
        None => Net::random(seed),
    };
    let mut adam = Adam::new();
    let mut grads: Vec<Grad> = (0..threads).map(|_| Grad::new()).collect();
    let steps_per_epoch = (tr.len() / batch).max(1);
    let total_steps = if epochs > 0 { epochs * steps_per_epoch } else { usize::MAX };
    let budget = minutes * 60.0;
    let mut best_loss = val_loss(&net, &va, lam, threads);
    let mut best = net.clone();
    let mut best_epoch = 0;
    println!("== start val_loss {best_loss:.5} (a resumed net that cannot improve on this is rolled back)");

    let t_start = Instant::now();
    let mut order: Vec<u32> = (0..tr.len() as u32).collect();
    let (mut step, mut epoch, mut seen) = (0usize, 0usize, 0u64);
    'outer: loop {
        for i in (1..order.len()).rev() {
            order.swap(i, rng.below(i + 1));
        }
        let mut run = 0f64;
        for bi in 0..steps_per_epoch {
            let frac = if epochs > 0 { step as f64 / total_steps as f64 } else { t_start.elapsed().as_secs_f64() / budget };
            if frac >= 1.0 {
                break 'outer;
            }
            let lr = lr0 * (0.5 * (1.0 + (std::f64::consts::PI * frac).cos()) as f32 * (1.0 - min_lr_frac) + min_lr_frac);
            let idx = &order[bi * batch..((bi + 1) * batch).min(order.len())];
            let inv_b = 1.0 / idx.len() as f32;
            let chunk = (idx.len() + threads - 1) / threads;
            let (netr, trr) = (&net, &tr);
            std::thread::scope(|sc| {
                for (g, ids) in grads.iter_mut().zip(idx.chunks(chunk)) {
                    sc.spawn(move || {
                        g.zero();
                        for &i in ids {
                            let s = decode(&trr[i as usize]);
                            fwd_bwd(netr, g, &s, lam, inv_b);
                        }
                    });
                }
            });
            let used = idx.chunks(chunk).count();
            let (first, rest) = grads.split_at_mut(1);
            for g in rest.iter().take(used.saturating_sub(1)) {
                for (x, y) in first[0].ft.iter_mut().zip(&g.ft) { *x += y; }
                for (x, y) in first[0].ft_b.iter_mut().zip(&g.ft_b) { *x += y; }
                for (x, y) in first[0].out_w.iter_mut().zip(&g.out_w) { *x += y; }
                for (x, y) in first[0].out_b.iter_mut().zip(&g.out_b) { *x += y; }
                first[0].loss += g.loss;
            }
            adam.step(&mut net, &first[0], lr);
            run += first[0].loss / idx.len() as f64;
            seen += idx.len() as u64;
            step += 1;
            if step % 100 == 0 {
                let el = t_start.elapsed().as_secs_f64();
                println!("ep {epoch} step {step} loss {:.5} lr {lr:.2e} {:.0} pos/s elapsed {:.1}m", run / (bi + 1) as f64, seen as f64 / el, el / 60.0);
            }
        }
        epoch += 1;
        let v = val_loss(&net, &va, lam, threads);
        println!("== epoch {epoch} val_loss {v:.5} best {best_loss:.5} elapsed {:.1}m", t_start.elapsed().as_secs_f64() / 60.0);
        if v < best_loss {
            best_loss = v;
            best = net.clone();
            best_epoch = epoch;
            best.export(&out);
        }
    }
    let v = val_loss(&net, &va, lam, threads);
    println!("== final val_loss {v:.5} best {best_loss:.5} elapsed {:.1}m", t_start.elapsed().as_secs_f64() / 60.0);
    if v < best_loss {
        best_loss = v;
        best = net.clone();
        best_epoch = epoch;
    }
    println!("final val_loss {best_loss:.5} (best, epoch {best_epoch})");
    println!("quantized val_loss {:.6} (float {:.6}) <- what the engine actually evaluates", val_loss(&best.quantized(), &va, lam, threads), best_loss);
    println!("throughput {:.0} pos/s over {} samples in {:.1}s", seen as f64 / t_start.elapsed().as_secs_f64(), seen, t_start.elapsed().as_secs_f64());
    best.export(&out);
}

fn pack(pos: &Position, score: i32) -> Rec {
    let mut r = [0u8; REC];
    let mut occ = 0u64;
    let mut k = 0;
    for sq in 0..64u8 {
        let p = pos.piece_on(Square(sq));
        if p.is_none() {
            continue;
        }
        occ |= 1u64 << sq;
        let v = p.index() as u8;
        r[8 + k / 2] |= if k % 2 == 0 { v } else { v << 4 };
        k += 1;
    }
    r[0..8].copy_from_slice(&occ.to_le_bytes());
    r[24] = pos.side.index() as u8;
    r[25..27].copy_from_slice(&(score.clamp(-1500, 1500) as i16).to_le_bytes());
    r[27] = 1;
    r
}

fn gen(a: &[String]) {
    let out = arg(a, "--out").expect("--out");
    let n: usize = argf(a, "--n", 100000);
    let seed: u64 = argf(a, "--seed", 1);
    let noise: f32 = argf(a, "--noise", 0.0); // gaussian label noise in cp: gives a realistic loss floor
    let mut rng = Rng(seed);
    let mut f = std::io::BufWriter::new(std::fs::File::create(out).unwrap());
    let mut written = 0;
    let _ = chess_rust_engine::attacks::tables();
    while written < n {
        let mut pos = Position::startpos();
        let plies = 10 + rng.below(70);
        for ply in 0..plies {
            let mut mv = [Move::NONE; MAX_MOVES];
            let k = legal_moves(&pos, &mut mv);
            if k == 0 {
                break;
            }
            pos.make(mv[rng.below(k)]);
            if ply >= 8 && !pos.in_check() && rng.below(3) == 0 {
                let s = evaluate(&pos) + (rng.normal() * noise) as i32;
                if s.abs() <= 1500 {
                    f.write_all(&pack(&pos, s)).unwrap();
                    written += 1;
                    if written >= n {
                        break;
                    }
                }
            }
        }
    }
    println!("wrote {written} records -> {out}");
}

fn eval_cmd(a: &[String]) {
    let net = Net::load(arg(a, "--net").expect("--net"));
    let (_, recs) = load_records(arg(a, "--data").expect("--data"), argf(a, "--limit", 0));
    let val_mod: u64 = argf(a, "--val-mod", 50);
    let lam: f32 = argf(a, "--lam", 0.75);
    let (_, va, _) = split(recs, true, val_mod);
    println!("val={} val_loss {:.5}", va.len(), val_loss(&net, &va, lam, 4));
}

/// Finite-difference check of the analytic gradient on a tiny batch (f32, so loose tolerance).
fn selftest() {
    let tmp = std::env::temp_dir().join("nntrain_selftest.bin");
    let p = tmp.to_str().unwrap().to_string();
    gen(&["--out".into(), p.clone(), "--n".into(), "64".into(), "--seed".into(), "7".into()]);
    let (_, recs) = load_records(&p, 0);
    let samples: Vec<Sample> = recs.iter().map(decode).collect();
    let mut net = Net::random(3);
    // scale up so that SCReLU is in its linear region for many units
    for w in net.ft.iter_mut() { *w *= 2.0; }
    let loss_of = |n: &Net| -> f64 {
        samples.iter().map(|s| { let e = sigmoid(forward(n, s)) - target(s, 1.0); (e * e) as f64 }).sum::<f64>() / samples.len() as f64
    };
    let mut g = Grad::new();
    for s in &samples { fwd_bwd(&net, &mut g, s, 1.0, 1.0 / samples.len() as f32); }
    assert!((g.loss / samples.len() as f64 - loss_of(&net)).abs() < 1e-6, "loss mismatch between fwd_bwd and forward");
    let mut rng = Rng(5);
    let mut checked = 0;
    let mut worst = 0f64;
    let mut rels: Vec<f64> = Vec::new();
    for _ in 0..4000 {
        // pick a parameter with a non-trivial analytic gradient
        let which = rng.below(3);
        let (i, ana) = match which {
            0 => { let i = rng.below(FEATS * H); (i, g.ft[i]) }
            1 => { let i = rng.below(BUCKETS * 2 * H); (i, g.out_w[i]) }
            _ => { let i = rng.below(H); (i, g.ft_b[i]) }
        };
        if ana.abs() < 2e-5 { continue; }
        let h = 3e-3f32;
        let get = |n: &mut Net| -> *mut f32 { match which { 0 => &mut n.ft[i], 1 => &mut n.out_w[i], _ => &mut n.ft_b[i] } };
        let (mut a, mut b) = (net.clone(), net.clone());
        unsafe { *get(&mut a) += h; *get(&mut b) -= h; }
        let num = (loss_of(&a) - loss_of(&b)) / (2.0 * h as f64);
        let rel = (num - ana as f64).abs() / (ana.abs() as f64).max(1e-6);
        worst = worst.max(rel.min(10.0));
        rels.push(rel);
        checked += 1;
        if checked >= 60 { break; }
    }
    assert!(checked >= 20, "too few informative parameters checked ({checked})");
    // f32 sums and SCReLU kinks make single entries noisy; the distribution must be tight.
    rels.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let (med, p85) = (rels[rels.len() / 2], rels[rels.len() * 85 / 100]);
    assert!(med < 0.03 && p85 < 0.25, "gradient check failed: median rel {med:.4}, p85 {p85:.4}");
    // export / load round trip stays within quantisation error
    let q = std::env::temp_dir().join("nntrain_selftest.net");
    net.clip();
    net.export(q.to_str().unwrap());
    let back = Net::load(q.to_str().unwrap());
    let dl = (loss_of(&back) - loss_of(&net)).abs();
    assert!(dl < 5e-3, "export/load changes loss by {dl}");
    println!("selftest ok: {checked} gradient entries finite-difference rel err median {med:.4} p85 {p85:.4} (worst {worst:.2}), quantised round-trip dloss {dl:.2e}");
}

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    match a.first().map(|s| s.as_str()) {
        Some("train") => train(&a[1..]),
        Some("gen") => gen(&a[1..]),
        Some("eval") => eval_cmd(&a[1..]),
        Some("selftest") => selftest(),
        _ => eprintln!("usage: nntrain train|gen|eval|selftest (see header of src/bin/nntrain.rs)"),
    }
}
