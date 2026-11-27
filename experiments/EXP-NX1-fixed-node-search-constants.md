# EXP-NX1 - NNUE-aware search constants at FIXED NODES  [Agent NX]

**Status:** complete. **Result: NEGATIVE / NULL. No `src/` change proposed. No Elo claim.**
**Baseline:** `cp/stack-g4net` @ `bfe0b082e8f45fb3985694f0fb2aa9ce093d00e6` (stack #43+#47+#41 + G4 net `1bcaff62d74b`).
**Not** `main` (`73d0379`, HCE-only). Nothing here transfers to `main` without a re-test.

## Environment (all arms identical)
| item | value |
|---|---|
| hardware | 4 vCPU / ~3 GB shared sandbox (AVX-512 capable) |
| compiler | rustc/cargo 1.100, `cargo build --release` (no target-cpu flag) |
| base binary sha256 | `05a52383707b4441ebf8dbfe3c4e77f812ebf395cbf6771fbf524cd3a75e922f` |
| net (embedded) sha256 | `1bcaff62d74b4927e179b391b63b57fa29200429e0274f7969781863230bd276` |
| bench 8 (base) | 117615 nodes |
| match tool | fastchess v1.8.3-alpha, `tc=inf nodes=25000`, 1 thread, Hash 16, concurrency 4 |
| openings | `tools/openings_book.epd` sha256 `f1d9e14283d12cb31abb8ab84d99f44b4bf4e7433fa087b380d9ae019daed7e8`, `order=random`, `-repeat` (colours reversed) |
| adjudication | draw: movenumber 40 / movecount 8 / score 10; resign: movecount 4 / score 800 two-sided |
| script | `tools/ab_fixed_nodes.sh` (this PR) |

## Finding 1 - the earlier NNUE-aware SPSA runs were no-ops (read from job logs, not comments)
CP's `spsa.yml` runs `43676899435` (a-prune) and `43676901438` (b-search): 3,200 / 3,184 games, 400 / 398 iterations x 8 games at 5+0.05.
Every tuned value stayed within ~1% of its default (NmpEvalDiv 200->198, HistPrune 2500->2526, SeeCapture 100->99, LmrHistDiv 6000->5887, others unchanged).
With 8 games per iteration the gradient is almost pure noise, so those runs **do not** show that the defaults are optimal under NNUE.

## Finding 2 - fixed-node SPSA, ~15x more games/hour, also finds a flat optimum
`tools/spsa.py --nodes 25000` (EV's patch from #68, unchanged), 12 numeric parameters, 16 games/iteration, `r_mult 20`, seed 424242.
Stopped by me after **165 of 900 scheduled iterations (2,640 games: plus 690 / minus 726 / draws 1,224)** because no parameter had moved more than 5.5%.
State: `experiments/EXP-NX1/spsa_state_165it.json`.

| param | default | theta @ it.165 | change |
|---|---|---|---|
| RfpMargin | 70 | 69.0 | -1.4% |
| RfpImproving | 40 | 42.2 | +5.5% |
| NmpEvalDiv | 200 | 199.7 | -0.2% |
| LmpBase | 4 | 4.0 | +1.1% |
| HistPrune | 2500 | 2589.6 | +3.6% |
| SeeQuiet | 20 | 20.7 | +3.3% |
| SeeCapture | 100 | 102.1 | +2.1% |
| FutilityMargin | 120 | 120.4 | +0.3% |
| SeMargin | 40 | 40.4 | +0.9% |
| LmrScale | 45 | 44.4 | -1.2% |
| LmrHistDiv | 6000 | 5670.1 | -5.5% |
| AspWindow | 25 | 24.7 | -1.1% |

**Honest reading:** either the defaults sit on a flat optimum (consistent with FX1's LmrScale sweep) or 2,640 games are too few to resolve a gradient that small.
I deviated from my pre-registered plan (900 iterations, then a 5-replica gate of the tuned vector) because there is **no tuned vector worth gating**: stopping early is a decision to save compute, not a result about iterations 166-900. Not a proof that SPSA cannot help.

## Finding 3 - three single-change structural probes (1,000 games each, 25k nodes, test vs base)
| ID | change | W-L-D | score | Elo (95%) | verdict |
|---|---|---|---|---|---|
| NX-LMR2 | LMR starts at 2nd legal move (`legal >= 2`, was 4) | 242-284-474 | 47.90% | -14.6 +/- 16.3 | **revert** (null/negative) |
| NX-LMR3 | LMR starts at 3rd legal move (`legal >= 3`) | 276-281-443 | 49.75% | -1.7 +/- 15.9 | null, revert |
| NX-HIST2X | history bonus x2 (`340*d-180`, cap 3600; was `170*d-90`, cap 1800) | 274-270-456 | 50.20% | +1.4 +/- 15.9 | null, revert |

**Limits (read before citing):** one replicate each. The project's own rule is 5 independent replicates before any ship decision; these were screening runs, so they are **preliminary** and each can only rule out effects larger than about +-15 Elo. Fixed nodes ignore NPS side effects. No A/A control was run on this box for these three (an A/A on the same harness gave 13-13-14 / 40 games, only a smoke check).

## Decision
Keep `bfe0b082` search constants and LMR gate unchanged. Nothing to merge. Record negative results so nobody repeats them.

## Implication for the 80%-vs-SF19-3000 target
Search-constant retunes and move-ordering magnitudes are not where the remaining ~+240 Elo lives: three independent measurements (FX1's replication of the Q1 toggles and LmrScale sweep, CP's SPSA runs which were too small to say anything, and this one) found nothing at the +-15 Elo level. The only lever with a measured large effect on this board is the net (HCE -> NNUE was ~+225 limiter-Elo). Compute is best spent on net data/training (G5 chain, data quality, king-bucket/width tests with enough data), then re-tune constants once, with a much larger fixed-node budget, on the winning net.

## Reproduce
```
tools/ab_fixed_nodes.sh ./test_bin ./base_bin <seed> 500 25000 [UciOption=Value ...]
```
