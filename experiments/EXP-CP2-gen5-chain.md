# EXP-CP2: gen-5 distill -> self-play -> relabel -> retrain turn (pre-registered)

Responsible agent: CP. Branch `cp/g5-chain`, based on `agentG4/gen4` @ the sha recorded in the commit (tools/ch, tools/sd,
tools/teacher come from that branch; `src/` is untouched, so the engine under test is exactly the one G4 used).
Workflow: `.github/workflows/g5-chain.yml` = G4's chain with a one-turn shift (derived by scripted text replacement, no logic changes
to the mix / relabel / train tools).

## Hypothesis
G4 (run 43427896067) beat its parent CH 145-77-278 / 500 = 56.8 % (5/5 replicates > 50 %, A/A 52 %) and scored 55.0 % vs 48.3 %
for CH against SF19 UCI_Elo 3000 (n=200 each, preliminary). If that is a property of the loop (self-play by the current net ->
SF19 d12 labels -> cumulative data) rather than luck, repeating the turn with G4 as the self-play net should beat G4 again.

## Change (one variable: the generation)
- Self-play net: G4 net (artifact `g4-net`, run 43427896067, sha256 prefix 1bcaff62d74b4927), depth 7, 5 shards x 70 min, seed 5.
- Teacher: Stockfish 19 (sha256 0f83d24cc46d2c66...), fixed depth 12, same relabel tool as G4/CH/TL (unmodified).
- Training mix: A = TL 4 parts (5M) + CH 4 parts (5M) + G4's own labelled 8 parts (10M); B = new gen-5 labels (10M). Total ~30M, the same
  size G4 trained on (memory/time validated), but with more weight on newer, on-policy positions.
- Holdouts: TL, CH, G4 and gen-5 labelled hold_sub samples are ALL excluded from training (game-disjoint).
- Last-known-good = G4 net. NEW = G5 net.

## Decision rule (fixed before any game is seen; same as G4's)
G5 REPLACES G4 iff all hold: pooled NEW-vs-LKG >= 52 % over 5x100 games with LOS >= 97.5 %; >= 4/5 replicates > 50 %; the A/A control is inside
its CI of 50 %; and NEW's SF19 UCI_Elo 3000 score (2x100) is not lower than LKG's. Otherwise keep G4. A negative result is recorded here.
If the gate passes, the net still has to pass `ship-gate.yml` on the integrated engine stack (#71 lineage) before it is embedded anywhere.

## Possible regressions / why it might fail
- Distribution shift: G4-net self-play is narrower than HCE self-play; the net may overfit its own style (watch SF-3000 score and the holdout MSE on TL/CH sets).
- Diminishing returns: gen-3 -> gen-4 gave +47 Elo; gen-5 may be smaller than the 5x100 gate can resolve (about +/-17 Elo noise floor per 600 games).
- 1-thread / 64 MB / 10+0.1 only; no claim about other settings.

## Execution plan
1. smoke (plumbing only, no strength claim): shards 2, gen 5 min, relabel 2, depth 10, train 6 min, 10 games.
2. full run with the defaults above (~9 h wall clock).

## Results
(to be appended by the first reader: run ids, pooled numbers, decision)
