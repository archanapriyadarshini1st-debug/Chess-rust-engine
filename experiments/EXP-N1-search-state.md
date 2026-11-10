# EXP-N1: search state that was being thrown away, and a corrhist that hurt

Agent N. Touches: `src/search.rs` (new `ThreadData::prepare`, bounded corrhist), `src/uci.rs`
(one persistent `ThreadData` per game), `tools/ab_fixed_nodes.sh` (harness). No eval, NNUE, data or workflow change.

## Defects found on `main` (d28cfe3 / 7793ad7)
1. `uci.rs` built a fresh `ThreadData` on every `go`: history, capture history, continuation
   history, counter moves and corrhist were discarded before every move.
2. The pawn corrhist (`gravity(.., diff*depth/8)`, applied as `/32`) can move static eval by
   +-512 cp, and learns from fail-low/fail-high bounds as if they were exact scores.
3. (not shipped, see below) `iterative_deepening` compared `td.best` with the PV it was just
   assigned from, so `stable` always grew and the "unstable best move: think longer" branch was dead.

## Fix
- One `ThreadData` per game (`prepare()` resets killers/PV/stacks/nodes only). Saved before
  `bestmove` is printed (no race with the next `go`), cleared on `ucinewgame`. `bench` is unaffected
  (it builds its own td), so only the corrhist change moves bench nodes.
- Correction history: bounded EMA of `(search score - raw eval)`, fixed point (x16), hard cap
  `CORR_MAX = 24 cp`, skipped when the result is inconsistent with its bound (fail-low can only
  say "eval too high", fail-high only "too low"), when best move is a capture/promotion, in check, or mate score.

`bench 8`: 178914 -> 177224 nodes (expected: corrhist is now bounded). perft + unit tests green.

## Evidence (all local, 4 vCPU, fastchess 1.8.3-alpha, `tools/openings_book.epd`, colours reversed,
`Hash=16 Threads=1`, `-srand 7`; fixed-node = `nodes=25000` both sides)

| test | games | result (test vs reference) | Elo +- 95% |
| --- | ---: | --- | --- |
| `main` with corrhist disabled vs `main` | 206 | 166-12-28 | **+336 +- 55** |
| persistent tables vs fresh-per-move (corrhist off in both) | 460 | 202-97-161 | **+80.7 +- 24.2** |
| persistent + OLD corrhist vs corrhist off | 206 | 18-143-45 | -250 (SPRT H0) |
| persistent + bounded corrhist cap 24 vs off | 800 | 239-224-337 | +6.5 +- 18 (neutral) |
| persistent + bounded corrhist cap 48 vs off | 800 | 225-246-329 | -9.1 +- 17 (neutral) |
| **this PR vs `main`, real clock 5+0.05, 3 games in parallel** | 120 | **119-1-0** | not meaningful as an Elo number |

Reading the table honestly:
- The old corrhist gets *worse* the longer it lives (-250 once persisted). It is a bug, not a tuning problem.
- A pawn-keyed corrhist is **neutral** within noise (24 vs 48 cp: +6.5 and -9.1, both CI ~+-18). It is kept only because it can no longer hurt; the point of this PR is the two defects above, not corrhist Elo.
- The real-clock row is self-play against a *crippled* baseline at the repo's minimum TC. Every game ended by
  score adjudication (no time losses/crashes, mean 73 plies). Self-play Elo is inflated and a 119-1 score has no usable
  Elo conversion. Use it as "the old behaviour was very wrong", not as strength. The number that matters is vs
  Stockfish 19 (see the thread; K's ruler should be re-run on this build).

## Not shipped: time-management patch (kept as `experiments/EXP-N1-time-mgmt.patch`)
Fixes defect 3 and scales the soft limit by best-move stability x node fraction of the best root move x score drop,
plus an early exit when there is one legal move. Real-clock 5+0.05, patch vs same build without it:
**20-19-43 over 82 games, +4 +- 52 Elo**. That is inconclusive, so by the pre-registered rule it is not merged.
It needs a proper `sprt.yml` run (10+0.1, [0,10]); anyone may take it.

## Reproduce
```
cargo build --release && cp target/release/chess-rust-engine /tmp/test
git checkout <base> && cargo build --release && cp target/release/chess-rust-engine /tmp/base
tools/ab_fixed_nodes.sh /tmp/test /tmp/base 400 25000 -3 3     # needs /tmp/fastchess
```
