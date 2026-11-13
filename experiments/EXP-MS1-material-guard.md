# EXP-MS1 - material-blind nets and the NNUE material guard (Agent MS)

**Repository / commit:** `archanapriyadarshini1st-debug/Chess-rust-engine`, base `main` @ `73d0379`, branch `agentMS/material-guard`.
**Status: PRELIMINARY (one machine, 40-game replicates). Decision: KEEP as default-off option + KEEP the probe tool. NOT a strength claim. No default change proposed.**

## Hypothesis
A net fine-tuned only on near-balanced positions cannot value lopsided material (it never saw it), so the engine drops or fails to win pieces even though search sees them. A material-aware blend toward the (material-correct) HCE score when |imbalance| is large should rescue such a net, and should be harmless for a healthy net.

## How it was found (weakness loop)
1. `main` + `nnue/ft-43234452295` net (`7253b07162ce`) vs SF19 UCI_Elo 3000, 10+0.1: **0-20** (aborted at 20). All losses were resign-adjudications.
2. Position reconstruction: game 2, `1.Nc3 e6 2.Nxd5? exd5`; Rust reports +0.73 / +0.91 for itself, SF19 +6.1. HCE static eval of that position = -301, FT net = +173.
3. Cause = evaluation (net coverage). Search, movegen and time management behave normally (depth 12-16, 0.2-1.4 s per move, no forfeits).
4. Static probe (`tools/material_probe.py`, 150 legal positions per class, side to move is up the piece):

| class | HCE | FT `7253b07162ce` | lichess-bulk `964d07413bac` | stage0-selfd7 `b66fe0abd943` |
|---|---|---|---|---|
| minor | 350 | 127 (0.35, 11/150 not ahead) FAIL | 381 PASS | 364 PASS |
| rook | 448 | 276 (0.63) FAIL | 457 PASS | 461 PASS |
| queen | 1000 | 338 (0.34) FAIL | 830 PASS | 1009 PASS |

   With `NnueGuard=150 NnueGuardSpan=300` the FT net moves to minor 224 (0.63, still FAIL), rook 443, queen 1000. The minor case is only partly corrected because a 300 cp imbalance sits inside the blend ramp; a lower start would fix it but touches more positions. Not tested here.

## Change
`eval.rs::material_guard` + `params.rs` `NnueGuard` (default 0 = off), `NnueGuardSpan` (default 400). When on: `w = clamp((|material_stm| - Guard) / Span, 0, 1)`; `score = nnue + (hce - nnue) * w`. HCE is evaluated only when |imbalance| > Guard. `tools/material_probe.py` is new and standalone.
Correctness: `bench 10` = **553783** with guard off (3 runs, same as main); `cargo test --release` 13 pass (2 new guard tests).

## Test configuration
Same binary (`cre_ms`, sha256 prefix `ff458efa083c`; base `main` binary `563cd2a342cf`; net sha prefixes in the tables; book `f1d9e14283d1`), same net per arm, Hash 64, 1 thread, 10+0.1, `tools/openings_book.epd`, colours reversed, `-srand` per replicate, draw/resign as `sf19-match.yml` (draw movenumber=40 movecount=8 score=20; resign movecount=3 score=600), concurrency 3 on 4 vCPU / 3.9 GB. Arm A = guard 150/300, arm B = guard off. Pre-registered KEEP rule (posted on issue #1 before the downside arm ran): rescue holds AND pooled downside score >= 48%.

## Results (raw logs in `EXP-MS1/raw_pgn_logs.tar.gz`, tally in `EXP-MS1/tally.txt`)
| arm | W-L-D | score | Elo (95%) |
|---|---|---|---|
| FT net, guard vs off (rescue) | 35-2-3 / 40 | 91.2% | +407 +-250 |
| lichess-bulk, guard vs off r1..r5 | 8-4-28, 8-11-21, 9-5-26, 10-5-25, 8-7-25 | 55.0, 46.2, 55.0, 56.2, 51.2 | |
| **lichess-bulk pooled** | **43-32-125 / 200** | **52.8%** | **+19 +-30** |
| lichess-bulk A/A control (guard off vs off) | 8-9-23 / 40 | 48.8% | -9 +-71 |

4 of 5 replicates > 50%; the pooled interval includes 0.

## Decision and what this does NOT show
* KEEP the option (default off) and the probe: the rescue is large and the downside on a healthy net is not measurable (pooled 52.8%, CI includes 0, A/A 48.8%).
* It does **not** show the guard improves a healthy net: +19 +-30 is inconclusive; ~800 games would be needed to resolve +20. Do not enable by default on that evidence.
* The SF19 UCI_Elo 3000 score of the FT net **with** the guard has not been measured.
* The right fix for the FT net is training-data coverage (add odds positions labelled by SF19 to the relabel set); the guard is a safety net, not a substitute.
* Not tested: TL's SF19-labelled net (only in an expiring run artifact), any net other than the three above.

## Reproduce
```
python3 tools/material_probe.py --engine target/release/chess-rust-engine --net NET.nnue --n 150
bash experiments/EXP-MS1/exp_ms1.sh   # edit the net paths / binary
```
Hardware: 4 vCPU / 3.9 GB sandbox, rustc 1.100.0, `RUSTFLAGS=-C target-cpu=native`. SF19 sha256 `0f83d24cc46d2c66`, fastchess 1.8.3-alpha.
