# EXP-W2 - NNUE width pilot: does capacity (H=256 / 512) beat the G4 H=128 net on identical data? (Agent W2)

Status: **pre-registered before any result exists.** The decision rule below may not be edited after the first gate game.
Result is posted to issue #1 by `.github/workflows/w2-width.yml` (machine generated, numbers copied verbatim).

| field | value |
|---|---|
| Experiment ID | EXP-W2 |
| Responsible agent | W2 (new session, owner's Composio connection as `archanapriyadarshini1st-debug`) |
| Repository / branch | `archanapriyadarshini1st-debug/Chess-rust-engine`, `agentW2/nnue-width-pilot` = `agentG4/gen4` + HW's `nnue.rs` width commit (`108fa81`, cherry-picked, unmodified) + `NN_H` env in the trainer/parity tool |
| Baseline | main `73d0379` (HCE default); last-known-good NET = G4 net, sha256 prefix `1bcaff62d74b4927`, run `43427896067` |
| Teacher | SF19 `sf_19` universal, sha256 `0f83d24cc46d2c66...`, d12, labels already on disk (TL/CH/G4 label artifacts). Stockfish is not used at runtime. |

## Why this lane
* Z9 (PR #73): same-recipe H=128 nets saturate (val 0.00705; S45 == 964d07 at fixed nodes, 0.0 +/- 21 Elo). "Capacity or data type is the lever."
* G4: the data loop compounds (+47 Elo vs CH, 5/5 replicas) but is still ~240 Elo short of the 80%-vs-SF19-3000 target. Gen-5 (CP/CN) varies the DATA. Nobody varies CAPACITY.
* HW (11-13) claimed width, pushed `agentHW/nnue-width` and then stopped: no PR, no result. This experiment finishes that lane (HW's code is used byte for byte).
* HW measured H=128 inference ~ HCE cost per node, so there is unused eval budget.

## Correctness evidence gathered before spending compute (reproducible, 4 vCPU sandbox)
| check | result |
|---|---|
| `bench 10` HW branch vs main, HCE | 553783 vs 553783 (identical) |
| `bench 10` HW branch vs main, G4 net loaded | 443140 vs 443140 (node-identical: H=128 path unchanged) |
| `cargo test --release` on the experiment branch | all pass (14+3+3+4) |
| `tools/nnue/parity_check.py` (engine vs float reference vs trainer `decode`), `NN_H`=128/256/512 | PARITY OK, worst diff 1.01 cp at every width |
| NPS cost, random nets, `bench 11`, noisy shared VM | H128 ~1.5-1.8M, H256 ~1.25-1.30M (-15-20%), H512 ~1.15M (-25%) |
Limits: the parity check proves inference == documented convention at every width; it does not exercise torch (not installable in my sandbox). The torch `Net` is width-agnostic (6 lines); the smoke run on Actions exercises `NN_H=256/512` end to end before the real run.

## Hypothesis
With identical data, an H=256 or H=512 net reaches a lower game-disjoint holdout loss than H=128, and the extra eval quality beats the 15-25% NPS loss at 10+0.1, so it beats the G4 net head to head.

## Design (ONE variable = width)
`train`: 3 parallel jobs, same 30M records, same `tools/nnue/train.py` (SCReLU, 8 material output buckets, lam 0.75, Adam, seed 1), **same wall-clock 310 min**:
`h256`, `h512`, and **`h128c` = H128 control at 310 min**. The G4 net itself trained 230 min, so `h128c` separates "more training time" from "more capacity".
Caveat that is stated now, not later: at equal wall-clock a wide net sees fewer epochs (H256 ~2x cost/epoch, H512 ~4x). If the wide net loses, it may be under-trained, not capacity-poor. Epoch counts are printed in `train.log` and reported.
`gate`: engine binary identical for all nets (same commit), only `CRE_NNUE_FILE` differs; 10+0.1, Hash 64, 1 thread, 3 concurrent, `tools/openings_book.epd`, colour-swapped pairs, `-srand` differs per replicate.
* h256, h512: 5 replicates x 100 games vs G4 net. h128c: 3 x 100 (control). A/A: G4 vs G4, 100 games (harness bias).
* Informational: each net vs SF19 UCI_Elo 3000, 2 x 100 games (G4 net: 1 x 100). UCI_Elo is a limiter scale, not CCRL.

## Decision rule (fixed now)
A candidate **REPLACES the G4 net as last-known-good** iff ALL of:
1. pooled head-to-head vs G4 >= 52.0% with LOS >= 97.5%;
2. >= 4 of 5 replicates > 50%;
3. the A/A control is inside +-4 points of 50%;
4. its informational pooled score vs SF19-3000 is not below the G4 net's by more than the pooled 95% half-width;
5. no forfeits, illegal moves or crashes in any gate log (any one = automatic reject);
6. it beats `h128c` head to head OR `h128c` is itself not better than G4 (so the gain is attributable to width, not to the longer schedule).
Otherwise: **keep G4**. A width result that fails only rule 6 is recorded as "longer training helps; width not shown".
Nothing is merged to `main` by this experiment. Promotion needs the repo's ship-gate (5 replicas on the integrated stack, SF19-3000 downside check) and a second reviewer.

## Outcome
(to be filled from the machine-generated report; negative results will be recorded as such)

## Smoke run 43683887148 (plumbing only, NO strength claim)
* Trainer ran at NN_H=256, 512 and 128 (control) on the real mixed data (12.5M records in smoke), exported nets of 401972 / 803892 / 201012 bytes; header hidden width read back as 256 / 512 / 128 by the gate job; all nets loaded (`eval_nnue` != none).
* Harness defect found and fixed before the real run: the gate's `bench (G4)` display line used `$G4` that was only exported through `$GITHUB_ENV` (next-step scope), so it printed the HCE node count (553783). The Gate step itself was unaffected (A/A candidate bench = 443140 = G4's own run). Fixed by setting the variable in the same step.
* Observation to be tested, not claimed: on the CI runner the H256 net benched ~1.53M nps vs ~2.0-2.8M for H128, i.e. width may cost more NPS there than the -15..-20% measured on random nets in the sandbox. The gate includes this cost by construction.
* Smoke game scores (4-minute nets, 10 games) are noise and are not cited.
