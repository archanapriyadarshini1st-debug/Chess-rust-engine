# EXP-NP1 — in-check extension policy (+ null-move double-null probe)

Agent NP (new session, same owner). **Pre-registered before the first game.**
Baseline: `main` @ `581b8ee` (repository `archanapriyadarshini1st-debug/Chess-rust-engine`), `bench 10` = **553783** nodes.

## Why this lane
`search()` adds `depth += 1` at *every* in-check node (`if in_check && excluded.is_none()`), PV or not.
Stockfish and Reckless have no blanket in-check extension; Ethereal/Viridithas extend far more selectively. It is a
large, unmeasured tree-shape lever in this engine: at depth 10 it accounts for **46 % of all bench nodes**
(see table). Nobody on issue #1 or in the open PRs owns it (TH = TT/node types/eval refinement, Q = LMR/pruning toggles,
BC = ordering, CX = time, EG = endgame, SP/CC = SPSA of numeric params; none touches this line).

## Change (one, default-off)
New UCI spin `XCheckExt` (`params.rs` + 6 lines in `search()`):

| value | behaviour |
|---|---|
| 2 (default) | current main: extend every in-check node |
| 1 | extend only PV in-check nodes |
| 0 | never extend |

Not an SPSA target (structural switch). **Default = main, so `bench` is node-identical (553783) when unchanged.**

## Probe that was dropped (negative result, recorded)
Hypothesis: `search()` allows two null moves in a row (no guard). Toggle `XNmpNoDouble=1` forbidding it changed
`bench 10` from 553783 to 553781 nodes (**2 nodes in 553783**). It essentially never fires, so it is not worth a
code path or any games. Removed from the PR. Nothing to ship, nothing hidden.

## Local correctness (before any game)
| check | result |
|---|---|
| `cargo test --release` (perft, eval params, parity, lib) | all pass |
| `bench 10`, default | 553783 (identical to main) |
| `bench 10`, `XCheckExt=1` | 465942 nodes (-15.9 %) |
| `bench 10`, `XCheckExt=0` | 300130 nodes (-45.8 %) |

Fewer nodes at equal depth is **not** evidence of strength: the shallower tree may simply search less. Only games count.

## Hypotheses
* H1: restricting the extension to PV nodes (`1`) is >= main in strength (cheaper non-PV trees buy depth where it matters).
* H2: removing it entirely (`0`) loses strength, because qsearch has no quiet-check generation, so perpetual/mating
  attacks need the extension.
* Possible regressions: tactical blindness in forcing lines; time-use change; mate-finding depth.

## Test configuration (fixed now)
* Workflow: repo's `sprt.yml`, `tc=10+0.1`, Hash/threads as the workflow sets, colours swapped, `openings_book.epd`.
* TEST = the code commit with `option.XCheckExt=<v>`; BASE = **the identical commit, default options** (so the only
  difference is the option; compiler/flags/binary are the same).
* **5 independent replicas per variant** (user's "test it 5 times" rule), each `max_rounds=400` (800 games).
  Bounds `elo0=-1, elo1=1` so SPRT practically never stops early; every replica plays its cap, which keeps the replicas
  poolable. `base` branch names `agentNP/base-1..5` (identical commit) avoid the workflow's concurrency-group cancel.
* Pool the 5 replicas: trinomial score, 95 % CI, chi^2 heterogeneity (df 4).

## Decision rule (fixed before the first game)
* **PROMISING** only if pooled 95 % CI lower bound > 0 **and** >= 4/5 replicas > 50 % **and** chi^2 p > 0.05.
  A promising result is *not* a merge: it must then (a) show no time forfeits/illegal moves/crashes in the logs, and
  (b) pass 5 replicated matches vs SF19 `UCI_Elo` (downside check) before anyone proposes a merge.
* **REJECT** if pooled upper bound < 0.
* Otherwise **INCONCLUSIVE**: main is unchanged and the numbers are published as they are.
* ~4000 games per variant resolves roughly +/-7 Elo (95 %). A smaller true effect cannot be seen here and will be reported as such.

## Results
_(filled in below as replicas finish; nothing edited after seeing outcomes except appending)_
