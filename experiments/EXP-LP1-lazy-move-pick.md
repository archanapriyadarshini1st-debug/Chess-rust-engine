# EXP-LP1: lazy stable move picking in `search.rs` - NEGATIVE / NOT PROMOTED

- **Experiment ID:** EXP-LP1
- **Responsible agent:** LP (new session, owner's Composio connection). This PR is docs + one tool; no `src/` change.
- **Repository / baseline:** `archanapriyadarshini1st-debug/Chess-rust-engine` `main` @ `73d0379` (HCE default).
  Baseline binary sha256 prefix `563cd2a342cf3b20`, `bench 10` = **553783** nodes (same as IR's and G4's reproduction).
- **Candidate:** same tree + one change in `src/search.rs` (not included here, because it is rejected).
  Candidate binary sha256 prefix `fcf190d5dbeebb8a`, `bench 10` = **553783** nodes.
- **Hardware:** 4 vCPU, 3 GB RAM, AVX2/AVX-512 flags, shared VM, **no PMU** (`perf_event_open` -> ENOENT).
  rustc/cargo 1.100, `.cargo/config.toml` as on main (x86-64-v2), `lto=true`, `codegen-units=1`.

## Hypothesis
IR's profile (gprofng, `bench 13`, #71 stack) attributes ~17% of CPU to `sort_moves`. It scores every move up front
(SEE per capture, history + 2x continuation history per quiet) and then runs an O(n^2) insertion sort over all ~35
moves, although most nodes cut off on the TT move or the first capture. Lazy selection should save work at cut
nodes and raise NPS **without changing a single searched node** (order-exact), which is verifiable by node identity.

## Change (stage 1, order-exact)
`score_moves()` fills the scores once; `pick_move(i)` finds the **earliest** maximum in `i..n` and rotates it to slot
`i`, so the relative order of the remaining moves (and tie-breaking) equals the old stable insertion sort.
Both call sites (`qsearch`, `search`) use `pick_move` instead of `moves[i]`.

## Correctness evidence (all passed)
| check | result |
|---|---|
| `cargo test --release` (perft, NNUE parity/incremental, fifty-move mate, eval params) | 22 passed, 0 failed |
| `bench 10` (candidate x5, base x2) | 553783 every run, both binaries |
| `bench 12` | 1,275,032 nodes for both binaries |
| fixed-depth audit, 14 positions (startpos, kiwipete, pos3, pos4, pos5, middlegames, KPK, rook endings, promotions, check-heavy), Threads=1, Hash=16, compare bestmove + score + nodes | depth 9: **14/14 identical** (321,203 nodes); depth 12: **14/14 identical** (1,511,307 nodes) |

The change **is** order-exact. The open question was only whether it is faster.

## Speed evidence (this decided it)
Interleaved A/B, order alternated each round, pinned with `taskset`:

| method | base | cand | reading |
|---|---|---|---|
| single unpinned `bench 10` readings (my first look) | 1.016-1.024 M nps | 1.097-1.183 M nps | looked like +8%; **it was noise** |
| 5 interleaved pairs, `bench 12`, unpinned (NPS) | median 1.062 M | median 0.952 M | -10.3%, cand lower in 5/5 pairs |
| 7 pinned pairs, `bench 10` (NPS) | median 1.097 M | median 1.110 M | +1.2% |
| 5 pinned pairs, `bench 12` (NPS) | median 1.085 M | median 0.997 M | -8.1% |
| min of 14, wall time `bench 11` | 1.126 s | 1.197 s | cand 6.3% slower (includes ~0.5 s start-up) |
| 60 pinned runs, wall time `bench 9` | min 0.630, p10 0.722, median 0.879 s | 0.634, 0.744, 0.890 s | cand 0.7% / 3.1% / 1.3% slower |
| 40 pinned runs, engine-reported search time `bench 10` (`tools/bench_minp.py`) | min 0.329, p10 0.378, p25 0.460, median 0.526 s | 0.356, 0.396, 0.453, 0.558 s | ratios 1.082 / 1.048 / 0.985 / 1.062 |

**Same-binary noise:** the base binary alone measured 913,833 .. 1,344,133 nps over 7 pinned `bench 10` runs
(about +-19%). Single-shot or 5-sample NPS comparisons on this class of VM are smaller than their own noise.
No row supports a speedup once noise is controlled; most rows have the sign of a small regression.

**Decision: REVERT. Not promoted, no source PR.** (Rule 9.4: a performance change must be demonstrably faster,
not merely correct.)

## Why it did not help (analysis; not proven with a profiler)
1. The 17% attributed to `sort_moves` is dominated by **scoring** (`see_ge`, `quiet_hist` with two continuation-history
   loads), which stage 1 leaves untouched, not by the sort itself.
2. `see_ge` already has the standard early exits (`score < 0`, `score - attacker >= 0`), so good-capture scoring is cheap.
3. At non-cut nodes (PV, all-nodes, heavy LMR) the rotate + rescan per pick is the same O(n^2) with worse constants,
   which cancels the gain at cut nodes.

## Stage 2 (also negative): defer scoring of quiets until noisy moves are exhausted
Captures/promos score >= 1.49 M, killers/counter/quiets <= 0.9 M, TT move 10 M, so classes are strictly separated.
It is **not** order-exact: quiet scores read shared history tables that child nodes update between initial and
deferred scoring. Measured `bench 10` = **503,061** nodes (vs 553,783: a behaviour change that would need SPRT) and
NPS 0.89-0.94 M vs ~1.1 M (lower). Dropped without a strength test since there is no speed to trade against the
behaviour change. If someone wants it, do a real staged picker (TT -> good captures -> killers -> quiets -> bad
captures) and test at fixed nodes **and** SPRT, rather than patching the sorter.

## Review note: persisted `ThreadData` across `go` (PR #36 area) - no defect found
`uci.rs`: `ucinewgame` waits for the search, clears the TT, drops the persisted `ThreadData`, resets game history; each
`go` re-seeds `td.hash_hist` from `moves_played`; `prepare()` swaps in the current TT/time manager, so `setoption Hash`
between moves is safe. History tables intentionally survive within a game. Not covered: a GUI that never sends
`ucinewgame` (stale history would affect ordering only, not legality).

## Lessons for other agents
- Do not accept NPS wins from fewer than ~40 interleaved, pinned, low-percentile samples. My own first reading was
  +8% and wrong; my 5-pair reading was -10% and also wrong in magnitude. Use `tools/bench_minp.py`.
- `bench` has a ~0.5 s fixed start-up (attack tables); wall-clock ratios of short benches are diluted. Compare the
  engine-reported search time, as `bench_minp.py` does.
- Node identity is necessary, not sufficient, for a performance change.
- Remaining NPS levers per IR are NNUE inference (`eval_cached_avx2` ~22%) and **scoring cost**, not sorting.

## Artifacts
`tools/bench_minp.py` (added in this PR). The identity audit is the same idea as #33's `perf_equiv.py` and #37's
node-identity tool, so no third copy was added. **No Elo claim of any kind is made by this record.**
