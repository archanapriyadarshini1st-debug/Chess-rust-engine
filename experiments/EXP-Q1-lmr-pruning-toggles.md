# EXP-Q1 - LMR / pruning depth bookkeeping (Agent Q)

- **Repository / baseline:** `archanapriyadarshini1st-debug/Chess-rust-engine`, `main` @ `40faeb7`
  (`bench` = 177090 nodes). Binary hashes are recorded in each Actions run's artifact.
- **Branch:** `agentQ/lmr-pruning-toggles`. Four UCI toggles, **all default 0**. With all toggles off the
  engine is node-identical to `main` (`bench` 177090 nodes) - verified.
- **Why toggles:** one binary, four isolated A/B tests, no confounding build differences. Nothing here
  changes behaviour until an option is set, so the branch cannot regress `main` by merging.

| ID | toggle | hypothesis | possible downside |
|---|---|---|---|
| Q1a | `XCapLmr` | Late non-promo, non-check captures are searched at full depth today; most are losing/neutral exchanges. Half-LMR frees nodes for the PV. | Missed tactics: a late capture is often the refutation. |
| Q1b | `XLmrFut` | Futility compares eval to alpha at raw `depth`, but a late quiet move is searched at `depth - R`; use that depth (+ half margin). | Over-pruning in positions where a quiet move is the only defence. |
| Q1c | `XDeeper` | After an LMR scout beats alpha, a *large* margin over `best` deserves +1 ply, a marginal one -1 ply. | More nodes per search; fewer when score is marginal. |
| Q1d | `XFailHighRed` | Once alpha is raised, remaining moves only need to refute: `depth -= 1` (depth 3..11, non-mate). TT keeps the loop-entry depth. | Big tree change (fixed-depth bench nodes -49%): deeper but shakier. |

Fixed-depth bench with each toggle on (sanity only - **not** strength evidence):
Q1a 176891, Q1b 179042, Q1c 201443, Q1d 90351, all four 88819 nodes (main: 177090). No hangs.

## Test protocol (fixed before any game)

1. `cargo test --release` (perft + unit) green; bench node-identity with toggles off.
2. 5 independent `sprt.yml` replications per toggle: test=branch + `option.X=1`, base=`main`,
   10+0.1, Hash 16, 1 thread, random openings from `tools/openings_book.epd`, colours swapped, SPRT [0,10].
3. Downside probe before any default-on proposal: tactics suite + fixed-time NPS.
4. **Keep rule:** pooled Elo > 0, 95% CI lower bound > -5, no replication worse than -25 Elo, probe clean.
   Otherwise recorded as negative / inconclusive. Never merged by the author.

## Results

(filled in as runs finish - see issue #1 and the table below)
