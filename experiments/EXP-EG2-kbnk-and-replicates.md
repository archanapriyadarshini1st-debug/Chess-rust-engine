# EXP-EG2: KBNK corner term (new, default-off) + independent 5-replicate downside check of #48

- **Experiment ID:** EXP-EG2
- **Responsible agent:** EG2 (same owner account; see issue #1)
- **Repository / baseline:** `archanapriyadarshini1st-debug/Chess-rust-engine`, `main` @ `40faeb7` plus PR #48 head `01d4dc9`. This PR is **stacked on `agentEG/endgame-scaling`**, not on main.
- **Binary:** `engine_pr48` sha256 prefix `a582d65de1ad3849` (this branch, `cargo build --release`, default flags = `target-cpu=x86-64-v2`). Pristine `main` build sha256 prefix `4d3b1bbc62d96479`. Bench 10: main 553783, `EndgameScale=0` 553783 (identical), `=3` 490573 (== #48), `=7` 490573 (bench has no KBNK position).
- **Hardware:** shared 4-vCPU / 3 GB cloud sandbox, Linux. Timing-sensitive numbers (NPS, the 3+0.03 KBNK games) are noisy; fixed-node games are not affected by load.
- **Stockfish:** not used anywhere in this experiment. No external data, no net.

## Hypotheses (written before the runs)
1. **H1 (hole):** the HCE gives K+B+N vs K no guidance (mop-up knows only majors and needs <=4 men with a major), so the engine cannot convert KBNK inside the 50-move limit.
2. **H2 (downside check of #48):** `EndgameScale=3` (50-move damping + material draw scaling, #48's default) does not lose strength in normal play.

## Change
`src/endgame.rs`: `KBNK = 4` bit and `kbnk_bonus()`: exactly four men (K+B+N vs K), bonus `(14 - d_corner)*12 + (7 - king_dist)*10` towards the two corners of the bishop's colour, signed for side to move, 0 for all other material. `set_mask` clamps 0..7. `src/uci.rs`: option max 3 -> 7. Default mask unchanged (3). Bit 4 is **off by default**.

## Testing configuration
- **KBNK:** `tools/gen_kbnk_positions.py` (seed 20261111) -> `experiments/EXP-EG2-data/kbnk.epd`, 50 random legal KBNK positions, white to move, black not in check. Same binary: `EndgameScale=4` vs `EndgameScale=0`, both colours per position (100 games), tc 3+0.03, 1 thread, Hash 16, fastchess 1.8.3-alpha, concurrency 4. Success = the strong side mates before the 50-move rule.
- **Downside:** same binary, `EndgameScale=3` vs `0`, 5 replicates x 300 games, fixed `nodes=25000`, disjoint slices of `tools/openings_book.epd` (`start=115*i`, 150 rounds x 2), colours swapped, `-srand i`.
- A/A control (earlier variant, same harness, identical settings on both sides): 300 games, exactly 50.00%, every pair 1-1. **This only shows there is no colour/harness bias.** Fixed-node play is deterministic, so it says nothing about noise.

## Results
**KBNK (preliminary, 100 games, 3+0.03):**
| run | binary | strong-side conversions with term | without term |
|---|---|---|---|
| 1 | standalone variant of the same term | 50/50 | 12/50 (24%) |
| 2 | **this branch**, `EndgameScale=4` vs `0` | 50/50 | 13/50 (26%) |
Zero position pairs where the term did worse. In run 2 the fastchess pair record was Ptnml [0,0,13,37,0].

**Downside check of #48 default (`EndgameScale=3` vs 0), fixed 25k nodes:**
```
R1: 300 games W-D-L 80-124-96 score 47.3%
R2: 300 games W-D-L 90-129-81 score 51.5%
R3: 300 games W-D-L 85-137-78 score 51.2%
R4: 300 games W-D-L 87-125-88 score 49.8%
R5: 300 games W-D-L 85-134-81 score 50.7%
POOLED 1500 games W-D-L 427-649-424 score 50.10% CI95 [48.19,52.01] Elo 0.7 [-12.6,13.9]
NPS ratio mask3/mask0 (8 interleaved bench 12): mean 0.989 median 0.992 min 0.879 max 1.080
```
Earlier run of my own variant (mask 3 + KBNK equivalent, 5 x 300): pooled 1500 games 51.0% [49.1, 52.9], replicates 49.0 / 53.3 / 52.8 / 49.3 / 50.5.

An NPS bug I found and fixed along the way: my first variant computed ~12 popcounts per eval and was 2-8% slower in all 5 paired benches. A cheap early exit fixed it with identical results (equivalence test + identical node counts, 1391237 nodes at depth 12 for both versions). #48 avoids this with its ">12 men" guard, so nothing to port.

## Statistical confidence / what is NOT claimed
- Both 1500-game blocks are consistent with 0 Elo (CI about +-13). **No regression detected, no gain demonstrated.** The sign flips between replicates (47.3% to 51.5% on the #48 variant), which is what noise looks like at 300 games.
- Fixed nodes do not price NPS; the real-time cost was measured separately (mean ratio 0.989, range 0.88..1.08 over 8 interleaved pairs, within sandbox noise).
- KBNK conversion is rare in real games. This is a correctness/hole fix, **not an Elo claim**. Preliminary until a real-time SPRT with `option.EndgameScale=7` vs `3` is run (it will almost surely read INCONCLUSIVE because KBNK barely occurs; the point of that run is only to prove it is non-harmful).

## Decision
- KBNK bit: **keep (default-off)**. Measured hole, zero harm detected, inert outside KBNK.
- #48 default (mask 3): **inconclusive** on this evidence. Not a regression at fixed nodes, no proven gain. Recommend default 0 until the real-time SPRT replicates in #48 finish.

## Reproduce
```
python3 tools/gen_kbnk_positions.py   # writes kbnk.epd
fastchess -engine cmd=./engine name=K4 option.EndgameScale=4 -engine cmd=./engine name=K0 option.EndgameScale=0 \
  -each tc=3+0.03 proto=uci option.Hash=16 -openings file=kbnk.epd format=epd order=sequential \
  -rounds 50 -games 2 -repeat -concurrency 4
```
