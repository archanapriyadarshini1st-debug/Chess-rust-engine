# EXP-H1: stage-0 net from engine self-play (Agent H)

**Verdict: NEGATIVE. Do not promote. Net loses to its own HCE: STAGE0 W-D-L 0-2-52 over 54 games (10+0.1, 1 thread, Hash 64, `openings_book.epd`, colours reversed, same binary, only `UseNNUE` differs).** Same collapse as Agent E's SF-labelled net (1-2-97), from completely different data.

## What was run (reproducible)
- Engine: `main` 6ce2055 + PR #8 (`nnue-h128`) + this PR's `datagen.rs` seed patch. Embedded net empty => HCE labels.
- Data: `CRE_SEED=1..4`, `CRE_SCRAMBLE=5,5,8,8`, `engine datagen 280000 6` x4 (depth 6, ~400 pos/s/core, 10 min on 4 vCPU). 1,120,000 positions -> `selfplay_to_bin.py` (byte-identical to `datagen_movetime.py::pack` on 3,000 FENs) -> 993,423 unique after dedupe. Results mix L/D/W = 362,889 / 271,924 / 358,610.
- Train: PR #8 `train.py` unmodified (`--lam 0.75`, hash-split val 19,828, best-val checkpoint), 15 min, 4 threads, ~130k pos/s. Best val loss 0.00874 (epoch 106); no overfitting (train ~ val).
- Gate: fastchess v1.8.3-alpha, `-tc 10+0.1 -rounds 50 -games 2 -repeat`, concurrency 3.

## Findings (all measured)
1. **Inference is correct.** PyTorch float forward vs engine `eval_nnue` on 400 held-out positions (both colours): max |diff| = 1 cp. Not an `nnue.rs` bug.
2. **Material probe passes but is not sufficient.** `tools/nnue/material_probe.py`: all 9 cases pass (net credits piece values, e.g. W up a queen HCE +1010 / net +717). E's -676 net failed it. Yet this net still loses ~97%.
3. **Where it fails (from game 1 of the gate, static evals, same position):**

| ply | white material | HCE | net |
| --- | --- | --- | --- |
| 6 (W to move) | +0 | -47 | +163 |
| 13 (B to move) | +0 | +116 | -202 |
| 14 (W to move, **a knight down**) | -3 | **-457** | **-4** |
| 16 (W to move) | -2 | -377 | +5 |
| 28 (W to move) | -2 | -314 | -10 |

   The net is blind to hanging / missing pieces in tactical middlegame positions. It plays 4.Ng5 (a piece for a pawn) and is lost by move 15.
4. **Speed is a minor factor, not the cause.** bench d9: HCE 1.16M nps vs net 0.72M nps (-38%, no incremental accumulator). That is tens of Elo, not hundreds.
5. **Val loss is not a strength signal** (confirms Agents D/E): 0.0087 here, -676 Elo there.

## Hypotheses, not yet tested
- H-a: training positions are quiet (best move not a capture, not in check, |score| < 1500). In-game leaf positions are not. The net has never been asked to price a hanging piece. Test: add positions with captures pending / material imbalance, labelled by a static or shallow-q-search teacher, then re-run the probe on `ply 14` above AND the gate.
- H-b: 4% random-move self-play almost never produces piece-down positions that survive the |score| filter. Test: histogram of |material diff| in the data (D's audit should include it).
- H-c: add the ply 14/16/28 FENs to `material_probe.py` as regression cases; they are real failures, unlike the synthetic ones.

## Not claimed
No Elo number. 54 games, one seed, one net size, one run.
