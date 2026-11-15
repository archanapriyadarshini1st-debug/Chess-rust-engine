# EXP-G4 - next turn of the chain: CH-net self-play -> SF19 d12 labels -> cumulative data -> gen-4 net (Agent G4)

Status: **pre-registered before any result exists.** The decision rule below may not be edited after the first gate game.
Result is posted to issue #1 by `.github/workflows/g4-chain.yml` (machine-generated, numbers copied verbatim).

| field | value |
|---|---|
| Experiment ID | EXP-G4 |
| Responsible agent | G4 (new session, owner's Composio connection as `archanapriyadarshini1st-debug`; not A/B/CH/TL/IV) |
| Repository / branch | `archanapriyadarshini1st-debug/Chess-rust-engine`, `agentG4/gen4` = `agentIV/gen2` (datagen-bin) + `agentCH/chain-sf19-gen3` (relabel / mix / gate tools). `src/` is **not** modified by this branch beyond what IV's branch already carries. |
| Last-known-good net | CH net from run `43359339220` (artifact `ch-net`) - pooled **67.9% / 500 vs TL, +130 Elo [+108,+154], 5/5 replicates**, informational 50.7% / 200 vs SF19 UCI_Elo 3000 |
| Teacher | Stockfish 19 `sf_19` universal, sha256 `0f83d24cc46d2c66...` pinned in the workflow, `UCI_LimitStrength=false`, 1 thread, fixed **depth 12** (identical to TL and CH labels, mixed depths abort the run) |

## What the evidence in issue #1 says (why this lane)
1. Biggest verified net gains so far all came from the **data**, not the architecture: SF19 labels on SD1's positions (+307 vs SD1), SF19-labelled NNUE-generated positions added (+130 vs TL).
2. Search micro-changes measured at 800-4000 games are mostly null (Q/FX/HX); the one clear positive (+43.6 Elo, NP2 stack) is being integrated by SF/CO/RS. Not duplicated here.
3. Nobody has taken the *next* turn of the loop (net -> its own self-play -> teacher labels -> better net). That is the standard flywheel of Reckless / Viridithas (self-play with the previous net, retrain) with Stockfish as the label source.

## Hypothesis
Self-play by the CH net visits positions that a ~3000-class opponent forces the net to play from, which neither the HCE-selfplay (SD1) nor the gen-2-net (IV) distribution contains. Labelling them with SF19 d12 and **adding** them to the earlier SF19-labelled sets (not replacing) raises distinct-position volume and covers the CH net's own error regions. Expected: G4 > CH.

## Change (data only)
`train data = 8 of TL's 16 labelled parts (10M, SD1 positions) + CH's 8 labelled parts (10M, IV gen-2 positions) + ~10M NEW positions` where NEW = every 2nd record of the merged CH-net self-play (5 shards x 70 min x 4 threads, depth 7) relabelled by SF19 d12.
Total ~30M = the same size CH trained on (memory-proven on a 16 GB runner), so any difference is composition, not volume. TL's share is halved (20M -> 10M) to make room; this is a documented trade-off, not hidden.
Unchanged: `tools/nnue/train.py` (H=128, 8 buckets), lam 0.75, 230 min, `tools/teacher/relabel_records.py`, `tools/sd/sd_merge.py`, gate harness, engine binary (same for both sides, only `CRE_NNUE_FILE` differs).
`score` is SF19's and only SF19's; `wdl` is the played-game result (here: game result of CH-net self-play) and is never invented.

## Data integrity
* Every datagen chunk must report `nnue_active: true` (else the job fails: it would silently be HCE data).
* `sd_merge.py`: identical-shard rejection, dedupe, game-disjoint holdout.
* Three evaluation-holdout samples (TL's, CH's, G4's; each <=100k, each SF19-relabelled the same way). `mix_records.py` removes **every** training record whose position hash appears in any of them, whichever source it came from.
* Teacher binary sha and depth must be identical across old and new labels or the run aborts.
* Limitation: only the <=100k samples are excluded from training, not the full holdouts. Evaluation uses only those samples, so evaluation is clean.

## Test configuration
* h2h: G4 vs CH, same binary, 10+0.1, Hash 64, 1 thread, `tools/openings_book.epd`, colours reversed (`-games 2 -repeat`), **5 replicates x 100 games with different seeds** + **A/A** (CH vs CH).
* Informational: each net vs SF19 UCI_Elo 3000, 2 x 100 games (same openings/seeds per net).
* Teacher agreement of both nets on all three holdout samples.
* A **smoke** run (`smoke=true`: tiny shards, d10, 5-minute train, 10 games) proves plumbing only and supports **no** strength claim.

## Decision rule (fixed now)
G4 **replaces CH as best-known net** iff ALL hold:
1. pooled G4-vs-CH score >= 52% with LOS >= 97.5%;
2. >= 4 of 5 replicates > 50%;
3. A/A inside its own CI of 50%;
4. no downside: G4's SF19-3000 score is not lower than CH's by more than the pair's combined 95% error;
5. no worse than CH on CH's own holdout sample (teacher MSE) by more than 5% relative (guards against forgetting).
Otherwise CH stays and the result is recorded here unedited. Promotion into `nets/default.nnue` is **not** part of this experiment: it needs its own PR, the HCE gate, and the integrated-engine (NP2 stack) re-test.

## Possible regressions to look for
* Dilution of SD1 positions (halved) hurting opening/early-middlegame accuracy.
* Feedback-loop narrowing: self-play positions concentrate in what the CH net already likes.
* 230 min at 30M positions = fewer epochs per position than a smaller set.

## Results
(posted by the workflow; copied here verbatim after the run)
