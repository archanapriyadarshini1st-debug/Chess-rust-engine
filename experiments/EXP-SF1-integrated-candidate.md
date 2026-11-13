# EXP-SF1: integrated candidate = verified search/time stack (#43+#47+#41) + lichess-bulk net

Agent SF. Status: **local evidence in; 5x GitHub replicas pending (see bottom). DRAFT PR, needs an independent reviewer.**
Nothing here is a CCRL/Elo-rating claim. UCI_Elo is a limiter scale.

## Identity
- Repository: `archanapriyadarshini1st-debug/Chess-rust-engine` (authoritative).
- Baseline: `main` 73d0379 (HCE default, bench 10 = 553783).
- Tested commit: `f6e3a96b09a56f9ca5c885f98bea3455aec08348` (branches `agent-sf/net-r1..r5`, same commit).
- Stack-only control: `agent-sf/integ-stack` @ `e751d86995671c624cb93d6a541c4d0719b0248e` (HCE, no net).

## Hypothesis
Two independently verified improvements touch disjoint files and should stack:
1. NP2 stack (PRs #43 time-mgmt, #47 stability fix, #41 TT-eval): +43.6 Elo [36.7, 50.5] / 4000 games (Agent CO, EXP-NP2).
2. Net `964d07413bac73565bff10060b78acc72ab8e4e1389f2afc41debb18afa62f91` (H=128, 768 inputs, 8 material buckets, 201,012 bytes),
   trained from 16M Lichess CC0 Stockfish-evaluated positions (run 43234447213), val_loss 0.00663.

## Change
Server-side merges of the three PR branches onto main + `nets/default.nnue` replaced by the net above. No other source change.
`UseNNUE=false` restores the full HCE path, so the fallback is retained.

## Correctness (local, sandbox 4 vCPU / 3 GB, rustc 1.100, `-C target-cpu=native`)
- `cargo test --release`: all tests pass (incl. perft suite, eval_params, fifty_move_mate).
- `bench 10`: 619016 nodes @ 1.46M nps with net; 496195 nodes @ 1.30M nps with `UseNNUE=false`. No NPS penalty from the net.
- Static-eval probes (side to move; HCE vs net): OCB +1 pawn 104 vs 6; R+P vs R 65 vs -11; SCB +1 pawn 156 vs 33;
  start-position-minus-queen 1012 vs 832; quiet middlegame -21 vs 22. The net does NOT show the OCB/rook-ending
  over-optimism DR reported for the TL net; it is *less* optimistic than the HCE there.

## Local results (all W/D/L recomputed from raw fastchess logs with `stats.py`: trinomial CI, logistic Elo)
Same machine, same time control, same book (`tools/openings_book.epd`, colours reversed), 1 thread, Hash 64.

| test | tc | W-D-L | score [95% CI] | Elo [95% CI] | note |
|---|---|---|---|---|---|
| main-binary HCE as opponent: NET only (no stack, main code) vs HCE | 5+0.05 | 92-12-16 / 120 | 81.7% [75.3, 88.0] | +260 [+194, +346] | isolates the net (binary 120d94e9 on CI gate: 29-6-5 / 40) |
| candidate vs SF19 UCI_Elo 2600 | 10+0.1 | 56-1-3 / 60 | 94.2% [88.5, 99.9] | +483 [+354, +1151] | main HCE: 67.3% / 500 (Agent X1) |
| candidate vs SF19 UCI_Elo 3000 | 10+0.1 | 12-29-19 / 60 | 44.2% [35.2, 53.1] | -41 [-106, +22] | |
| main (HCE) vs SF19 UCI_Elo 3000 | 10+0.1 | 2-15-43 / 60 | 15.8% [9.1, 22.6] | -290 [-400, -214] | same ruler, same book |

Binaries: candidate sha256 prefix `7f3a3645e491`, main `3d5cfb6930f0`. SF19: `stockfish-linux-x86-64-universal`
sha256 `0f83d24cc46d2c66...` (matches the pin). fastchess 1.8.3-alpha. These are PRELIMINARY samples (60 games each).

## Owner target status
**NOT MET.** Target is >= 80% vs SF19 UCI_Elo 3000 at 10+0.1. Candidate measured 44.2% [35.2, 53.1] / 60 games, i.e. about
+250 Elo (limiter scale) better than main on the same ruler, but still below the gate. No 3000-Elo claim is made.

## Caveats (stated up front)
- Net labels are not from the pinned SF19 (Lichess DB: various SF versions/depths) and positions are human-game positions.
- 60-game samples have wide CIs; GitHub replicas (below) are the decision evidence, not these.
- The net's gate used `openings_book.epd`; `sf19-match.yml` uses `tools/openings.epd` (random legal, less balanced). Both arms of every comparison use the same file.
- Lazy-SMP / long time controls untested.

## Pre-registered GitHub replicas (config fixed before the first game)
`sprt.yml`, tc 10+0.1, `elo0=-1 elo1=1` (no early stop), `max_rounds=200` (400 games), concurrency 3, Hash 16.
- SF-A: TEST `agent-sf/net-r{1..5}` vs BASE `main`.
- SF-B: TEST `agent-sf/net-r{1..5}` vs BASE `agent-sf/integ-stack` (does the net stack on the search stack?).
- SF-C: `sf19-match.yml` ladder 2600,3000 x 60 games, 5 candidate replicas (`net-r*`) and 3 baseline replicas (`base-r*`).
Decision rule: pooled CI lower bound > 0, >= 4/5 replicas > 50%, chi2 heterogeneity p > 0.05, no forfeit/illegal/crash in logs.

## Decision
PENDING the replicas. Rollback path: `git revert` of the net commit restores HCE; `UseNNUE=false` at runtime.
