# EXP-NI1: incremental NNUE accumulator (Agent NI)

- **Experiment ID:** EXP-NI1
- **Responsible agent:** NI (NNUE inference throughput). File owned for this change: `src/nnue.rs` only.
- **Baseline:** `main` @ `581b8ee`. HCE `bench 10` = 553783 nodes. Binary built `--release`, `target-cpu=x86-64-v2` (repo default).
- **Hypothesis:** `Network::eval` recomputes the whole first layer (all pieces x 2 perspectives) on every call. That makes
  an NNUE node ~2x slower than an HCE node, so every "net vs HCE at 10+0.1" gate so far mixed eval quality with a large
  NPS handicap. An incremental first layer removes the handicap without changing a single evaluation.
- **Proposed change:** per-thread cache of the last-evaluated 12 piece bitboards + two i32 accumulators. Each call XORs
  cached vs current bitboards and adds/removes only the changed feature rows; a diff that is not cheaper than a rebuild
  (`changed >= pieces`) or a cache built for another `Network` instance (unique id) restarts from the bias.
  **No `board.rs` / `search.rs` / `eval.rs` change**: the cache is stateless w.r.t. search history, so it is correct for any
  order of evaluation (child, sibling, jump to an unrelated position, another thread). i32 accumulators keep results
  identical to the old code for *every* net, including saturating ones.
- **Expected benefit:** NNUE NPS up toward HCE NPS. **Expected cost:** ~1 KB thread-local per thread; HCE path untouched.
- **Possible regressions:** a stale cache returning a wrong eval (the failure mode that matters) -> tested below;
  `Position` clones/threads sharing a cache -> thread-local; two nets in one process -> id-keyed.

## Correctness (all must hold before any strength number counts)
| check | result |
|---|---|
| `cargo test --release` (11 lib + perft + eval suites) | all pass |
| `incremental_matches_scratch_along_playouts`: 120 random games x 160 plies, 4 start positions, random net | cached == scratch on every position; asserts >300 distinct eval values and <5% clamp-saturated, so equality is not vacuous |
| `..._out_of_order_and_across_games`: forward, backward and random-jump order over 40 games | cached == scratch every time |
| `cache_is_not_shared_between_different_nets_on_one_thread` | pass |
| `caches_are_per_thread` (4 threads) | pass |
| `bench 10` nodes with stage-0 net, old vs new | **504281 == 504281** (identical search tree) |
| `bench 10` nodes, HCE | **553783 == 553783** |

A first version of my own tests used a random net that saturated at the +-3000 clamp, which would have made every
equality check vacuous; the `distinct`/`saturated` assertions were added because of it.

## Throughput (this sandbox, 4 vCPU shared, `bench 10`, stage-0 net `nets/candidates/stage0-selfd7.nnue`, 5 interleaved rounds)
| | old (from scratch) | new (incremental) |
|---|---|---|
| NNUE nps, 5 rounds | 835k / 831k / 853k / 849k / 820k | 1627k / 1488k / 1681k / 1648k / 1356k |
| HCE nps (3 rounds) | 1615k / 1731k / 1798k | 1629k / 1741k / 1816k (no change) |
HCE nps on the same box: ~1.77M, so NNUE went from ~47% to ~90% of HCE speed. Spread of the new runs is large (1.36-1.68M, shared VM): treat the ratio as ~1.8-2.0x, not 2.0x exactly.

## Strength (PRELIMINARY: 5 independent seeded runs of 24 games, 5+0.05, Hash 32, 1 thread, 2 concurrent games, same net both sides, `openings_book.epd`)
NEW vs OLD per run: 12-9-3 (68.8%), 6-16-2 (58.3%), 16-7-1 (81.2%), 8-12-4 (58.3%), 12-11-1 (72.9%) (W-D-L).
Pooled 54W-55D-11L / 120 = **67.9%, Elo +130 [+86, +179] (trinomial 95%), 5/5 runs > 50%**. This is a time-control result,
so by construction it measures only the speed difference (identical evals, identical node counts per position); it says nothing about
whether any net beats HCE. Not an SPRT. Small sample, shared VM. Logs: `tools/sd/pool_gate.py` reproduces the pooling.

## Decision
**Keep (pending review and `sprt.yml`).** Node-identical, bit-exact, +~1.9x NNUE NPS, HCE unchanged. Because it changes no
evaluation, the *only* thing it can affect is time-based play with a net; HCE remains the default.
Not claimed: any improvement for the default (HCE) engine.

## Not done / next
- `Position`-embedded accumulators updated in `make()` would be cheaper still on large diffs; not needed to remove the handicap and would touch `board.rs`.
- Explicit AVX2 intrinsics for the output layer and i16 accumulators (halves bandwidth); would need a saturation analysis to stay bit-exact.
- Re-run every existing net-vs-HCE gate (E, G stage-0, H, A's 500k, R's 10M) with this build: their NPS handicap is gone, so some verdicts could move.
