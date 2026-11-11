# EXP-SP1 — SPSA at scale on `main@581b8ee`  [Agent SP]

**Status:** IN PROGRESS (runs dispatched 2026-11-11 13:09Z). **No Elo claim. No tuned value exists yet.**
**Repository:** `archanapriyadarshini1st-debug/Chess-rust-engine` (authoritative). **Base commit:** `581b8eef45a0d3298d9229c900173ea15a85555f` (= `40faeb7` + docs).
**Baseline reference:** X1's EXP-X2, 318-37-145 / 500 = 67.3% vs SF19 UCI_Elo 2600 on `40faeb7` (limiter scale, not CCRL).
**Baseline sanity:** `bench 10` = 553783 nodes (reproduced locally, native build, rustc stable).

## Hypothesis
The 16 search constants in `src/params.rs` are the original hand-set literals and were never tuned. W built the SPSA infrastructure (#20) and proposed no values. A tuned subset can recover Elo without any code change. Typical SPSA gains on an untuned engine are tens of Elo, but that is a prior, not a measurement here.

## Change under test
None in source. Only UCI option values (`setoption name X value N`), applied through `sprt.yml`'s `test_opts`.

## Runs (all `spsa.yml`, 5+0.05, iterations 500, rounds 4, concurrency 3, r_mult 8, budget 330 min, 1 thread)
| branch (same SHA) | group | seed | Actions run |
|---|---|---|---|
| `sp/prune-s1` | P: RfpMargin, RfpImproving, NmpEvalDiv, FutilityMargin, SeeQuiet, SeeCapture, HistPrune | 1 | 43026576248 |
| `sp/prune-s2` | P | 2 | 43026579773 |
| `sp/red-s1` | R: LmrScale, LmrHistDiv, LmpBase, SeMargin, AspWindow | 1 | 43026583918 |
| `sp/red-s2` | R | 2 | 43026588956 |

Run-to-branch mapping follows dispatch order. Confirm in the run's "Inputs" panel before citing it.
Excluded on purpose: `RfpDepth, FutilityDepth, NmpBase, NmpDepthDiv` (integer gates with c=1, which SPSA handles poorly).

## Pre-registered decision rules (written before any result)
1. **Seed agreement:** for each parameter, if the two seeds' tuned values move in opposite directions from default, that parameter stays at default. Otherwise use the mean of the two tuned values, rounded to integer.
2. **Gate 1 (head-to-head):** combined vector as `test_opts` vs the same commit with defaults, `sprt.yml`, 10+0.1, 5 independent replicates with disjoint seeds, same book. Report every replicate and the pooled score.
3. **Gate 2 (independent opponent):** the same vector vs SF19 UCI_Elo 2600 through `sf19-match.yml`, >= 300 games, compared with the 67.3% baseline.
4. **Ship only if** pooled Gate-1 score has a 95% lower bound > 50% **and** Gate-2 is not below baseline **and** no replicate pair disagrees in sign beyond chance. Otherwise HOLD or REVERT.
5. A tuned vector is valid only for the commit it was tuned on. If search-shape PRs (#39-#46) merge first, Gate 1 is re-run on the new `main` before any claim.

## Known risks / possible regressions
- 5+0.05 training TC is shorter than the 10+0.1 gate TC, so ultra-short-TC optima may not transfer. Gate 1 is the check.
- About 4k games per run is thin for 7 params. Small movement is expected, and flat is a valid outcome.
- SPSA's match score is a training signal, not a verdict.

## Results
_Pending. This section is filled in by whoever collects the artifacts (`spsa-<run id>`: `spsa_result.json`, `spsa_state.json`, `spsa.log`), including negative or flat outcomes._

## Decision
_Pending._
