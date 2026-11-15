# EXP-G5 - gen-5 turn of the SF19-labelled data flywheel (Agent CN)

Status: **pre-registered before any result exists.** The decision rule below may not be edited after the first gate game.

| field | value |
|---|---|
| Experiment ID | EXP-G5 |
| Responsible agent | CN (owner's Composio connection as `archanapriyadarshini1st-debug`) |
| Repository / branch | `archanapriyadarshini1st-debug/Chess-rust-engine`, `agentG5/gen5` = `agentG4/gen4` @ `667628386453` + this record + `.github/workflows/g5-chain.yml` + `.github/g5-params.json`. `src/` untouched. |
| Baseline net (last-known-good) | **G4 net**, sha256 `1bcaff62d74b4927...`, artifact `g4-net`, run 43427896067 |
| Teacher | Stockfish 19 `sf_19` universal, sha256 `0f83d24cc46d2c66...`, `UCI_LimitStrength=false`, 1 thread, fixed depth 12 (same as TL/CH/G4) |

## Evidence that motivates it (all from run logs, recomputed with trinomial stats)
* G4 run 43427896067 completed all 9 hours; only its `report` step failed (a reporting error, not a training or gate error), so no result was ever posted. Job-log gate results: G4 vs CH 5x100 = **145-77-278 (W-L-D)** = 56.8%, Elo +48 [+27,+68], LOS 100%, replicates > 50%: 5/5; A/A 16-12-72 (52.0%, inside its CI). By its own pre-registered rule G4 replaces CH.
* Informational vs SF19 UCI_Elo 3000: G4 69-49-82 (55.0%, n=200) vs CH 51-58-91 (48.2%, n=200).
* Independent check by CN (this session, local, same #71 stack binary, fixed 25k nodes, only the net differs): CH vs 964d07 = 347-238-215 over 800 games (56.8%, Elo +48 [+27,+69]); see EXP-CN1.
* Each turn of the loop so far gave a positive step: SD1 -> TL (+307), TL -> CH (+130), CH -> G4 (+48). The steps shrink; whether turn 5 is still positive is the question.

## Hypothesis
Self-play by the G4 net (a distribution one generation stronger than CH's), labelled by SF19 MAX d12 and **added** to the cumulative SF19-labelled data, makes a net that beats G4.

## Change (data only)
Train mix = TL 4 parts (~5M) + CH 4 parts (~5M) + **G4's 8 SF19-labelled parts (~10M)** + new G5 positions (~10M) = ~30M (same size as CH/G4, memory-bound). `train.py`, `relabel_records.py`, `mix_records.py`, lam 0.75 and 230 min unchanged. `wdl` is never invented; `score` is SF19's only. **All four** game-disjoint holdout samples (TL, CH, G4, new) are removed from training by `mix_records.py` (position-identity hash).

Deliberately dropped from the old mix to keep the size: TL 4 of 8 parts, CH 4 of 8 parts. This changes composition, not volume. Possible downside: older HCE-distribution positions are diluted; check via the TL/CH holdout MSE in `holdout_teacher.txt`.

## Test configuration
G5 vs G4 net, same binary, only `CRE_NNUE_FILE` differs, 10+0.1, Hash 64, 1 thread, `tools/openings_book.epd`, colours reversed, 5 replicates x 100 games + A/A (G4 vs G4). Informational: each net vs SF19 UCI_Elo 3000, 2 x 100.

## Decision rule (fixed now)
G5 **replaces G4** as best-known net iff ALL: (1) pooled G5-vs-G4 >= 52% with LOS >= 97.5%; (2) >= 4 of 5 replicates > 50%; (3) A/A inside its CI of 50%; (4) G5's SF19-3000 score not lower than G4's by more than the pair's combined 95% error. Otherwise G4 stays and the result is recorded here unedited. A `smoke=true` run proves plumbing only. **Promotion into `nets/default.nnue` is NOT part of this experiment**: it needs the #71-stack fixed-node A/B and the 5-replicate ship gate.

## Possible regressions
Diminishing returns / dilution; the self-play engine is the same HCE-era search as G4's (so data distribution comes from a weaker search than the #71 stack); 100-game replicates are noisy (pooled n=500 resolves ~+25 Elo).

## Results
Filled by the workflow comment on issue #1 and copied here verbatim afterwards.
