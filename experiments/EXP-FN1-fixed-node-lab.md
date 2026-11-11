# EXP-FN1/FN2 - fixed-node A/B lab, replication, and a bench-vs-NPS downside (Agent FN)

**Repo / baseline:** `archanapriyadarshini1st-debug/Chess-rust-engine` `main` 581b8ee (bench 10 = 553783). Candidates built from `pull/N/head` (#39 410f725, #40 657ceeb, #41 823f66a, #42 6cf2ff8, #46 1c5e2ba) on 2026-11-11.

## Method (fixed before any game was played)
- fastchess `fastchess alpha 1.8.3 compiled for ubuntu-22.04 20261107-d7b47e8 (CI)`; `-each tc=inf nodes=25000`; Hash 16, Threads 1; book `tools/openings_book.epd` (595 lines, sha256 prefix `f1d9e14283d12cb3`), `order=random`, `-games 2 -repeat` (colours swapped), adjudication as in `sprt.yml` (draw movenumber=40 movecount=8 score=10; resign movecount=4 score=800 twosided), maxmoves 300, concurrency 3.
- Hardware: Intel(R) Xeon(R) Processor @ 2.60GHz, 4 vCPU, 3.9 GB, Linux 6.1.189+, rustc 1.99.1, default `cargo build --release`.
- Stage 1 (screen): 400 games per candidate vs main, seed 101, plus an A/A control (main vs main).
- Stage 2 (owner's "test it 5 times"): 5 replicates, disjoint seeds 201-205, x300 games for #39 and #40 (the two largest Stage-1 deviations, one up, one down), x100 for the FN fix.
- Elo = logistic from score; CI = trinomial (per-game variance); LOS = normal CDF. Computed by `tools/fixed_node_lab/stats.py` from raw W/D/L only.
- Binary sha256 prefixes: {"main": "4d3b1bbc62d96479", "fn": "81d52d42bfb46b53", "pr39": "019f9f2a69c22391", "pr40": "4d78190557139ad8", "pr41": "f3d7fa3675ae99b1", "pr42": "1f938094acf96177", "pr46": "31d06edeedb05c83"}
- 7,100 games total. Illegal-move / disconnect / stall / time-loss grep across every log: **0**.

## Results
| candidate | seed | W-D-L | score | Elo | 95% CI |
|---|---|---|---|---|---|
| pr40 | 101 | 97-182-121 | 47.0% | -21 | [-46, +4] |
| pr40 | 201 | 75-147-78 | 49.5% | -3 | [-32, +25] |
| pr40 | 202 | 87-138-75 | 52.0% | +14 | [-15, +43] |
| pr40 | 203 | 95-122-83 | 52.0% | +14 | [-16, +44] |
| pr40 | 204 | 79-135-86 | 48.8% | -8 | [-37, +21] |
| pr40 | 205 | 89-128-83 | 51.0% | +7 | [-23, +37] |
| **pr40 pooled s2 (5 reps)** | | 425-670-405 | 50.7% | +5 | [-8, +18] LOS 76% ; per-rep scores [49.5, 52.0, 52.0, 48.8, 51.0] |
| pr41 | 101 | 115-161-124 | 48.9% | -8 | [-34, +19] |
| pr42 | 101 | 119-157-124 | 49.4% | -4 | [-31, +22] |
| pr39 | 101 | 120-179-101 | 52.4% | +17 | [-9, +42] |
| pr39 | 201 | 96-123-81 | 52.5% | +17 | [-13, +48] |
| pr39 | 202 | 83-137-80 | 50.5% | +3 | [-26, +33] |
| pr39 | 203 | 92-137-71 | 53.5% | +24 | [-5, +54] |
| pr39 | 204 | 79-130-91 | 48.0% | -14 | [-44, +16] |
| pr39 | 205 | 96-124-80 | 52.7% | +19 | [-12, +49] |
| **pr39 pooled s2 (5 reps)** | | 446-651-403 | 51.4% | +10 | [-3, +23] LOS 93% ; per-rep scores [52.5, 50.5, 53.5, 48.0, 52.7] |
| q-XCapLmr | 101 | 101-175-124 | 47.1% | -20 | [-46, +5] |
| q-XLmrFut | 101 | 116-170-114 | 50.2% | +2 | [-24, +28] |
| q-XDeeper | 101 | 107-176-117 | 48.8% | -9 | [-34, +17] |
| q-XFailHighRed | 101 | 117-154-129 | 48.5% | -10 | [-37, +16] |
| AA-main-vs-main | 101 | 108-184-108 | 50.0% | -0 | [-25, +25] |
| fn | 201 | 35-30-35 | 50.0% | -0 | [-57, +57] |
| fn | 202 | 20-60-20 | 50.0% | -0 | [-43, +43] |
| fn | 203 | 28-44-28 | 50.0% | -0 | [-51, +51] |
| fn | 204 | 25-50-25 | 50.0% | -0 | [-48, +48] |
| fn | 205 | 31-38-31 | 50.0% | -0 | [-54, +54] |
| **fn pooled s2 (5 reps)** | | 139-222-139 | 50.0% | -0 | [-23, +23] LOS 50% ; per-rep scores [50.0, 50.0, 50.0, 50.0, 50.0] |

### Bench per-node speed (5 interleaved rounds, `bench 10`, NPS)
| build | NPS rounds | median | vs main |
|---|---|---|---|
| main | 2138158 2105638 2105638 2097662 2146445 | 2105638 | 1.000 |
| #39 | 1887555 1785363 1881221 1874929 1919876 | 1881221 | **0.893** |
| #40 | 1999085 2014059 2068284 1984332 2076270 | 2014059 | 0.957 |
| FN fix (#51) | 2097662 2013756 2097662 2081890 2113675 | 2097662 | 0.996 |

## Findings (honest reading)
1. **A/A control = 50.0% (108-108-184).** The harness is unbiased; +-25 Elo is the 95% noise at 400 games, so Stage-1 numbers for #41, #42 and the four Q toggles are *screens only* (none beyond noise; XCapLmr -20 [-46,+5] was NOT replicated, so no conclusion).
2. **#40 was a false alarm in Stage 1** (-21 Elo at 400 games) and came back to +5 [-8,+18] over 1,500 games. One short match misled; that is the case for 5 replicates.
3. **#39 (TH1 TT):** +10 Elo fixed-node [-3,+23], LOS 93%, replicate scores 48.0 .. 53.5%. But **per-node speed is ~10.7% lower** in all 5 interleaved bench rounds (every #39 round is below main's slowest). At roughly 50-60 Elo per NPS doubling that is about -8..-10 Elo at real time control, which would cancel the fixed-node gain. Fixed-node games cannot see this; a real-TC SPRT can. Suggestion to TH: profile the probe/store path in #39 before spending a ship-gate on it.
4. #40 costs ~4% NPS (close to this box's noise) for an unproven +5.
5. **#51 (mate beats 50-move) is node-identical**: 88/88 searches identical, 5 x 100 games all exactly 50.0% (identical games). No Elo claim; it is a correctness fix.

## What this does NOT show
- Fixed nodes at 25k (depth ~10) is not 10+0.1. A change that helps only at depth 14+ can look neutral here. Nothing above is a promotion verdict.
- Stage 2 replicated only two candidates. #41, #42 and the Q toggles still need replicates if their authors want fixed-node evidence.

## Reproduce
`tools/fixed_node_lab/run.sh NAME BIN "option.X=1" ROUNDS SEED` (BASE = `/tmp/bins/main`, book at `/tmp/book.epd`), then `stats.py`. Node-identity: `ident.py BIN_A BIN_B` (holds stdin open until bestmove).
