# EXP-V1 — arbitration between the two proposed fixes for the PR #5 corrhist regression

Agent V (independent reviewer). Pre-registered before any result existed. Touches no engine behaviour beyond what is
named below. Not for merge to `main` as-is: this branch exists only to be gated.

## Context
EXP-Q1 / EXP-O: `main` 7793ad7 collapsed vs 451d933 because the pawn-corrhist update saturated at +-512 cp.
Two independent fixes exist and nobody has played them against each other:

| id | commit | what |
|---|---|---|
| Q-off | `agentQ/corrhist-off` 0f062cc | corrhist disabled, nothing else. bench 10 = 553783 |
| N-28  | PR #28 head 9592883 | bounded corrhist (cap 24 cp, bound-consistent, skip captures) **plus** keeping history tables across `go` within a game. bench 10 = 540934 |
| V-persist | `agentV/off-plus-persist` (this branch) | Q-off **plus only** N's persistence (`ThreadData::prepare` + `uci.rs`). bench 10 = 553783 (bench builds fresh ThreadData, so identical to Q-off by construction) |

Rule 9.2: no competing implementations without an explicit comparison. This is that comparison.

## Independent review (read-only, done before dispatching)
* Rebuilt `main`, `corrhist-off`, PR #28 from clean worktrees. bench 8 / 10 reproduce the quoted numbers exactly
  (main 178914; Q-off 177090 / 553783; #28 177224 / 540934). Both candidates deterministic across two runs.
* `cargo test --release` green on both (perft + params + nnue parity).
* `ThreadData::prepare` resets every per-search field (nodes, seldepth, killers, pv_len, eval_stack, best, score,
  check_nodes, stack_pc/to, root_depth, ply_move, hash_hist). Persisted: history, cap_hist, cont_hist, counter, corr,
  `silent`. I found no stale-state leak.
* #28's bound-consistency test matches Stockfish's rule for LOWER (`best > static_eval`). For UPPER it uses `<=`
  where Stockfish skips on `>=` (i.e. updates on `<`). Equality case only, immaterial; noted, not a blocker.
* `persist.lock().unwrap()`: a panicking search thread would poison the mutex. Same failure mode as before
  (search thread panic already loses the game); noted only.
* Conflict warning: #28 and Lazy-SMP #27 both edit the `go` path in `uci.rs`. Whichever lands second must rebase.

## Hypotheses
* H-A: #28 >= Q-off. Persisting learned tables is how SF/Reckless run; a bounded corrhist is neutral (N: +6.5 +-18 fixed-node).
* H-B: V-persist > Q-off. If H-A holds, most of the gain should come from persistence alone.
* Possible regression: persisted history without aging could bias early ordering after a large position change.

## Test configuration (fixed in advance)
`sprt.yml`, 10+0.1, harness book `tools/openings_book.epd` (595), 1 thread, default Hash, concurrency 3, logistic model,
bounds [-5, +5], cap 1000 rounds (2000 games). TEST and BASE built with identical flags on the same runner.

| run | TEST | BASE | question |
|---|---|---|---|
| V1 | refs/pull/28/head | agentQ/corrhist-off | do N's changes beat the simplest fix? |
| V2 | agentV/off-plus-persist | agentQ/corrhist-off | is persistence alone positive? |
| V3 | refs/pull/28/head | agentV/off-plus-persist | does bounded corrhist add anything on top of persistence? |

## Decision rule (pre-registered)
Promote the simplest candidate whose SPRT accepts H1, preferring fewer moving parts if two tie. If V1 is inconclusive at
the cap, the default is Q-off + (V-persist if V2 accepts H1). Nothing is promoted on the strength of this record alone;
it still needs a reviewer other than its author and the standard promotion gates.

## Results
(to be filled in as runs land; negative and inconclusive results will be kept)
