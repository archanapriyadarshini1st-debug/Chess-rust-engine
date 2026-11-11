# EXP-TH: search-tree hygiene (Agent TH)

Repository: `archanapriyadarshini1st-debug/Chess-rust-engine`. Baseline: `main` @ `40faeb7`
(`bench 10` = **553783 nodes**). Everything below is a *hypothesis from reading code* until a gate decides it.
Bench nodes show the tree changed, **not** that it got stronger.

## Rules fixed before any result existed
* One functional change per branch, each off `40faeb7` (TH5 is stacked on TH1 by design).
* Screening: `sprt.yml`, TEST = branch, BASE = `main`, 5+0.05 (repo floor), logistic [0, 6], alpha = beta = 0.05, cap 2500 rounds.
* Ship gate (owner's rule: *test 5 times, find the downside, fix it first*): a candidate that passes screening is
  re-run as **5 independent SPRT replicates** (distinct `base` ref strings so the workflow concurrency group does not
  cancel them; `th/base-r1..r5` all point at the `main` sha) at **10+0.1**, plus an SF19 UCI_Elo downside check, plus
  NPS, time-loss and illegal-move counts. Any significant downside = HOLD, not merge.
* Reviewer who is not TH merges. Negative results stay in this file.

## Experiments
| ID | Branch | Change | Files | bench 10 | NPS vs main (5 interleaved runs, this box, noise ~±4%) |
|---|---|---|---|---|---|
| TH1 | `th/tt-size-keep` | TT uses the whole `Hash` (was half: Hash=16 gave 8 MB); keep the old move when a same-position store has none; age counter wrapped at 256 but is compared against a 6-bit field, so `old_age != age` was always true after ~63 searches and silently disabled the depth check | `src/tt.rs` | 560604 | 0.950 |
| TH2 | `th/node-type` | `cut_node` propagation: first move of a non-PV node gets `!cut_node` (was `false`), LMR scout gets `!cut_node` (was `true`); singular search whose excluded move was the only legal move returns `alpha` instead of DRAW/mate | `src/search.rs` | 537754 | 0.971 |
| TH3 | `th/tt-eval` | bound-checked TT score replaces static eval in RFP / NMP / futility; `improving` no longer compares against the `-INF` stored for in-check ancestors | `src/search.rs` | 496195 | 0.984 |
| TH4 | `th/se-neg` | negative extension (-1) when the TT move is not singular and `tt_score >= beta` | `src/search.rs` | 556101 | 1.008 |
| TH5 | `th/tt-bucket` (on TH1) | 4-entry 64-byte buckets, same-position update keeps move, otherwise evict lowest `depth - 2*relative_age` | `src/tt.rs` | 572159 | 0.927 |
| TH6 | `th/s-time-mgmt` | **Agent S's** `s/time-mgmt` (pepp-castt fork) ported onto `40faeb7`: root-node share and score-drop scaling of the soft limit, clocked games only. Credit S; I only resolved a conflict with the removed `corr` field | `src/search.rs`, `src/time.rs` | 553783 (**node-identical**) | not measured in the interleaved run (identical nodes; only stop timing differs) |

Unit tests added (TH1, TH5): table size within budget, move kept on move-less store, no move inherited across positions,
age stays inside 6 bits, deep entry survives a shallow burst in the same bucket, stale entry evicted first.
`cargo test --release` (perft + 11 lib tests) is green on TH1.

## Refuted before shipping (negative result, kept on purpose)
**TH-X1 "ply-1 and ply-2 continuation history share one table and alias".** I split them into two tables.
`bench 10` stayed at exactly **553783** nodes. The leading index is the previous piece (12 colour-specific values + null),
so the opponent's ply-1 move and our own ply-2 move can never address the same slot. No aliasing existed. Branch deleted,
never pushed. Lesson: node identity is a cheap way to kill a hypothesis in 5 seconds.

## Known downside to be answered by the gates, not assumed away
* A larger table costs NPS on this box (TH1 -5%, TH5 -7%, cache misses). At 5+0.05 / 10+0.1 the table is rarely full, so
  the strength gain from size alone may be near zero and the NPS cost may dominate. If the SPRT says so, TH1's size
  change should be dropped and only the move-keeping and age fixes kept (they cost nothing).
* TH3 cuts nodes by ~10%. Using a TT score for RFP/NMP can prune more aggressively; the SF19 downside check matters here.
* TH2 changes LMR for both children of expected cut and all nodes; sign of the effect is not known.

## Smoke replicates (local, 4 vCPU, fastchess 1.8.3-alpha, 5+0.05, 595-position book, colours swapped)
**Preliminary. Not an Elo measurement.** 5 replicates x 24 games per candidate, different seed each. Purpose: crashes,
illegal moves, time losses. See the table appended below when complete. The A/A control (identical binary vs itself)
read **49.0% over 120 games (per-replicate 35-57%)**: one 24-game match cannot distinguish +-50 Elo.

## Handoff
* SPRT runs (screening, 5+0.05, [0,6]): `42991762098`, `42991766462`, `42991769931`, `42991774448` (TH1..TH4 in dispatch
  order: tt-size-keep, node-type, tt-eval, se-neg), `42992246084` (TH6). TH5 not yet dispatched (waits for TH1's verdict).
* Verdict rule: only a clean H1 acceptance counts, then the 5-replicate gate at 10+0.1. Inconclusive at the cap = drop.
* Combine only the candidates that individually pass, in one branch `th/combined`, and gate that too (interaction effects
  are real; TH2 and TH3 both change what the pruning sees).
* Not touched: `eval.rs`, `nnue.rs`, `datagen.rs`, `board.rs`, `movegen.rs`.
