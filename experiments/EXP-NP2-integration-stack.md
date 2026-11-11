# EXP-NP2 — integration test: time-management stack (#43 + #47) + TT-eval refinement (#41) vs main

Agent NP. **Pre-registered before the first game.** Repository `archanapriyadarshini1st-debug/Chess-rust-engine`.
Baseline: `main` @ `581b8eef45a0d3298d9229c900173ea15a85555f` (bench 10 = 553783).

## Why
Every candidate so far was measured **alone** against main, by a different agent, with different time controls and
different stopping rules. Nobody has measured whether two independent positive candidates stack. Merging unmeasured
combinations is how engines silently lose Elo ("candidates interact"). Evidence ledger (raw `sprt.yml` logs, recomputed
by NP, trinomial 95 % CI; SPRT-stopped runs are biased upward, treat the lower bound with care):

| candidate | PR | tc | W-D-L | Elo vs main [95 % CI] | verdict |
|---|---|---|---|---|---|
| `agentCX/time-stability-fix` (stacked on #43) | #47 | 10+0.1 | 228-553-145 (n=926) | +31 [+17, +45] | SPRT PASS |
| `th/s-time-mgmt` | #43 | 5+0.05 | 342-830-262 (n=1434) | +19 [+8, +31] | SPRT PASS |
| `th/tt-eval` | #41 | 5+0.05 | 274-718-194 (n=1186) | +23 [+11, +36] | SPRT PASS |

#47 already contains #43's commit, so the first two rows overlap; the two *independent* areas are
**time management** (`time.rs` / `iterative_deepening`) and **eval refinement in pruning** (`search()` body).

## Candidate
Branch `agentNP/stack-time-tteval` = `main` + `agentCX/time-stability-fix` (#47, includes #43) + `th/tt-eval` (#41).
Merge is conflict-free. Credit: Agents TH (#41, #43) and CX (#47); NP only integrated and measures.
| check | result |
|---|---|
| `cargo build --release` | ok |
| `cargo test --release` | all pass (8 + 4 + 3 + ...) |
| `bench 10` | **496195** (== #41 alone; time code does not affect fixed-depth bench) |

## Hypotheses
* H1: the stack beats main by a positive amount at 10+0.1 (expected lower than the sum of the parts, because each
  individual figure is SPRT-stopped/optimistic and both partly act through "think longer / prune safer").
* Possible regressions: interaction between the new stability scaling and the TT-eval-changed search (different
  best-move flip rate -> different time use); higher time-loss risk; tactical regressions from more aggressive eval-based pruning.

## Test configuration (fixed now)
`sprt.yml`, `tc=10+0.1`, logistic, `elo0=-1, elo1=1` (effectively never stops early), `max_rounds=400` (800 games) x
**5 independent replicas** (owner's "test it 5 times"), TEST = candidate commit, BASE = unmodified main
(`agentNP/main-1..5` all point at `581b8ee`, which only makes the five concurrency groups distinct). Pool: trinomial
score, 95 % CI, chi^2 heterogeneity (df 4).

## Decision rule (fixed now)
* **PROMISING**: pooled CI lower bound > 0, >= 4/5 replicas > 50 %, chi^2 p > 0.05.
* **REJECT**: pooled CI upper bound < 0. **INCONCLUSIVE** otherwise. Nothing is merged by NP in any case.
* PROMISING is a *recommendation to the owner/reviewers*, not a merge: it additionally needs (a) log check: 0 time
  forfeits / illegal moves / crashes, (b) 5 replicated `sf19-match.yml` UCI_Elo runs as downside check, (c) a second
  agent's review of the integrated diff. Components must also not be merged individually in a way that changes this
  tested combination without re-testing.
* Not tested here (said openly): each component alone at 10+0.1 inside the same harness, the stack at 5+0.05, NNUE interaction.

## Results
_(appended as replicas finish)_
