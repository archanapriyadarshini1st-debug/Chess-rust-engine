# EXP-RV1: second review + reproduction of #25/#26, review of #36, fuzz of merged main [Agent RV]

Repo: `archanapriyadarshini1st-debug/Chess-rust-engine`. Hardware: 4 vCPU Linux sandbox, rustc 1.99.1, `cargo build --release` (default flags), 1 thread, Hash 16.
Binaries: BASE = `52cb805`; TEST = `52cb805` + #25 + #26 (clean merge, `f23ea7b`/`6c94ae1` locally; merged upstream as `9a0ad5b`, `40faeb7`).

## Hypothesis
#25 (shared attack sets in eval, TT prefetch, popcnt) and #26 (captures-only qsearch generator) change speed only, not decisions.

## Results
| check | result |
|---|---|
| `cargo test --release` on TEST | all pass |
| node identity: 68 positions x depth 6/8/9 = 204 searches (`tools/node_ident.py`) | 204/204 identical (nodes, score, bestmove); 0 searches without an info line |
| `bench 10` x5 interleaved | nodes 553783 = 553783 every round; NPS ratio 1.169, 1.204, 1.277, 1.175, 1.013; median 1.175 |
| post-merge main `40faeb7`: `bench 10` | 553783 nodes (unchanged), tests green |

Decision: **keep** (merged). No Elo claim. Shared-VM NPS noise is large (ratio spread 1.01-1.28); the node-identity result is the real evidence, the speed number is indicative.

## #36 (persist-hist), read-only review
`ThreadData::prepare` resets every per-search field of `ThreadData` (nodes, seldepth, killers, pv, pv_len, eval_stack, best, score, check_nodes, stack_pc/to, root_depth, ply_move, hash_hist). Persisted: `history`, `cap_hist`, `cont_hist`, `counter` (intended). `silent` persists but only `bench` sets it. Singular-excluded move is an argument, not state, so it cannot leak. `ucinewgame` clears the persisted box; the state is stored before `bestmove` is printed. No defect found. Strength of #36 is N's/A's SPRT, not this record.

## Robustness fuzz of merged main (`tools/uci_fuzz.py`)
5 seeds x 150 `go` commands (movetime 20/50/100, wtime/btime 0.3/1/3 s + inc, depth 3/6/8, infinite+stop; ucinewgame mid-game; Hash 1/4/16/64 changes; random FEN jumps without ucinewgame); every bestmove validated with python-chess.
Result: 750 `go`, **0 illegal, 0 hang, 0 crash, 0 clock overrun, 0 stderr lines.**

## Harness pitfall (recorded so nobody repeats it)
This engine treats stdin EOF as `stop`. Piping `position ...; go depth N` and closing stdin yields aborted searches with no `info` lines; a comparison of two such runs reports "identical". My first run did exactly that (204 "identical", 0 real). Fixed in `node_ident.py`.

## Not tested
Strength (no Elo claim), Lazy SMP, NNUE paths, non-x86 targets, Windows.
