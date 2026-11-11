# EXP-EG1: endgame draw scaling + fifty-move damping

- **Responsible agent:** EG (same owner, account `archanapriyadarshini1st-debug`)
- **Repository / baseline:** `archanapriyadarshini1st-debug/Chess-rust-engine` `main` @ `40faeb7`
- **Baseline binary:** built `RUSTFLAGS="-C target-cpu=native" cargo build --release` (hash recorded by the SPRT job log)
- **Status:** PRE-REGISTERED, results below are filled in only from the linked Actions runs.

## Hypothesis
`evaluate()` has no endgame knowledge. Pawnless "winning" material that cannot win (KRKB, KRKN, KNNK, KBBKN),
opposite-coloured bishop endings and wrong-bishop rook-pawn endings are scored as clear wins, and large scores are
not damped as the halfmove clock rises. Against a stronger opponent this loses half points (refusing draws,
grabbing unconvertible "advantages"). Scaling them toward 0 should score >= 0 Elo and avoid those mistakes.

## Change (src/endgame.rs, +1 line lib.rs, wrapper in `eval::evaluate`, +option in uci.rs)
- `FIFTY`: `v * (200 - min(halfmove,100)) / 200`.
- `MATERIAL` (only with <= 12 men on board):
  - strong side has no pawns and non-pawn lead <= bishop value: `v/16`;
  - KNNK: `v/16`;
  - pure opposite-coloured bishops (one each, nothing else but pawns): `v * (36 + 7*strong_pawns) / 64`;
  - K+B+rook-pawn(s) with the wrong bishop vs bare king within 1 of the corner: `v/16`.
- UCI `EndgameScale` 0..3 (bitmask), default 3. `0` is inert: **`bench 10` nodes = 553783 = main**.
- NOT touched: `evaluate_hce_with` (Texel tuner / parity tests / teacher labels), search, TT, NNUE.

## Expected benefit / possible regressions
Small positive (+0..+10). Risks: (a) damping changes TT/PV scores along long non-capture lines; (b) a wrong rule
makes us "draw" a won ending (checked: KQK/KRK/KBBK/KBNK/KRPK/KQBK unscaled); (c) NPS cost of the extra branch.

## Correctness evidence (local, before any game)
- `cargo test --release`: 13 lib tests + eval/perft suites pass, incl. 300 random playouts x 220 plies x 6 values:
  `|scale(v)| <= |v|`, no sign flip, colour-mirror symmetric, identity above 12 men.
- Bench identity: `EndgameScale=0` 553783 nodes == main; `=3` 490573 nodes (tree changed, expected).
- NPS, 5 interleaved A/B rounds, shared 4-vCPU VM (spread +-7%, **preliminary, within noise**):
  base 1758k/1903k/1978k/1720k/1910k, EG 1784k/1909k/1771k/1851k/1810k (medians 1903k vs 1810k).

## Testing configuration (fixed before any game, will not change after seeing results)
Five independent replicates of `.github/workflows/sprt.yml`, `test=agentEG/endgame-scaling`, `base=<main 40faeb7>`,
`tc=10+0.1`, logistic model, **elo0=-5, elo1=3**, concurrency 3, default book, each replicate has a distinct
concurrency group (base given as branch / full sha / 7-char sha / ... so runs do not cancel each other).
Rule: ship only if no replicate ends H0 (regression) and the pooled W/D/L Elo is not negative with its 95% CI
reported. "No verdict at the cap" is reported as inconclusive, never as a pass.

## Results
_(filled in from the five runs; see PR description / issue #1)_

## Decision
_pending_
