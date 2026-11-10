# EXP-Q1 — pawn correction history saturates and destroys strength (regression bisect)

- **Experiment ID:** EXP-Q1 (fix = branch `agentQ/corrhist-off`; follow-up EXP-Q2 = `agentQ/corrhist-bounded`)
- **Responsible agent:** Agent Q (regression bisect). Touches only `src/search.rs` (corrhist hunks) + this file.
- **Repository / baseline:** `archanapriyadarshini1st-debug/Chess-rust-engine`, `main` = `7793ad75dd4c152f23d2af225e8fec48485c55ad`.
- **Trigger:** Agent A measured `main` at +2=1-17 (12.5%) vs SF19 UCI_Elo 2400 and 2600, against a recorded 76% (40g) / 94.5% (100g vs 2000).

## Hypothesis
Something merged after the measured-good commit `4214eeb` collapsed playing strength. The pawn-corrhist table
added in `0676766` updates with `gravity(e, diff*depth/8)`, a *history* update whose fixed point is `+-HIST_MAX`
(16384) for any consistently-signed bonus, regardless of size. It is applied to static eval at `/32`, so each
pawn-structure slot can move eval by up to **+-512 cp**. That noise feeds RFP, NMP and `improving`.

## Evidence (all raw numbers reproducible; none cherry-picked)
| # | test | result |
|---|---|---|
| 1 | `bench 10` per commit (deterministic nodes) | `4214eeb` = `451d933` = **356715**; `0676766` = `cf3eb9f` = `983e3e2` = `7793ad7` = **469049**. The search changes at exactly one commit: `0676766` (SE + corrhist). |
| 2 | GHA SPRT run `42791696696`: TEST `4214eeb` vs BASE `main 7793ad7`, 10+0.1, 3 conc, 595-book, Hash 16, 1 thread, logistic [0,10] | **205-0-3** (99.28%), LLR 2.95, **H1 accepted**. Builds + perft green. |
| 3 | Local fastchess 1.8.3-alpha, 10+0.1, 3 conc, same book, `-srand 12345`: TEST = `main` with *only* the corr term removed (`bench 10` = 553783) vs `main` | **58-0-2** (98.33%) over 60 games, Ptnml(0-2) `[0,0,0,2,28]`. Preliminary sample, but 0 losses. |
| 4 | GHA SPRT `42791701553`: `4214eeb` vs `451d933` (benches identical => same search, A/A control) | **pending** at time of writing; will be appended. Expected: ~50%, otherwise the harness is biased. |

What this does **not** show: that singular extensions are good or bad on their own, or that a *correct* correction
history helps. Those are separate experiments (EXP-Q2 below, and `agentQ/corrhist-off` vs `4214eeb`).

## Change (EXP-Q1 fix, `agentQ/corrhist-off`)
`const CORRHIST: bool = false;` gates both the application (`static_eval`) and the update. Search tree is then
identical to the variant in row 3 (`bench 10` = **553783**, `bench 8` = 177090). Singular extensions are untouched.
`cargo test --release`: all green.

## Follow-up (EXP-Q2, `agentQ/corrhist-bounded`) — candidate, NOT proposed for merge yet
Same table, correct estimator: running mean of (search score - raw eval) in 1/16 cp, clamped to +-32 cp (so the
correction can never exceed +-32 cp), depth-weighted rate `min(depth+1,16)/256`, skipping updates whose TT bound is
uninformative (lower bound <= raw eval / upper bound >= raw eval) and updates when the best move is a capture.
`bench 10` = 571546. Must beat `agentQ/corrhist-off` in an SPRT before it is considered.

## Lessons recorded
1. A bundled patch (SE + corrhist in one commit) hid a catastrophic component (0 losses in 205 games; Elo is unbounded above, only a several-hundred-Elo lower bound is supported, no point estimate is claimed) behind a "SE is a classic gain" story.
   One change per commit, SPRT per change (as the gate rules already say).
2. `bench` equal across a refactor is not strength equal, and `bench` *changed* is not strength *changed* — only games decide. But a node-count bisect is a free way to find *which commit* to play games about.
3. The earlier retro-gate of PR #5 (run `42596468549`) ended in `Verdict failure`, i.e. no H1 at the sample size — it was
   never shown to be a large loss because the sprt window was [0,10]. A **non-regression** gate with a wide sample would
   not have missed this: a collapse of this size is visible in ~20 games. Suggest every retro-gate also runs the reverse direction.
4. 20-game limiter ladders are still the wrong ruler for ±30 Elo, but they were right to flag this: they saw a 5–12% score
   where 76% had been recorded. That discrepancy should have triggered a bisect immediately.
