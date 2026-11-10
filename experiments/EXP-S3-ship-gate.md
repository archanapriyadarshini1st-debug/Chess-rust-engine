# EXP-S3: ship gate - five replicated tests + side-effect checks before anything ships

- **Experiment ID:** EXP-S3
- **Responsible agent:** S3 (account `archanapriyadarshini1st-debug`, same owner as A/V/V2/U)
- **Repository / baseline:** `archanapriyadarshini1st-debug/Chess-rust-engine`, main `7793ad7`. Adds files only; **no `src/` change, no engine behaviour change, no Elo claim.**
- **Files:** `tools/ship_gate.py`, `.github/workflows/ship-gate.yml`, this record.

## Hypothesis
`sprt.yml` is one early-stopping stream on one machine. It cannot show that a verdict is *repeatable*, and it does not look at side effects (search non-determinism, NPS loss, time forfeits, a false "node-identical" claim). The owner's rule is "test it 5 times before shipping, and fix anything that gets worse". A gate that replicates the match five times on disjoint openings and probes side effects will catch regressions that a single stream can miss, at a known false-ship rate.

## What it does
1. **build job** - builds candidate and base with identical flags (`-C target-cpu=x86-64-v2`, portable so one binary pair runs on every runner), runs perft on the candidate, then `probe`: 5x `bench 11` on each engine (determinism), interleaved NPS ratio, sha256 of both binaries, CPU model.
2. **replicate job x5 (separate runners)** - replicate *i* plays a disjoint slice (`lines[i::5]`) of `tools/openings_book.epd`, shuffled with seed `1000+i`, colours swapped every opening, fixed rounds (default 119 = 238 games), **no SPRT, no early stop**, same adjudication as `sprt.yml`.
3. **verdict job** - pools the five replicates (exact union, nothing dropped) and applies the fixed rule documented at the top of `tools/ship_gate.py`. Exit 0 only for SHIP.

Decision rule was written **before** any result and must not be edited after seeing one. REJECT on: perft fail, non-deterministic candidate bench, candidate lost by time/illegal/crash, any replicate significantly negative (99%), pooled significantly negative (95%), median NPS ratio < 0.90, or a broken `expect_node_identical` claim. INVESTIGATE on replicate disagreement (heterogeneity p < 0.01) or NPS ratio 0.90-0.95. SHIP (improve) needs pooled LOS >= 97.5%, pooled 95% lower bound > 0 and >= 3/5 replicates positive; SHIP (noninferior) needs pooled lower bound >= -margin.

## Testing done on the gate itself (local, 4 vCPU Xeon, Rust 1.99.1)
| check | result |
|---|---|
| `ship_gate.py selftest` (statistics vs chi-square/normal tables, 15 decision-rule cases incl. A/A control, one collapsed replicate, -20% NPS, false node-identical claim, forfeit, unstable replicates, PGN parse) | all pass. It **caught a wrong fixture of mine** (my "equal" data was really +17 Elo) and the fixture was fixed, not the rule |
| `probe` on main vs main | bench 10 = 469049 nodes x5 on both, NPS ratios 0.965-1.042 (median ~1.01): the probe sees the noise floor of one box, which is why the thresholds are 0.90/0.95, not 0.99 |
| real fastchess PGN -> `parse` | 12 games parsed as +3 -6 =3, identical to fastchess's own summary. Plumbing test at 3+0.03 only; **not** a strength measurement (A/A read 37.5% over 12 games = noise) |
| workflow YAML | parses; 3 jobs, 10 inputs, 5-way matrix. **Not yet run on GitHub Actions** (see Status) |

## Operating characteristics of the decision rule (Monte-Carlo, 1500 trials, 5 x 238 games, 40% draws)
These are the honest error rates. They follow from the sample size and cannot be wished away.

```
games/replicate=238 replicates=5 draw_rate=40% trials=1500 mode=improve
true Elo | SHIP    REJECT  INVEST  INCONCL
     -10 |    0.1%    29.0%     0.4%    70.5%
      -5 |    0.5%    13.2%     0.5%    85.7%
      +0 |    2.3%     4.7%     0.8%    92.2%
      +5 |    8.7%     1.5%     0.9%    88.9%
     +10 |   24.6%     0.6%     0.9%    73.9%
     +15 |   48.1%     0.2%     1.1%    50.6%
     +20 |   71.7%     0.0%     0.9%    27.3%
     +30 |   95.8%     0.0%     1.1%     3.1%
     +50 |   98.5%     0.0%     1.5%     0.0%
```

Non-inferiority mode (margin 10 Elo):

```
games/replicate=238 replicates=5 draw_rate=40% trials=1500 mode=noninferior
true Elo | SHIP    REJECT  INVEST  INCONCL
     -20 |    0.2%    75.7%     0.1%    24.0%
     -10 |    1.9%    30.3%     0.3%    67.5%
      +0 |   26.2%     4.7%     0.8%    68.3%
      +5 |   46.9%     1.5%     0.9%    50.7%
```

Reading: the gate **will** stop a real regression (>= -10 Elo is rejected 29% of the time, -20 Elo 76%+) and **will** ship a clearly good patch (>= +30 Elo: 96%). It ships a truly equal patch ~2% of the time. It is **weak at +5..+10 Elo** with 1190 games (9-25% ship). That is a property of 1190 games, not of the rule: raise `rounds` (slice is repeated), e.g. rounds=357 gives 3x the games, and still use `sprt.yml` for tiny gains. Noninferior mode with a 10 Elo margin ships a truly equal patch only ~26% of the time at this sample size, so refactor claims need more rounds too.

## Limitations / possible regressions of the gate itself
- Trinomial statistics ignore opening-pair correlation; intervals are slightly wide (conservative).
- Replicates test the same pair of binaries, so they cancel runner noise and opening luck but **not** a systematic flaw of the time control / book. 10+0.1 single-thread only.
- `target-cpu=x86-64-v2` binaries are slower than `native`; fine for A-vs-B, **not** comparable to other agents' `native` NPS numbers.
- The fault scan relies on fastchess `Termination` text; `adjudication` and `normal` are not faults.
- Does not (yet) include a tactical regression suite or an SF19 UCI_Elo cross-check; both are listed as follow-ups.

## Status / decision
**Inconclusive until it has run on Actions.** Next step: dispatch it on PR #30 (corrhist revert) vs main as its first real use. Result will be appended here and not by editing the rule.
