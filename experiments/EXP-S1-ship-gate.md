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

## Results (canary runs on GitHub Actions, preliminary: 40 rounds/rep, 30 SF19 games/engine)

Both final runs use the same code as this branch (`tools/ship_gate.py` + `ship-gate.yml`), 10+0.1, 1 thread,
16 MB hash, 595-position book `f1d9e142...`, fastchess 1.8.3-alpha, SF19 `UCI_Elo 2400`.

| canary | run | verdict | reps | pooled | A/A | SF19 TEST vs BASE | bench |
|---|---|---|---|---|---|---|---|
| `7793ad7` (PR #5 corrhist) vs `451d933` | `42820807288` | **BLOCK** (expected) | 0/5 positive, all 5 significantly negative | +4 -389 =7 (1.9%) | 46.2%, OK | 25.0% vs 88.3%, z = -7.80 | nodes 469049 vs 356715 |
| `a0c6786` (A's revert) vs `7793ad7` | `42820841782` | **SHIP** (expected) | 5/5 positive | +391 -5 =4 (98.2%) | 54.4%, OK | 81.7% vs 23.3%, z = +6.63 | NPS ratio 0.883 (warning) |

So the gate blocks the exact regression that bench could not see (bench nodes at d10 differ, but d8 were identical
and the strength loss was ~58 points of score), and it accepts the exact fix.

### Bugs this experiment found in the gate itself (fixed, in this order, all visible in the git history)
1. **Markdown renderer crashed** on the pooled row (`KeyError: 'w'`). The selftest never rendered markdown; the real run
   did (run `42816892339`). Fix: pooled W/D/L, tolerant `fmt`, verdict JSON written *before* markdown, selftest now
   renders every case.
2. **SF19 job skipped on push triggers**: on `push`, `inputs.sf_elo` is null and `null != '0'` is false in Actions
   expressions. Fix: `|| github.event_name == 'push'`. Without that fix the gate was silently running without its
   downside check.
3. **Heterogeneity test fired on same-direction sweeps** (+759 vs +3600 Elo). Elo saturates near 0%/100% scores, so Cochran Q on
   the Elo scale is meaningless there. The question heterogeneity asks (is the *sign* reproducible?) is already answered
   when every rep is individually significant in the same direction. Rule changed *because of a diagnosed flaw, with the
   canary data in hand*. That is a disclosed post-hoc change; it only turns INVESTIGATE into a note when all reps are
   decisive in the same direction and never relaxes BLOCK/INVALID.

### An unresolved harness question (not claimed either way)
Four A/A (BASE vs BASE, first-listed engine always `test`) samples on GHA scored 46.2%, 38.8%, 31.2%, 50.0% for the first engine
(160 games, 41.6%, z about -2.9), and a local A/A (direct vs direct, 80 games, and direct vs `sh`-wrapper, 80 games)
scored 46.9% and 46.9%. Agent S3 independently saw 37.5% over 12 games. The wrapper is **not** the cause (local test).
These samples are small and I started looking *because* one failed, so selection inflates the apparent effect. It might be
a small first-listed-engine penalty (order of ~-25..-40 Elo) or luck. I cannot tell. Consequence for the design: the
gate now **alternates engine order** across replications and between the two A/A halves, so a first-engine effect cancels in
the pooled estimate. After this change the two A/A samples read 46.2% and 54.4% (160 games, 50.3%).
**Other agents' single-order SPRTs (`sprt.yml`: `test` always first) would carry any such bias.** Worth a dedicated
larger A/A (>= 1000 games, both orders) before trusting small SPRT verdicts.

### Limits of this evidence
- Both canaries are *huge* effects (about -700 / +700 Elo). They show the gate catches a catastrophic regression and recognises a
  large fix. They say **nothing** about its ability to separate +5 Elo from 0; that needs ~10x more games (see Power).
- 40 rounds/rep is preliminary; A/A at 80 games has a +-45 Elo error bar.
- Bench `nodes ratio` warning (x1.31) fired on the blocked pair as intended; NPS 0.883 on the fix is the cost of singular
  extensions (+18% nodes at d10) which A's SF19 results suggest is paid for. That is a hypothesis, not a measurement.

## Decision

**Keep (as a promotion gate), label preliminary.** It reproduced the known-bad and known-good verdicts, and the process of
running it found three real defects in itself plus one open question about the shared harness. It does **not** replace
`sprt.yml`; it adds replication, an A/A control, order balancing and an external-opponent downside check.
Overlap: Agent S3's `agentS3/ship-gate` (PR #32) implements the same idea with disjoint opening slices and bench
determinism but had not been run on Actions when this was written; see issue #1 for the reconciliation.

## Possible regressions / limits

- It costs ~7 runner-jobs per gate. It is for **promotion**, not for every exploratory commit.
- UCI_Elo opponents are not calibrated; the downside check compares TEST against BASE on the *same* opponent,
  so calibration cancels, but a strength-dependent effect is still possible.
- Self-play + SF19 UCI_Elo cannot see regressions that appear only at long time controls or high thread counts.
- A SHIP verdict does not retire the other gates in section 9.4 (perft, fixed-node, no unexplained tactical
  regression); it adds replication and downside evidence on top.
