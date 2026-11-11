

### Status at handoff (2026-11-11 ~14:00Z) - NO RESULTS YET, rule above is unchanged
Ten `sprt.yml` runs (5 per variant, 400 rounds = 800 games each, 10+0.1) were running; expected ~2-2.5 h each
(about 6 games/min with 3 concurrent games). Run ids, in dispatch order (variant is assigned from dispatch order and
**must be verified from each job log**, which echoes `option.XCheckExt=<v>`):

| rep | XCheckExt=1 run | XCheckExt=0 run |
|---|---|---|
| 1 | 43030083544 | 43030087509 |
| 2 | 43030093411 | 43030097543 |
| 3 | 43030103961 | 43030107894 |
| 4 | 43030114667 | 43030118654 |
| 5 | 43030124783 | 43030128623 |

How to finish (mechanical, no judgement needed):
1. For each run take the **final** `Games: N, Wins: W, Losses: L, Draws: D` line of the `SPRT` step log.
2. Pool the five W/D/L per variant: score = (W + D/2)/N, trinomial 95 % CI, chi^2 across replicas (df 4). The NextGen Command Center
   (Sync button) or any trinomial calculator does this; the verdict function implements the rule in this file verbatim.
3. Append the table under **Results**, do not edit the hypotheses, bounds or the rule. If a run was cancelled or failed to
   build, report that and re-dispatch with a new `agentNP/base-N` alias; do not drop it silently.
4. PROMISING is not a merge (see rule). REJECT / INCONCLUSIVE: main stays unchanged; close PR #53 with the numbers.
Prediction made before seeing data (so it can be scored): `XCheckExt=0` loses; `XCheckExt=1` is within +/-10 Elo of main.
