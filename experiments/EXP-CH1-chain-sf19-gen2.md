# EXP-CH1 - SF19-labelled NNUE-generated positions added to TL's data (Agent CH)

Status: **pre-registered before any result exists.** The decision rule below may not be edited after the first gate game.

| field | value |
|---|---|
| Experiment ID | EXP-CH1 |
| Responsible agent | CH (owner's Composio connection as `archanapriyadarshini1st-debug`; not A, B, TL, IV, GP) |
| Repository | `archanapriyadarshini1st-debug/Chess-rust-engine` (authoritative), branch `agentCH/chain-sf19-gen3`, stacked on `agentTL/sf19-relabel` @ `1c6e5e4` (tools only; `src/` untouched, engine = main `73d0379`) |
| Baseline net (last-known-good for this experiment) | TL net, sha256 `1f12a1097c7f...`, artifact `tl-net`, run 43226480499 |
| Teacher | Stockfish 19 `sf_19` universal, sha256 `0f83d24cc46d2c66...`, `UCI_LimitStrength=false`, 1 thread, fixed **depth 12** (identical to TL) |

## Hypothesis
Two independent measured facts, never combined so far:
1. SF19 d12 labels on SD1's positions made a net **+307 Elo** stronger than SD1 (TL1, 5/5 replicates), and 46.5% vs SF19 UCI_Elo 3000 (informational, 200 games).
2. NNUE-driven self-play (IV1) produced a position distribution closer to what the net actually meets: gen-2 beat gen-1 by +237 Elo, but its labels are the gen-1 net's own depth-7 scores, so label quality is capped by the net itself.

Giving the SF19 teacher the gen-2 positions and **adding** them to TL's data should (a) increase distinct-position volume (the trainer is data-limited: best epoch 121-154 on 20M), (b) add positions where an NNUE engine's evaluation errs, which HCE self-play cannot reach.

## Change (data only)
`train data = TL's 20M SF19-d12 records (unchanged, 16 artifacts of run 43226480499) + 10M IV gen-2 records relabelled by SF19 d12`.
IV's 10M = every 2nd record of IV's merged 20M train set (stride keeps shards/games evenly represented). `wdl` (played-game result) is never touched or invented; `score` is SF19's and only SF19's. Unchanged: `tools/teacher/relabel_records.py`, `tools/nnue/train.py`, lam 0.75, 230 min, architecture, engine binary, gate harness.
Memory-driven cap: `train.py` decodes the whole set to int16 arrays; 40M records would need ~13-14 GB on a 16 GB runner, so 30M is used. This is a documented limitation, not a result.

## Data integrity
* Two game-disjoint holdout samples (<=100k each): TL's `hold_sub` (from SD1 holdout) and IV's `hold_sub` (from IV holdout), both SF19-relabelled the same way.
* `tools/ch/mix_records.py` removes **every training record whose position identity (train.py's `pos_hash`) is in either holdout**, whichever source it came from (tested by `--selftest`; the hash constants are asserted equal to train.py's).
* The relabel tool drops (and counts) illegal / in-check / no-move positions; mixed teacher binaries or depths between TL and CH labels abort the run.
* Limitation: only the two <=100k samples are excluded from training, not the full SD1/IV holdouts. The evaluation uses only those samples, so the evaluation itself is clean.

## Test configuration
* h2h: CH vs TL, same binary, only `CRE_NNUE_FILE` differs, 10+0.1, Hash 64, 1 thread, `tools/openings_book.epd`, colors reversed (`-games 2 -repeat`), **5 replicates x 100 games with different seeds** + **A/A** (TL vs TL).
* Informational, not a promotion criterion: each net vs SF19 UCI_Elo 3000, 2 x 100 games.
* Teacher agreement of both nets on both holdouts (game-disjoint MSE, constant-predictor MSE for scale).

## Decision rule (fixed now)
CH **replaces TL as best-known net** iff ALL hold:
1. pooled CH-vs-TL score >= 52% with LOS >= 97.5%;
2. >= 4 of 5 replicates > 50%;
3. A/A inside its own CI of 50%;
4. no downside: CH's SF19-3000 score is not lower than TL's by more than the pair's combined 95% error.
Otherwise TL stays, and the result (including a negative one) is recorded here unedited.
A smoke run (`smoke=true`) proves plumbing only and supports no strength claim. Promotion of any net into `nets/default.nnue` is **not** part of this experiment; it needs its own PR and the EXP-LS1 gate vs HCE.

## Possible regressions to look for
* Dilution: if IV positions are of lower value than SD1 positions, the 1/3 share could lower the score vs TL.
* Over-fitting to NNUE-style positions (check: holdout MSE on TL's holdout must not worsen materially).
* Time-to-train: 30M positions in 230 min = fewer epochs per position than TL.

## Results
(filled by the workflow comment on issue #1; copied here verbatim afterwards)
