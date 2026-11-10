# EXP-S2: Lazy SMP (Threads > 1)

Agent: SMP (new session, same owner). Touches: `src/search.rs` (threading wrapper only,
no pruning/ordering/eval change), `src/uci.rs` (`Threads` option, `bench` args),
`src/main.rs`, `tests/smp.rs`. Does **not** touch `eval.rs`, `nnue.rs`, trainer, data, workflows.

## Why this lane
`Threads` was `min 1 max 1`. Every Stockfish / Reckless / Viridithas release uses Lazy SMP, and any
real match (TCEC-style, owner's "no limitation" run) gives the engine all cores. Nobody claimed it in
the thread. It is orthogonal to the net / Texel / search-patch lanes.

## Design (public technique, no copied code)
- One shared lockless TT (already XOR-verified) and one shared stop flag.
- Helpers `1..N-1` run the same iterative deepening with Stockfish-style depth skipping
  (`skip_depth`) so they desynchronise from the main thread and fill the TT.
- Only the main thread owns: book, soft/hard time decision, `go nodes` limit, `info` output.
  Helpers never stop on the soft limit; main requests stop after it finishes.
- `info ... nodes/nps` report the sum over threads (helper counters published every 2048 nodes).
- Final move = vote over threads: `(score - min_score + 14) * depth` per move, ties by score;
  a proven mate from any thread wins.
- `smp_search(threads <= 1)` calls `iterative_deepening` unchanged.

## Invariants verified (before any Elo claim)
| check | result |
| --- | --- |
| `bench 8` (Threads=1) | **178914 nodes**, identical to `main` d28cfe3 / 7793ad7 |
| `cargo test --release` | all green incl. new `tests/smp.rs` (legal moves x 2/4/8 threads x 4 FENs, mate-in-1, single-thread determinism) |
| `go infinite` + `stop` with Threads=3 | returns `bestmove`, joins cleanly |
| nps scaling, 4 vCPU box, `bench 15` | 1 thread 1.84 Mnps -> 4 threads 5.68 Mnps (3.1x) |

## What the box could NOT show
Time-to-depth on `bench 12..16` is **noisy and not a usable proxy** (the single-thread search itself
changed node count 10.4M -> 14.6M when only the hash size changed 16 -> 256 MB). Depth is not Elo.
NPS scaling is a throughput fact, not a strength claim. Strength is decided only by games.

## Pre-registered test (written before any game)
- Workflow: `sprt.yml`, `test=agentS2/lazy-smp`, `base=main`, `test_opts=option.Threads=2`,
  `concurrency=1` (so 2+1 busy threads fit 4 vCPU), `tc=10+0.1`, bounds `[0, 10]` logistic.
- Hypothesis: 2 threads vs 1 thread at equal wall-clock is clearly positive (expected +30..+70 Elo from SF/Reckless
  history; this engine's weak spot is that its TT is 1 entry/slot, so the gain may be smaller).
- **Keep iff SPRT accepts H1, or a >=750-game run has CI lower bound > 0.** If SPRT accepts H0 the code still
  merges only if Threads=1 stays bench-identical (it is opt-in), but the result is logged here as negative.
- Threads=1 must remain the default so every existing gate / ladder / ruler is unchanged.

## Known limitations / follow-ups (not in this PR)
- TT is one entry per slot with always-replace-ish policy; at 6 Mnps / 16 MB it is saturated in 5 s.
  A 3-entry bucket with depth/age replacement is the obvious next step (separate PR, separate SPRT).
- `go nodes N` is enforced on the main thread only (helpers are free).
- Shared history tables across threads are not implemented (each thread has its own, like Reckless v0.1-era).
