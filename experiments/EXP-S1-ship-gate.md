# EXP-S1: Ship gate (5 replications + A/A control + downside checks)

- **Experiment ID:** EXP-S1
- **Responsible agent:** Agent S (new session, same owner, lane: *ship gate / downside detection*)
- **Repository:** `archanapriyadarshini1st-debug/Chess-rust-engine` (authoritative)
- **Baseline commit:** `7793ad7` (main at time of writing). **No `src/` change.** Engine behaviour is untouched.
- **Files owned:** `tools/ship_gate.py`, `.github/workflows/ship-gate.yml`, this file. Nothing else.

## Problem

A single SPRT (`sprt.yml`) has a 5% false-pass rate, cannot detect a biased harness, and checks only
self-play. The repo has already paid for this once: PR #5 (pawn correction history) merged with **bench
nodes identical to main (178914 at d8)**, then scored **12.5% vs UCI_Elo 2400** (70.8% before it). Several
later experiments were measured on top of that broken search. A gate that asks one question once is not
enough to "ship".

## Hypothesis

A gate made of (a) five fixed-size independent replications, (b) an A/A control, (c) an external-opponent
downside check and (d) reliability/cost checks will
1. **BLOCK** the known PR #5 regression (`7793ad7` vs `451d933`), and
2. **SHIP** the known fix (`a0c6786`, Agent A's corrhist revert, vs `7793ad7`),
3. have a false-SHIP rate under H0 (identical engines) well below a single SPRT's 5%.

## Decision rules (fixed before any result; do not edit after seeing a run)

Implemented in `tools/ship_gate.py` and unit-tested by `python3 tools/ship_gate.py --selftest`.

| verdict | condition |
|---|---|
| **INVALID** | fewer than 5 replications / a replication under `min_games` / A/A control shows `|Elo| > 2.576*se` / SF19 check required but missing |
| **BLOCK** | any replication significantly negative (`elo + 2.576*se < 0`, Bonferroni over 5 reps), or pooled LOS <= 2.5%, or SF19 downside `z <= -1.96` (TEST vs BASE score against the *same* external opponent), or TEST has more crash/illegal/time-forfeit losses than BASE, or perft/bench failure |
| **INVESTIGATE** | replications disagree (Cochran Q p < 0.01), or soft SF19 downside `z <= -1.28` |
| **SHIP** (`improve`) | pooled LOS >= **99%**, pooled Elo >= `min_gain`, and >= 4 of 5 replications positive |
| **SHIP** (`neutral`) | pooled `Elo - 1.96*se >= -margin` (a loss larger than `margin` is ruled out) |
| **SHIP** (`perf`) | bench nodes **identical** (and deterministic) and NPS ratio >= 1.0 |
| **INCONCLUSIVE** | everything else. That means "more games", never "probably fine" |

Elo uses pentanomial pair statistics (colour-swapped paired openings), normal approximation.
Replications are **fixed size with no early stopping**, so optional stopping cannot inflate the pass rate.
A warning (not a block) is raised for NPS ratio < 0.90 or bench nodes x1.30 at fixed depth.

## Measured properties of the gate itself (selftest, simulated, no engine involved)

- 1000 simulated gates of identical engines (5 reps x 150 pairs, 60% draws, valid A/A): **false-SHIP 1.2%**.
  An 18-case truth table (collapse, one bad rep, biased A/A, missing rep, SF19 downside, crash, perft fail,
  perf, heterogeneity, parser on a real fastchess log) passes.
- The parser was validated on a real local fastchess 1.8.3-alpha run of this engine
  (16 games, `Ptnml(0-2): [0, 2, 4, 2, 0]`), not only on synthetic text.
- First selftest run read 2.8% false-SHIP at `LOS >= 97.5%`; I tightened the rule to 99% **before any engine
  data existed** (this is a design correction, recorded here, not a result-fitted change).

## Power (honest limits)

5 x 150 rounds = 1500 games pooled per gate. At ~60% draws, the pooled 95% half-width is roughly +-10 Elo.
So `improve` can certify gains of about **+15 Elo or more**; it cannot certify +5. For small gains use the
existing SPRT with [0, 5] bounds and *then* run this gate as the replication/downside check.
`neutral` with margin 10 needs about the same sample. Defaults are inputs, not claims.

## How to run

GitHub -> Actions -> **Ship gate** -> `workflow_dispatch`: `test=<branch|sha> base=main mode=improve rounds=150`.
Defaults: 10+0.1 (floor 5+0.05 enforced), 595-position book, 1 thread, 16 MB hash, SF19 UCI_Elo 2400 x 100 games
per engine, `-srand` seeds `seed_base+1..5` (A/A: `+100`). Artifacts: per-run logs/PGNs/bench/meta
(book sha256, binary sha256 prefixes, commits, fastchess version, SF19 sha256) and `ship_gate.json`.
Exit code: green only for SHIP.

## Canary runs (proof that the gate works; small, **preliminary**)

Pushing `agentS/gate-canary-block` runs `7793ad7` (TEST) vs `451d933` (BASE): expected **BLOCK**.
Pushing `agentS/gate-canary-ship` runs `a0c6786` (TEST) vs `7793ad7` (BASE): expected **SHIP**.
40 rounds per rep (20 per A/A half), 30 SF19 games per engine; `min_games` 60. Results are appended below by link, whatever they are.

## Results

_(pending; filled in from the run summaries, negative or unexpected outcomes included)_

## Decision

_pending_

## Possible regressions / limits

- It costs ~7 runner-jobs per gate. It is for **promotion**, not for every exploratory commit.
- UCI_Elo opponents are not calibrated; the downside check compares TEST against BASE on the *same* opponent,
  so calibration cancels, but a strength-dependent effect is still possible.
- Self-play + SF19 UCI_Elo cannot see regressions that appear only at long time controls or high thread counts.
- A SHIP verdict does not retire the other gates in section 9.4 (perft, fixed-node, no unexplained tactical
  regression); it adds replication and downside evidence on top.
