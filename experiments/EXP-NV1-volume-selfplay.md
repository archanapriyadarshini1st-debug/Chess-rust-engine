# EXP-NV1: does ~20x more self-play data (with outcomes, shard-disjoint validation) fix the net-vs-HCE gap?

Agent NV. Baseline: `main` @ `40faeb7` (HCE default; no net promoted). Datagen = PR #22 (`datagen-bin`, head SHA is
recorded per shard in `*.provenance`). **Stockfish is not used anywhere in this experiment.** Registered BEFORE any
game was played.

## Why this experiment (and not another gate or verifier)
Eight-plus agents already own gating, review, fuzzing and measurement. The open question the thread keeps circling is
whether the replace-style net path is *dead* or *starved*: every net so far used <= 1.2M positions (stage-0: 757k, +35 +/- 61
vs HCE at 100 games), validation was position-hash (leaks, EXP-I2), and stage-0 labels had no game outcome (`wdl=1`).
Z measured that one 4-vCPU job produces ~1.5-1.9k pos/s with `datagen-bin`; nobody has trained on that volume yet.
M claimed a 20M scale test (#16 + game-disjoint val) but I could not find a result posted; if M already has one running,
this experiment is the *replicate with outcomes* and the two should be pooled, not raced.

## Hypotheses
- H1: a net trained on >= 20M unique quiet self-play positions with real outcomes (lam 0.6) scores >= 50% vs HCE at equal nodes.
- H2: lam 1.0 (search score only) vs lam 0.6 (score + outcome) differ. Direction not pre-registered.
- H0: more data does not help (curve stays far below 50%); then the replace-style net is the wrong next investment and the
  tuned-HCE / search lines should get the compute.

## Design
1. 5 training shards + 1 held-out validation shard, depth-8 HCE self-play, distinct seeds (7001..7006), balance filter and
   adjudication as in PR #22. Only quiet positions (not in check, best move not capture/promo, |cp| <= 2500).
2. Trainer = `tools/nnue/train.py` with the new opt-in `--val-data` (validation = whole held-out shard, positions that also
   occur in training are dropped; the old hash split is unchanged when the flag is absent). No other trainer change.
3. Two nets in parallel: `lam=1.0`, `lam=0.6`. Same data, same wall-clock.
4. Gate: same binary, `UseNNUE` true+net vs false, **fixed 25k nodes/move**, 1 thread, Hash 64, colours swapped,
   `tools/openings_book.epd`, **5 independent replicates with disjoint opening slices** (the owner's "test it 5 times").
5. Controls in the same workflow: **A/A** (HCE vs HCE, must show |Elo| < 2.576 se or everything is INVALID) and the
   **stage-0 reference net** (`nets/candidates/stage0-selfd7.nnue`), so "better than before" is measured, not remembered.

## Pre-registered verdicts (implemented in `tools/nnue/nv_report.py`, which recomputes from raw logs)
- KILL: pooled 95% CI upper bound < 0 Elo.
- ADVANCE: pooled score >= 50%, >= 3/5 replicates >= 50%, pooled CI lower bound > -40 Elo. **Earns only a 10+0.1 gate, never a merge.**
- else INCONCLUSIVE. Nothing changes after the numbers are seen; negative results are kept.

## Known limits (stated up front)
- Fixed nodes ignore NNUE's lower NPS (no incremental accumulator on main), so this is an *eval-quality* screen, not a strength claim.
- Self-play from HCE teaches HCE's opinion plus outcomes; it cannot exceed "HCE with search folded in" by itself.
  Beating HCE needs outcome signal (lam < 1) or later net-vs-net iteration.
- `config smoke` runs (tiny data) are pipeline checks and are labelled as such.

## Amendments (made after the SMOKE stage, before any evidence game)
- Smoke run `42991827803` (150k positions, 60 games/candidate) only proved the pipeline: all jobs green, A/A 50.0%, nets junk as expected
  (lam1.0 24%, lam0.6 2.5%). **Not evidence.** It measured `datagen-bin` at ~600 pos/s on a GHA runner (Z's local figure was higher),
  so the full stage is 6 train shards x 2M = ~12M positions (not 20M) to keep the run to ~2 h.
- Added a **dose-response arm** `lam0.6-1shard` (same recipe, 1 of the 6 shards, ~2M positions). If `lam0.6` (12M) beats it clearly the
  net path is *starved*; if both sit at the same low score it is *not a volume problem*. This arm has no verdict of its own.
- Full-stage gate: 5 replicates x 120 games = 600 games per candidate at 25k nodes. Verdict rules above are unchanged.
