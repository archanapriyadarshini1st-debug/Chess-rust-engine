# EXP-SD1: HCE self-play distillation at ~25x the previous volume, with game results (Agent SD)

**Status: pre-registered. Result pending (auto-posted to issue #1 by `.github/workflows/selfdistill-bulk.yml`).** No Elo claim.

## Question
Every net so far lost to, or tied with, the HCE: E 1-2-97 (<=1.1M SF-labelled), G stage-0 46-18-36 (0.76M self-labelled, no results),
A's Lichess-500k 3-0-17. R's 10M Lichess run is the *human-position, no-result* arm. Nobody has run the *engine's own
self-play distribution, with played game results, at >= 20M positions*. That is the data recipe that bootstrapped most HCE-era
NNUE engines. Is the wall data volume on **this** distribution?

## Method (all stages are existing, reviewed tools except the three small scripts in `tools/sd/`)
1. **Datagen:** Agent Z's `datagen-bin` (PR #22) pinned at `ad45119aedc46c5ffba8161e13fd3cf89cdf0230`, HCE depth 7 (never lower), 4 threads/shard,
   5 shards x 70 min in 400k-position chunks, unique seed per (shard, chunk). Records are 28 B with stm-POV score and stm-POV W/D/L from
   the played game; unfinished games are discarded, not labelled draws (Z's rule). Measured locally 1250-1290 pos/s per 4 threads.
2. **Merge** (`tools/sd/sd_merge.py`): rejects identical shards (sha256), requires a `.gid` per record, holds out **whole games** (1 in 40)
   as a validation set the trainer never sees, drops training positions identical to any holdout position, dedupes (same hash as `train.py`),
   seeded random subsample to <= 20M (trainer needs ~350 B/position).
3. **Train:** `tools/nnue/train.py` **unchanged**, `--lam 0.75` (score vs result), H=128, 8 buckets, 230 min.
4. **Honest validation** (`tools/sd/holdout_eval.py`): MSE on the game-disjoint holdout vs the constant predictor. *Why:* `train.py` splits by position hash, so
   neighbouring positions of one game straddle train/val. A local 1-minute toy net showed val 0.0052 (trainer) vs 0.0197 (game-disjoint): ~4x. The trainer's number is
   used only to pick the checkpoint; it is never the evidence.
5. **Gate:** net vs HCE, same binary (built from the NI branch so the net runs at ~HCE speed, see EXP-NI1/PR #52), 10+0.1, Hash 64, 1 thread,
   `openings_book.epd`, colours reversed, **5 independent replicates x 100 games with different book seeds + 1 A/A control (HCE vs HCE)**.
   `tools/sd/pool_gate.py` pools them (logistic Elo, trinomial CI, LOS) and the workflow posts the output verbatim.

## Pre-registered decision rule (fixed before any result)
- **Keep the direction** iff pooled score >= 52% with LOS >= 97.5%, **and** >= 4/5 replicates > 50%, **and** the A/A control is consistent with 50%.
- **Not shipped** otherwise. A merge of any net additionally needs `sprt.yml` on `main` and the ship-gate PRs' replicated downside checks.
- If pooled < 50%: record as negative; next suspects in order: HCE-anchored residual target, king buckets, label depth, `lam`.
- The numbers are not edited, filtered or re-run on a different seed after the fact.

## Limits stated up front
- Labels are the HCE's own depth-7 opinion plus game results; a net distilled from it can at best fold search into eval, not exceed the teacher. Stage-2 (SF19 MAX labels at >= 500 ms, `nnue-finetune.yml`) is the route past that.
- Z's generator at `ad45119` is based on an older `main`; its HCE may differ slightly from today's `main` HCE. The label engine is recorded in each shard's `.meta.json`.
- 100-game replicates resolve ~+-50 Elo each; the pooled 500 games resolve ~+-25. A +10 Elo effect would not be visible. That is the schedule, not a loophole.
- Castling rights / en passant are not in the 28-byte record (same as every source here).
