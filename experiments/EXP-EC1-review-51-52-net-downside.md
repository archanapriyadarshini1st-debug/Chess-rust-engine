# EXP-EC1: independent review of #51 and #52, SD1-net endgame downside check

- **Agent:** EC (new session, same owner's Composio/GitHub connection). Touches no `src/`, no workflows.
- **Repository / baseline:** `archanapriyadarshini1st-debug/Chess-rust-engine`, `main` = `581b8eef45a0d3298d9229c900173ea15a85555f`.
- **Heads reviewed:** #52 `agentNI/nnue-incremental` = `f87e85de7fd2ab885d55e716af8af71dc0479cd2`; #51 `agentFN/mate-beats-fifty-move` = `8a1a8bac7d4b744339d2a8449e49c2bebe70685d`.
- **Net:** `nets/candidates/sd1-a598bf2f.bin` from `agentPN/sd1-net`; sha256 recomputed from the git blob =
  `a598bf2f32472e34fe2ae43e9b629e1a612ddd5607b42d6e994bee99a0cf1f5d` (matches PN's `.sha256` file).
- **Hardware:** 4 vCPU / 3.9 GB Linux sandbox, cargo 1.99.1, `cargo build --release` (profile as in `Cargo.toml`, no `target-cpu=native`).
- **Binary sha256 (first 16 hex):** main `4d3b1bbc62d96479`, #52 `1bfcc039f2599cad`, #51 `81d52d42bfb46b53`.
- **Scope:** correctness + node-identity + throughput + downside. **No strength (Elo) claim is made here.**

## Hypotheses

1. H51: #51 changes decisions only at `halfmove >= 100` while in check; elsewhere it is node-identical. It fixes a real missed mate.
2. H52: #52's incremental accumulator is bit-exact vs main's from-scratch NNUE evaluation (same score, nodes, bestmove) and faster.
3. H-net: the SD1 net has no catastrophic endgame-conversion downside versus HCE.

## Results

### H51 (#51): confirmed
- `cargo test --release --test fifty_move_mate`: 4/4 pass.
- `bench 10` = **553783 nodes**, identical to main (HCE).
- Independent position (not from the PR's tests): `6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 99 80`, `go depth 6`.
  - main: `score cp 567 ... bestmove h2h4` (**misses mate in 1**; Ra8# is scored as a fifty-move draw).
  - #51: `score mate 1 ... pv a1a8 bestmove a1a8`.

### H52 (#52): confirmed, with the SD1 net loaded (`CRE_NNUE_FILE`)
- `bench 10`: main **465476** nodes, #52 **465476** nodes, three runs each (stable).
- NPS, 3 runs per arm on this box: main 788k / 803k / 864k, #52 1.42M / 1.53M / 1.62M, **~1.85x**.
  Same box, HCE `bench 10` is ~1.5-1.8M NPS, so with #52 the NNUE path is roughly at HCE speed instead of half of it.
- Search identity through real UCI (stdin held open until `bestmove`; each comparison asserts an `info depth N` line was seen):
  - 5 disjoint random slices x 16 positions of `tools/openings_book.epd`, depth 9: **80 positions, 0 differences** (score, nodes, bestmove).
  - 10 perft-suite positions (Kiwipete, positions 3-6, promotions, en passant, castling rights, underpromotion race) at depth 7 / 10 / 12: **0 differences at each depth**, nodes 490539 / 795285 / 1616038 on both.

### H-net: no catastrophic downside (PRELIMINARY: n = 10 starts per cell, 50 ms/move, seed 7)
`tools/endgame_conversion.py`: engine plays both sides from random legal won endgames; counts checkmates within 200 plies.

| ending | HCE mated | net mated | mean plies HCE / net |
|---|---|---|---|
| KQK | 10/10 | 10/10 | 13 / 18 |
| KRK | 10/10 | 10/10 | 24 / 24 |
| KBBK | 10/10 | 10/10 | 31 / 36 |
| KBNK | 4/10 | 2/10 | 50 / 41 |

KBNK is weak for **both** evaluations (pre-existing; EG2/#49 owns that lane). 2/10 vs 4/10 is not distinguishable at n = 10.
The net is a few plies slower on KQK/KBBK but converts all of them.

## Limits / what this does NOT show
- No game-play strength result for #51 or #52. #52 is node-identical, so it cannot change strength except through throughput;
  the SD1-vs-HCE strength evidence (SD run 43035169390, +123 [+97, +151]) was measured on an engine that already contains NI's accumulator.
- The conversion check is a single run at tiny n; it rules out a catastrophe, not a few-percent regression.
- Nothing here approaches the owner's 80%-vs-SF19-UCI_Elo-3000 target.

## Decision
- #51: **KEEP** (recommend merge; correctness bug, node-identical on bench).
- #52: **KEEP** (recommend merge; bit-exact on 110 positions, ~1.85x NNUE-path NPS). Merging still needs a second reviewer who is not me.
- SD1 net: **no new downside found**; promotion still needs PN's SF19 measurement and the repo's ship gate.

## Reproduce
```
git fetch origin agentNI/nnue-incremental agentFN/mate-beats-fifty-move agentPN/sd1-net
git show origin/agentPN/sd1-net:nets/candidates/sd1-a598bf2f.bin > sd1.bin
(echo "bench 10") | CRE_NNUE_FILE=$PWD/sd1.bin ./target/release/chess-rust-engine
pip install chess && python tools/endgame_conversion.py ./target/release/chess-rust-engine net 0.05 $PWD/sd1.bin
```
