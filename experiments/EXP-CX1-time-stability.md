# EXP-CX1: best-move stability counter was always true

- **Experiment ID:** EXP-CX1
- **Responsible agent:** Agent CX (time-management correctness)
- **Repository / baseline:** `archanapriyadarshini1st-debug/Chess-rust-engine`. `main` @ `40faeb7`; stacked on PR #43 (`th/s-time-mgmt` @ `9f55267`).
- **Binary hashes (local sandbox build, x86-64-v2, rustc 1.99.1):** PR43 `sha256:01481734e1cae067...`, CX `sha256:85f6bd91a561cd08...` (prefixes; GHA builds its own per-runner binaries).
- **Status:** PRE-REGISTERED. Strength results pending. **No Elo claim.**

## Hypothesis
`iterative_deepening` compares `last_pv.first()` with `td.best`, but both are assigned from `td.pv[0][0]` a few lines earlier, so
the test is always true. `stable` therefore increases every iteration and `soft_expired(stable >= 4)` is true from depth 4 on.
The "best move keeps changing -> keep thinking" behaviour cannot run on `main`, and the scaling table added in #43
(`[1.45, 1.25, 1.10, 1.0, 0.90][stable.min(4)]`) is stuck on its last entry (0.9x).

## Evidence of the bug (reproduced)
Kiwipete, `go depth 14`, #43 head instrumented to print `stable`: best move `e2a6 -> d5e6 (d3) -> e2a6 (d6)`, `stable` = 1,2,3,...,14 (never reset).

## Change
`next_stability(prev_best, best, stable)` in `src/search.rs`; the previous iteration's best is remembered and compared
with the new one. First iteration counts as unstable (0). Unit test `stability_resets_when_best_move_changes`.
`bench 10` = 553783 (unchanged; bench is depth-only and cannot observe time management).

## Expected benefit
Positions where the best move flips late get up to 1.45x the soft budget; stable positions still stop early.

## Possible regressions (stated before testing)
- This **activates** scaling values that have never been exercised. If 1.45x/1.25x/1.10x are too generous, the engine
  burns clock in volatile middlegames and loses on time at 10+0.1 (increment is only 0.1 s).
- `soft` is capped at `hard/2`; hard is `min(4*soft, remain - overhead - 80)`. Time losses are the thing to watch.
- Interaction with #43's node-share and score-drop terms (all multiply).

## Testing configuration
- `sprt.yml`, TC 10+0.1, logistic, H0 = 0, H1 = +5, round cap 800 (1600 games), concurrency 3, harness book from `main`.
- Arm 1: CX vs #43 (`th/s-time-mgmt`). Arm 2: CX vs `main`. TH's #43-vs-main run supplies the third arm.
- Local downside check (not strength): 40 games CX vs #43 at 5+0.05, 2 concurrent, `-recover`: crashes / illegal moves / time losses.

## Decision rules (fixed before any result)
- **KEEP** iff Arm 1 accepts H1 **and** Arm 2 is not negative. Time losses > 0 attributable to CX blocks it.
- Arm 1 accepts H0 or any negative Arm 2: **REVERT** and record why, since the scaling table would then be mis-tuned and needs SPSA.
- Cap reached without a verdict: **INCONCLUSIVE**; do not merge; the effect is then below what 1600 games can resolve.

## Results
(pending, filled in by Agent CX or the next agent; run ids are in the PR description)

## Decision
(pending)
