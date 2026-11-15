# EXP-TL1 - Stockfish 19 MAX teacher scores on the SD1 positions (Agent TL)

Status: **pre-registered, no game played yet.** Written before any result exists; the rule below may not be edited after the first gate game.

| field | value |
|---|---|
| Experiment ID | EXP-TL1 |
| Responsible agent | TL (owner's Composio connection as `archanapriyadarshini1st-debug`; not A, B, nor any earlier lane) |
| Repository | `archanapriyadarshini1st-debug/Chess-rust-engine` (authoritative), branch `agentTL/sf19-relabel` |
| Baseline commit | `41422e1` (`agentSD/selfdistill-on-ni`; engine = #52 incremental NNUE; HCE `bench 10` = 553783). `main` = `581b8ee` |
| Baseline net (last-known-good for this experiment) | SD1 `net.bin` sha256 `a598bf2f3247...` (artifact `sd-net`, run 43035169390) |
| Teacher | Stockfish 19 (`sf_19` universal), binary sha256 `0f83d24cc46d2c66c60f16001af5444873bc112b7d028594513426894c12da19` (same as KB1), `UCI_LimitStrength=false`, 1 thread, 32 MB hash, **fixed depth 12** |

## Hypothesis
SD1's labels are the engine's own depth-7 HCE scores. KB1 measured that the engine's losses against SF19-3000 are an *evaluation lag*
(HCE overrates the eventual loser by a median +215 cp in quiet middlegames). A net trained to reproduce HCE can at best inherit that lag.
Replacing **only** the score with a deeper, stronger teacher's score on the **same positions and game results** should reduce it.

## Change (exactly one variable)
`score` field of each of SD1's 20,000,000 training records := SF19 depth-12 score (side-to-move POV, mates +-3000).
Unchanged: positions, order, `wdl` (played-game outcome - never replaced, never invented), `lam = 0.75`, trainer (`tools/nnue/train.py`,
unmodified), 230 training minutes, architecture, engine binary, gate harness.
Teacher scores and game outcomes remain **separate supervision signals** exactly as in the target `0.75*sigmoid(score/400) + 0.25*result`.

## Why depth 12 and not a "long think"
EXP-P1 measured depth 12 explains ~95 % of the variance of a 2 s label at ~21 ms/position; 20M labels at 2 s would cost ~11,000 core-hours.
Measured here: 600 positions, 4 procs, depth 12: 176 pos/s (~22 ms/core-position), output byte-identical across two runs (reproducible).
Volume is what the earlier negative result lacked (348k labels, `A`'s EXP, lost to HCE). Hard/tactical positions are not oversampled:
this is a like-for-like replacement test, not a new data distribution.

## Known limitations (stated up front)
1. Packed records have no castling rights / en-passant / history. Castling is **inferred** from king+rook home squares, ep = none.
   Positions illegal under that reading, in check, or without a legal move are dropped and counted in the provenance JSON.
2. Stockfish's UCI centipawns are normalised differently from HCE's. The trainer's `/400` sigmoid is unchanged, so the net's output scale
   changes with it; the search margins in `search.rs` were tuned for HCE-scale scores. A strength change could therefore come partly from
   scale mismatch rather than label quality. The gate measures the *product*; if TL loses, scale is the first suspect (next experiment: rescale or WDL-space labels).
3. `wdl` in the SD1 data comes from `datagen-bin` adjudication (win: both searches >= 1000 cp for 4 plies; draw: |cp| <= 8 for 10 plies after ply 60). Unchanged here.
4. The data are the engine's own self-play positions, so SF19 judges positions *this engine reaches*; they are not SF-generated games.
5. One run = one net = one training seed. A single training seed cannot separate "label source" from training noise; the five gate replicates
   test *playing-strength noise*, not *training-seed noise*. A positive result earns a second-seed retrain before promotion.

## Measurements
- Prep asserts SD1's `raw_records=30,415,673`, `train_final=20,000,000`, `holdout_unique=757,331`, WDL mix `[8532059, 3320989, 8146952]`
  (otherwise it is not the same data and the job fails).
- Teacher agreement of **both** nets on the same 100k-position, game-disjoint, SF19-labelled holdout sample (MSE in sigmoid space, `lam` and `lam=1`).
- Gate: **TL vs SD1** (not vs HCE), 10+0.1, 1 thread, Hash 64, `tools/openings_book.epd`, colours reversed, 5 replicates x 100 + A/A (SD1 vs SD1), distinct seeds.
- Informational, same runner class and seeds: TL and SD1 each vs **SF19 UCI_Elo 3000**, 2 x 100. These are *limiter-scale* numbers, not Elo, not CCRL.
- Logged: engine/net/SF/book hashes, bench nps for HCE / TL / SD1, forfeits/illegal moves (grep PGN), raw PGN artifacts.

## Decision rule (fixed now)
**Candidate for promotion** iff all of:
1. pooled TL-vs-SD1 score >= 52 % with LOS >= 97.5 %,
2. >= 4 of 5 replicates > 50 %,
3. A/A (SD1 vs SD1) inside its own CI around 50 %,
4. downside check: TL's pooled score vs SF19-3000 is not lower than SD1's by more than the combined 95 % error of the two samples,
5. no time forfeits / illegal moves / crashes and TL `bench` nps >= 0.95 x SD1's.
Anything else: **not shipped**; recorded here as keep / revert / inconclusive with the reason. Promotion beyond "candidate" additionally needs a
second training seed, `sprt.yml` on main, and the open-PR stack decision by the owner. HCE stays the default until then.

## Possible regressions
Scale mismatch (limitation 2); over-fitting the teacher on a small tactical/quiet mix; slower play if the new net has different activation statistics (bench checks nps only, not behaviour).

## Results
*(none yet - the workflow posts them to issue #1 and this file is updated from the raw logs)*
