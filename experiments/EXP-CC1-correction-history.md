# EXP-CC1 — correctly-scaled static-eval correction history (Agent CC)

**Status: PRE-REGISTERED. Results are appended below only after the runs finish. Nothing here is a rating claim.**
Repository: `archanapriyadarshini1st-debug/Chess-rust-engine`. Baseline: `main` **73d0379**, `bench 10` = **553783**
(reproduced, rustc stable, 4 vCPU). Binary sha256 prefix of baseline built locally: `563cd2a342cf3b20`.

## Hypothesis
The HCE static eval has a position-class-dependent bias (pawn structure, remaining piece sets). Learning the running
mean of `(search score - raw static eval)` per context and adding a clamped fraction back to the eval used by RFP /
NMP / futility / `improving` makes pruning decisions more accurate. Stockfish (`correctionHistory`), Reckless and
Viridithas all ship a variant and report gains; PR #5's variant here lost because it was mis-scaled (`corr/32` of a
gravity sum with HIST_MAX 16384 saturates at +-512 cp), not because the idea fails. This is **not** a repeat of #5.

## Change (src/search.rs, src/params.rs only)
* Three tables `[pawns | white non-pawns | black non-pawns] x [side to move] x 16384` of `i16`, units 1/32 cp.
* Update at node end (non-excluded, not in check, |best| < mate, best move not a capture/promo, and the usual
  "bound does not contradict direction of the error" rule): entry <- weighted mean toward `clamp(best - raw_eval, +-200)`,
  weight `min(depth+1, 16)/256`. Entries are bounded means in cp, they cannot saturate like a gravity sum.
* Apply: `static_eval = raw + clamp(mean(3 entries) * CorrWeight/100, +-CorrMax)`; raw eval is used for the update target.
* Options: `CorrWeight` (default **0 = off**, bench-identical, verified 553783) and `CorrMax` (default 64 cp).
* Persisted across moves of a game (like the other histories), cleared on `ucinewgame` (ThreadData is rebuilt).

## Known cost
~4-9 % NPS when on (3 extra table reads + hashing per node). Fixed-depth node count drops (bench 10: 553783 ->
506447 at W=100, 491436 at W=50, 524087 at W=200), so a net gain is not implied — only games can tell.

## Test design (fixed before any game is seen)
* `sprt.yml`, TEST = `agentCC/corr-hist` with `test_opts=option.CorrWeight=<W>`, BASE = byte-identical `main` 73d0379
  via distinct branches `agentCC/base-1..N` (so replicas do not cancel each other in the workflow concurrency group).
* **5 independent replicas per arm**, tc **5+0.05** (screening; floor of the repo) and, only for an arm that passes
  screening, **5 replicas at 10+0.1** (owner's time control). Fixed sample, no early stop (`elo0=-1 elo1=1`, large max_rounds
  is capped by `max_rounds`), `openings_book.epd` random order, 3 concurrent games.
* Arms: W=100 (mean of the three tables), W=200. One **A/A control** (main vs main) for the noise floor.
* **Keep** iff pooled CI lower bound > 0 AND >= 4/5 replicas > 50 % AND heterogeneity chi2 p > 0.05 AND no
  forfeits/illegal moves. **Revert / leave default-off** iff pooled point estimate <= 0 or CI includes a
  material loss (< -5). Anything else = inconclusive, not promoted. After "keep": downside check vs SF19 UCI_Elo and
  a tactical sanity probe before CorrWeight's default may be changed.
* Default stays 0 in this PR regardless of outcome; flipping the default is a separate, evidence-citing change.

## Results
_(to be filled in)_
