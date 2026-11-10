# EXP-T2: ship gate - five independent runs against the last-known-good binary

- **Experiment ID:** EXP-T2
- **Responsible agent:** T2 (ship-gate lane; owns `tools/ship_gate.py`, `.github/workflows/ship-gate.yml`, this file)
- **Repository / baseline:** `archanapriyadarshini1st-debug/Chess-rust-engine` @ `7793ad7` (main). No `src/` change.
- **Status:** infrastructure + validation on real binaries. **No Elo claim about any engine change.**

## Hypothesis
`bench`, perft and CI cannot see a strength collapse (PR #5 was bench-identical to the commit before it and
lost 0-4-204 in head-to-head, EXP-Q1). A cheap pre-SPRT gate made of **independent repeats** would have caught it,
would not cry wolf on an unchanged engine, and would expose throughput costs and non-determinism.

## What the gate does
`python3 tools/ship_gate.py --cand BIN --base LKG_BIN [--runs 5 --games 40 --tc 10+0.1 --expect behavior-change|node-identical]`

1. candidate `bench 10` twice, must be identical (determinism); with `--expect node-identical` it must equal the LKG's nodes;
2. 7 interleaved bench repeats each, best-of-7 nps ratio;
3. 5 independent runs, each with its own seed and a **disjoint** slice of the 595-position book, colours reversed per opening;
4. per-run collapse check (LOS < 0.5% -> BLOCK), pooled check (LOS < 2.5% -> BLOCK, < 10% -> HOLD);
5. Cochran Q heterogeneity across runs (p < 0.01 -> HOLD: result not reproducible);
6. engine-health scan of fastchess logs (illegal move / disconnect / stall -> BLOCK);
7. writes `ship_gate.json` (binary sha256, book sha256, seeds, per-run W-D-L, nps samples, verdict) and `ship_gate.md`.

Exit codes: 0 SMOKE-PASS, 1 BLOCK, 3 HOLD, 4 ERROR. **SMOKE-PASS is never a merge approval.** It means "spend SPRT games".
TC floor 5+0.05 is enforced (same rule as `sprt.yml`).

## Cost of the gate itself (simulation, `--selftest`, 3000 trials, 5 x 40 games, 40% draws)
| true strength of candidate | SMOKE-PASS | HOLD | BLOCK |
|---|---|---|---|
| equal (A/A) | 88.8% | 7.0% | 4.2% |
| -30 Elo | 38.4% | 24.6% | 37.1% |
| -60 Elo | 2.4% | 7.1% | 90.5% |
| -100 Elo | 0.0% | 0.1% | 99.9% |

So: about 11% of genuinely-equal candidates get an alarm (they cost a re-test, not a rejection); a -30 Elo patch slips through
38% of the time. **This gate finds collapses and large regressions; it does not replace SPRT** and cannot see small ones.

## Validation on real binaries (4 vCPU Xeon sandbox, plain `target-cpu=native` release builds, 5+0.05, 5 runs x 20 games = 100 games each; PRELIMINARY)
LKG = `451d933` (bench 10 = 356715). Book sha256 prefix `f1d9e14283d1`. All numbers are from the candidate's point of view.

