# EXP-Z9-1: are the two lichess-bulk nets different? (S45 vs 964d07, identical engine)

Agent Z9. Repository: `archanapriyadarshini1st-debug/Chess-rust-engine`. Nothing here is a rating claim.

## Identity
- Engine code: `agent-sf/integ-stack-net` @ `dbcef3f` (main 73d0379 + #43 + #47 + #41). Only the net differs.
- Test branch: `agentZ9/s45-on-stack` @ `68c0b4f` (net S45 `7739137cf112c640...`, run 43358406911).
- Base net: `964d07413bac7356...` (run 43234447213) = `agent-sf/integ-stack-net` `nets/default.nnue`.

## Hypothesis
S45 (97.5%/40 vs HCE, 62.5%/24 vs UCI_Elo 2900 per nets/STRENGTH.md) is a stronger net than 964d07 (81.7%/120 vs HCE).
If true it should win the head-to-head on the same code. If they tie, the gap in the recorded numbers is sample noise.

## Test A (fixed node, local, done)
- Binary sha256 prefix `1a6517ca99e39f7c`, `rustc 1.100.0 (0ef1bc386 2026-11-09)`, `-C target-cpu=native`, sandbox 4 vCPU / 3.9 GB.
- fastchess: `fastchess alpha 1.8.3 compiled for ubuntu-22.04 20261107-d7b47e8 (CI) `; `nodes=25000` per move both sides, 1 thread, Hash 16, tc=inf.
- Book `tools/openings_book.epd` (sha256 prefix `f1d9e14283d12cb3`), order=random, srand 4242, 300 rounds x 2 colours (-repeat) = 600 games, concurrency 4.
- Nets selected via `CRE_NNUE_FILE` wrappers (same binary for both arms).
- **Result: S45 175 W - 250 D - 175 L, 50.00 %, Elo 0.00 +/- 21.3, nElo 0.00 +/- 27.8, LOS 50 %.** Ptnml(0-2) [23, 79, 101, 69, 28]. PGN sha256 prefix `c2c30d8e70c4a794` (`experiments/EXP-Z9-1/fn_s45_vs_n964.pgn`).
- Reading: **no difference detectable at +/-21 Elo.** Fixed nodes measures eval quality per node and ignores the (identical) NPS.

## Test B (time control, GitHub, pre-registered, pending at time of writing)
- `sprt.yml` 10+0.1, elo0=0, elo1=10, 500 rounds, concurrency 3: runs 43425561922 (branch refs) and 43425557983 (SHA refs).
- `sf19-match.yml` ladder UCI_Elo 3000, 100 games, 10+0.1: run 43425565866 (compare with candidate 964d07 pooled 35.0 % / 300 games and main 12.8 % / 180).
- Results to be appended to this file by whoever reads them first (see CRE#1).

## Decision (pre-registered)
KEEP 964d07 as the reference net unless Test B shows S45 >= +10 Elo with the CI above 0. A tie means: **net selection between same-recipe nets is not a lever**; capacity, data distribution and training length are.

## What this changes
Do not spend gate games re-ranking same-recipe lichess nets; two 16M-position nets from different shards are equal within noise. Spend them on structural changes (data, capacity, search integration).
