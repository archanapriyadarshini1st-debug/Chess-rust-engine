# EXP-Z1: `datagen-bin`, a multi-threaded, game-id'd, adjudicated self-play generator (Agent Z)

**Status:** infrastructure. **No Elo claim.** Search (`search.rs`), eval, NNUE inference and `board.rs` are untouched;
`bench 8` / `bench 10` = **178914 / 469049**, identical to `main`. The legacy `datagen` subcommand is untouched
(its only change is `fn load_openings` -> `pub(crate)`), so its output stays bit-identical.

## Why (what the thread already established)
* EXP-I2: the trainer's validation split is `hash(position) % 50`; neighbouring positions of one game land on both sides,
  so val loss is optimistic and nets memorise games. Fix needs a **game id** per record. Records had none.
* Data volume is the open lever (teacher set = 348k labels, 74% draws; M's scale test needs 1M -> 20M+ shard-disjoint positions).
* Legacy `datagen` (text `fen | cp | wdl`, 1 thread) needs a separate conversion step, and has three quality problems found by reading it:
  1. every search starts with an **empty `hash_hist`** (the UCI path sets it), so repetitions inside the game being played are invisible;
  2. a new `ThreadData` (~1.3 MB of history tables) is allocated **per move**;
  3. games with no result after 160 plies are labelled **draw**, and there is no score adjudication, so long games dominate the cost.

## What it does
`chess-rust-engine datagen-bin <positions> <depth> <out.bin> [threads]`
* N worker threads, own TT each, one `ThreadData` per game; game history passed to the search.
* Writes the trainer's **28-byte record directly** (`tools/nnue/train.py` layout) + `<out>.gid` (u32 game id per record) + `<out>.meta.json` (provenance).
* Ends games on mate / stalemate / 50-move / insufficient material / 3-fold. Adjudicates (win: both searches >= 1000 cp for 4 plies;
  draw: |cp| <= 8 for 10 plies after ply 60; `CRE_DATAGEN_ADJ=0` disables). **Unfinished games are discarded, not labelled draws.**
* Opening balance filter (first search within +-450 cp, `CRE_DATAGEN_BAL`), 2-5 random scramble plies from the 595-position book + legacy list.
* `CRE_DATAGEN_SEED` per shard, `CRE_DATAGEN_NODES` optional node cap. Same seed + 1 thread + fixed depth is **byte-identical** (tested).
* Same net-aware behaviour as the engine: with `CRE_NNUE_FILE` set and `UseNNUE` on, games are played with the net (generation N+1 data).

## Measured (4 vCPU, depth 7, HCE; seed 1)
| generator | threads | positions/s |
|---|---|---|
| legacy `datagen` | 1 | 411 (3000 pos / 7.3 s) |
| `datagen-bin` | 1 | 467 (3026 pos / 6.5 s) |
| `datagen-bin` | 4 | **1852** (12153 pos / 6.6 s), 3.97x scaling |

Caveat, stated plainly: the 1-thread gain is **not** a clean A/B of one change, because adjudication also changes the workload (shorter games).
What is solid: 4-thread scaling is ~linear, no conversion step, and labels are different:
stm-POV W/D/L = **37% / 23% / 40%** (4550 / 2805 / 4798) vs 74% draws in the 500 ms teacher set.
The WDL difference is a *consequence of adjudication thresholds*, not evidence that the labels are better; whether `lam` < 1 helps is a training question.

## Verified
* `cargo test --release`: perft suite, nnue tests and 3 new tests (record layout hand-computed from `label_self.py::pack`, pack/unpack round trip,
  byte-reproducibility + game-id contiguity + no record with the mover in check).
* Independent Python `struct("<Q16sBhB")` decode of 12,153 records: 0 malformed (popcount(occ) == used nibbles, padding zero, wdl <= 2).

## How to use it for the game-disjoint split
`gid` is unique per game across all threads in one run. For multi-shard runs use a distinct `CRE_DATAGEN_SEED` per shard and
hold out **whole shards** (or `gid % K`, computed per shard) for validation. Never split by position hash.

## Not claimed / open
* Not tested: that more data makes a net beat HCE (M's lane). This only removes the generation bottleneck and the leak.
* Adjudication thresholds are conventional, not tuned. A/B them on net strength before trusting them.
* Positions are still 'quiet best-move' filtered at the root only; leaf-distribution mismatch (EXP-I2 guess) is not addressed.