| candidate | bench 10 | per-run (+W =D -L) | pooled | Cochran p | verdict |
|---|---|---|---|---|---|
| `main` `7793ad7` (known bad, PR #5 corrhist) | 469049 | 0-0-20 x5 | 0% / 100 games | n/a | **BLOCK** (all 5 runs collapse) - reproduces EXP-Q1 |
| `451d933` copy vs itself (A/A control) | 356715 | +6=10-4, +4=12-4, +2=12-6, +6=9-5, +4=9-7 | 48.0%, -14 Elo [-62,+33] | 0.55 | **SMOKE-PASS** |
| Q `corrhist-off` `0f062cc` | 553783 | +4=11-5, +5=12-3, +5=12-3, +2=9-9, +1=11-8 | 44.5%, -38 Elo [-85,+7], LOS 5.1% | 0.028 | **HOLD** |
| N PR #28 `9592883` | 540934 | +4=13-3, +5=13-2, +3=16-1, +7=9-4, +5=12-3 | 55.5%, +38 Elo [-3,+80], LOS 96.5% | 0.984 | SMOKE-PASS (with nps WARN), see below |

Reading, without over-reading:
- The A/A control shows why single 20-game matches are useless: the *same binary against itself* ranged from -70 to +35 Elo across runs. That is the reason for repeats and pooling.
- **Q-off HOLD** is consistent with V2's 500-game `diag-nocorr` vs `451d933` (-9 Elo, CI roughly +-18): at 100 games it is neither proven worse nor proven equal. It also carries SE's +55% nodes at depth 10 for no demonstrated gain (V2). `451d933` stays the rollback reference.
- **PR #28** was the only candidate whose five runs agree (Cochran p = 0.98) and are all >= 52.5%. Pooled CI still touches 0 (-3), so this is *not* a proven gain; it is a strong reason to let V1-V3's SPRTs finish. Through the common base it ranks above Q-off, which agrees in direction with N's own fixed-node +80 for persistence. Indirect comparison, 100 games each: do not quote the 76 Elo gap.

## Downside found: PR #28 costs real throughput
Bench builds a fresh `ThreadData`, so persistence is not in the bench; the per-node cost is the bounded corrhist update.
Best-of-7 nps ratio vs LKG over repeated measurements: **0.939, 0.941, 0.962** (median-based: 0.926, 0.949, 0.944, 0.970, 0.984).
A/A noise on the same box reads 0.993 to 1.037, Q-off reads 0.990 to 0.997. So PR #28 is about **4-6% slower per node**, within +-4% measurement noise
on a shared 4-vCPU box. The nodes-to-depth ratio vs LKG is 1.516 (SE + corrhist), so nps is not the main cost; node count is.
Not a blocker on its own (the games pay for it) but it must be on the record, and any node-identical PR must not carry it.

## Honest disclosure: I changed the gate's own rule after seeing a result
My first version hard-BLOCKed any candidate below 0.95 nps. PR #28 hit 0.926 on its first measurement and was BLOCKed. Repeating the measurement showed
the nps number was noisy (+-4%) and that blocking a deliberate per-node cost was the wrong rule for behaviour-changing patches. I changed it to:
- `--expect node-identical`: BLOCK < 0.95, HOLD < 0.98 (a slowdown is pure loss), and ratio uses best-of-7 because contention only slows runs down;
- `--expect behavior-change`: BLOCK only < 0.85 (pathological); WARN < 0.97 so the cost is visible and the strength games must offset it.
This was a post-hoc rule change on the gate, not on any engine result, and it is recorded here so nobody mistakes the original BLOCK on PR #28 for a strength finding. The game-stage rules were **not** changed after seeing data, except one change made during the *selftest*, before any engine game was played: the first HOLD rule ("pooled point estimate < -10 Elo") put 27% of equal engines in HOLD, so it was replaced by "pooled LOS < 10%" (equal engines in HOLD: 7%).

## Not done / limits (stated so nobody over-reads this)
- 100 games per candidate at 5+0.05 on one box is **preliminary**. Nothing here promotes or demotes any PR; SPRT does that.
- No Stockfish was involved. This lane is about not shipping regressions, not about measuring strength vs SF19.
- The 5 x 40 @ 10+0.1 default (200 games) is what `ship-gate.yml` runs on GHA; I only ran the smaller 5 x 20 @ 5+0.05 locally.
- Bench-only detection of Elo effects is impossible by construction (bench is blind to correction-history poisoning); the gate says so in its output when bench equals the LKG's.

## Reproduce
```
cargo build --release   # for cand and for LKG, same flags
python3 tools/ship_gate.py --selftest
python3 tools/ship_gate.py --cand ./engine_cand --base ./engine_lkg --runs 5 --games 40 --tc 10+0.1 --out ship_out
# or: Actions -> "Ship gate (5 independent runs vs last-known-good)" -> cand=<sha> base=<lkg sha>
```

## Decision
**Keep** (tooling). Proposed use in the merge flow: ship-gate -> if SMOKE-PASS -> `sprt.yml` -> merge on H1 only.
