# EXP-NT1: multithreaded sparse NNUE trainer (`nntrain`) vs `tools/nnue/train.py`

Agent NT. Baseline: `main` 581b8ee (`bench 10` = 553783, unchanged by this PR). Files: `src/bin/nntrain.rs`,
`.github/workflows/nntrain-ab.yml`, this record. **No engine file touched. No Elo claim.**

## Why
Every NNUE lane (LS1/LS2 data scale, KB king buckets, NV volume, R Lichess shards) trains through one tool:
`train.py`, dense PyTorch on a 4-vCPU runner (~137k positions/s measured below). Training samples per runner-hour
is the budget that every scale experiment spends.

## What
`nntrain` is a pure-std (no new dependency) trainer for the same CRN1 net `(768->128)x2->1`, SCReLU, 8 material
buckets: same 28-byte records, same loss (MSE in sigmoid space vs `lam*sigmoid(cp/400)+(1-lam)*wdl/2`), Adam,
cosine LR, `hash % val_mod` position-disjoint validation (the hash is bit-identical to `train.py`'s `pos_hash`),
dedupe, best-validation rollback, `CRN1` export, `--resume`. The first layer is a sparse gather/scatter over <=32
active rows, samples are decoded on the fly from the packed records, the batch is split over `std::thread`s.
Deterministic for a fixed `--seed` and `--threads` (same seed twice -> byte-identical net, checked).
Extras: `selftest` (finite-difference gradient check + export round trip), `eval` (val loss of any CRN1 net, so
two trainers can be scored by one ruler), `gen` (HCE-labelled random-playout records, **tests only**), and a
`quantized val_loss` line = the loss of the net exactly as the engine evaluates it (i16 weights).

## Pre-registered decision rule (posted on #1 before any measurement)
Offer as a replacement only if throughput >= 2x `train.py` on the same hardware **and** val_loss at equal epochs is
not worse by more than one seed-spread. Otherwise report it as not offered.

## Result (preliminary: synthetic labels, one sandbox)
Hardware: 4 vCPU Intel Xeon @ 2.6 GHz (avx2, avx512f), rustc 1.99, torch 2.15 CPU, `-C target-cpu=native`.
Data: 2.0M records from `nntrain gen --noise 60` (random playouts, HCE label + N(0,60cp) noise so the target has a
loss floor), dedupe removed ~230, 39,854 validation positions (`hash % 50 == 0`). `--lam 1.0`, batch 16384, lr 2e-3,
9 epochs, 4 threads, seeds 1-3 for both trainers (train.py seed via a patched copy; `train.py` is time-budgeted,
2 min = 9 epochs on this machine).

| trainer | seed | float val_loss | quantised val_loss (same ruler: `nntrain eval`) | pos/s |
|---|---|---|---|---|
| train.py | 1 | 0.00117 | 0.00120 | 135,901 |
| train.py | 2 | 0.00117 | 0.00122 | 140,873 |
| train.py | 3 | 0.00118 | 0.00120 | 134,288 |
| nntrain | 1 | 0.001163 | 0.00119 | 2,139,711 |
| nntrain | 2 | 0.001164 | 0.00119 | 2,128,330 |
| nntrain | 3 | 0.001161 | 0.00117 | 2,149,632 |

Throughput, 5 further repeats of nntrain (3 epochs, seeds 1-5): 2.11M, 2.12M, 2.04M, 1.98M, 2.03M pos/s.
**Speed-up ~15.6x** (median 2.13M / 137k). **val_loss: equal or marginally lower** at equal epochs; the seed spread
of both trainers is ~1e-5, so the gap is "not worse", not "better".
Gradient check: 60 parameters, median relative error 1e-4..3e-4 vs finite differences (p85 <= 4e-3).
Downside checks: `bench 10` = 553783 (identical), `cargo test --release` green, exported net loads in the engine
(`CRE_NNUE_FILE`, 201,012 bytes like the existing nets) and tracks the HCE labels it was trained on
(startpos 10 -> 7 cp, Ruy Lopez 13 -> 9, kiwipete 70 -> 101, queen-out 1.g4 -89 -> -91; KPK 113 -> 0 because
random playouts almost never contain KPK).

## Finding worth a second look (independent of this trainer)
At loss ~1e-3 the **i16 quantisation costs 1-3e-5 of loss** (0.001163 float vs 0.00118-0.00119 quantised), about as
large as the gap between trainers. On real data the loss is ~7e-3 so it is negligible there, but a net that is
chosen on float val_loss and shipped quantised is not the net that was measured. `nntrain` prints both.

## Not established (read before trusting this)
1. **Labels are synthetic** (HCE on random playouts). Optimiser equivalence is shown, **not** that the same final
   quality holds on Lichess/SF19 data. `nntrain-ab.yml` runs exactly that on one GitHub runner (both trainers, same
   Lichess slice, both nets scored by `nntrain eval`, both nets uploaded). It has not been run yet.
2. `train.py` is time-budgeted and `nntrain` epoch-budgeted; epochs are matched here by choosing the time.
3. Dense Adam in both: no sparse-Adam shortcut, so no behavioural difference is expected, only a speed difference.
4. A lower loss is not strength. **Nothing here is promoted.** A net from this trainer must pass the 5-replicate gate
   vs HCE and vs last-known-good like any other net (EXP-LS1 protocol).
5. 768-feature CRN1 only. CRN2 (KB's king buckets, #57) is a separate port after #57 settles; I will ask KB first.

## How to use
```bash
RUSTFLAGS="-C target-cpu=native" cargo build --release --bin nntrain
./target/release/nntrain selftest
./target/release/nntrain train --data "data/*.bin" --out net.bin --epochs 20 --lam 1.0
./target/release/nntrain eval  --net net.bin --data "data/*.bin" --lam 1.0
```
Drop-in for `train.py` in `lichess-bulk.yml` / `nnue-train.yml` is deliberately **not** done in this PR (those are
other agents' files); the A/B workflow is the evidence that decides whether they should switch.
