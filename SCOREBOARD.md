# SCOREBOARD (single shared record)

Maintained by Agent NP as a first version; **every agent updates the rows it owns in its own PR**. Repository:
`archanapriyadarshini1st-debug/Chess-rust-engine` (authoritative). Written at `main` **581b8ee**, 2026-11-11 ~14:00Z.
Nothing here is a rating claim. UCI_Elo is a limiter scale, not CCRL. Numbers were recomputed from raw W/D/L in the
Actions logs (trinomial 95 % CI, logistic Elo), not copied from comments.

## 1. Current stable
| item | value |
|---|---|
| stable commit | `main` 581b8ee (code identical to 40faeb7 + docs) |
| default eval | HCE (no NNUE net has earned promotion) |
| `bench 10` | 553783 nodes |
| last-known-good rollback | 451d933 / 40faeb7 (see `tools/net_registry.py` for nets) |

## 2. Verified strength (owner target: >= 80 % vs SF19 UCI_Elo 3000 at 10+0.1 — **NOT MET**)
| measurement | result | n | status |
|---|---|---|---|
| main 40faeb7 vs SF19 UCI_Elo 2600, 10+0.1, 5 replicas (Agent X1) | 67.3 % [63.4, 71.2] = +125 limiter-Elo | 500 | adequate sample |
| main vs SF19 UCI_Elo 2900 (issue #1, 10:52Z) | 17.5 % (+1 =5 -14) | 20 | **preliminary** |
| SF19 MAX fixed-node ladder (`odds-ladder.yml`) | infrastructure exists, no result found by NP | - | open |
The earlier "81.8 % vs 2600" (44 games) is **not** used: a 500-game replication gave 67.3 %.

## 3. Evidence ledger (head-to-head `sprt.yml`, recomputed by NP from raw logs)
SPRT-stopped runs are biased upward; a positive row means "replicate", not "merge".

| candidate | PR | tc | W-D-L | n | Elo [95 % CI] | reading |
|---|---|---|---|---|---|---|
| time: stability fix on top of #43 | #47 | 10+0.1 | 228-553-145 | 926 | +31 [+17, +45] | positive, **needs 5x replication** |
| TT score refines eval for pruning | #41 | 5+0.05 | 274-718-194 | 1186 | +23 [+11, +36] | positive, needs replication |
| time: root-share + score-drop scaling | #43 | 5+0.05 | 342-830-262 | 1434 | +19 [+8, +31] | positive; inherits stability bug fixed in #47 |
| cut_node propagation | #40 | 5+0.05 | 393-1107-448 | 1948 | -10 [-20, 0] | not better |
| negative ext. non-singular TT move | #42 | 5+0.05 | 454-1404-502 | 2360 | -7 [-16, +2] | not better |
| capture ProbCut + razoring | #18 | 10+0.1 | 286-202-312 | 800 | -11 [-32, +10] | not better |
| Texel-tuned HCE (5 replicas, `texel-1a-r1..r5`) | TX | 10+0.1 | 927-1010-1063 | 3000 | **-15.8 [-25.9, -5.6]**, chi2 2.61 (df 4) | **reject** (replicas agree) |
| A/A control (identical engines) | TX | 10+0.1 | 114-361-125 | 600 | -6 [-24, +11] | shows the noise floor of one 600-game run |
| Q toggles XCapLmr / XLmrFut / XDeeper / XFailHighRed (2x300 each) | #46 | 10+0.1 | pooled | 600 each | +5 / -5 / +2 / +3, all CI +-17 | indistinguishable from 0 |
| `XNmpNoDouble` (NP probe) | - | bench | 553783 vs 553781 nodes | - | never fires | **dropped** |

Lesson from the A/A row: a single 600-game run has a +-17 Elo error bar. Any claim below ~+/-17 from one run is noise.

## 4. Open experiments (NP)
| id | question | runs | rule |
|---|---|---|---|
| EXP-NP1 | blanket in-check extension: `XCheckExt=1` (PV only) / `=0` vs identical binary | 10 runs x 800 games, 10+0.1 | `experiments/EXP-NP1-check-extension.md` |
| EXP-NP2 | do #43+#47 (time) and #41 (TT-eval) stack? vs unmodified main | 5 runs x 800 games, 10+0.1 | `experiments/EXP-NP2-integration-stack.md` |
Live tracker with the same statistics: the NextGen Command Center app (pools replicas, chi2, verdict by the pre-registered rule).

## 5. Bottlenecks
1. **Evidence, not ideas.** ~25 draft PRs, ~6 with a positive single run, none replicated 5x, and nobody had measured whether positives stack (EXP-NP2).
2. **Strength gap at the top.** 67 % vs 2600 but ~17 % vs 2900: the owner target needs roughly +300 limiter-Elo more. The only lever of that size remains a net that beats HCE; Texel-tuning HCE was negative.
3. **Sample size.** At ~20 % draws, +10 Elo needs ~3000 games, +5 needs ~12000. One 600-game run cannot see anything under ~17.
4. **Harness traps:** stdin-EOF counts as `stop` (RV); `sprt.yml` concurrency group `sprt-${test}-${base}` cancels replicas that share both strings (use distinct base refs); mixing 5+0.05 and 10+0.1 numbers; SPRT-stopped upward bias.

## 6. Next priorities (proposal, in order)
1. Finish EXP-NP1/NP2 replicas; log check for forfeits/illegal/crashes.
2. 5x SF19 UCI_Elo downside check for whichever stack is PROMISING; second reviewer reads the integrated diff.
3. Stack-aware merge queue: merge positives one at a time, re-measure after each (no blind batch).
4. NNUE: only the volume/outcome experiments (NV) can change the ceiling; keep HCE fallback until a net passes the 5x gate.
5. Re-run main vs 2900 with >= 100 games and 5 replicas so the owner target has a real baseline.

## 7. Active lanes (from PR list and issue #1, 2026-11-11)
TH tree hygiene (#39-45) · TT table (tt.rs) · Q LMR/pruning toggles (#46) · BC move ordering · CX time correctness (#47) ·
EG/EG2 endgame (#48, #49) · FN fixed-node lab + mate/50-move (#51) · SP/CC/W SPSA (#50, spsa.yml) · TX Texel at scale ·
NV NNUE volume · NI NNUE incremental · AU static threat eval · S2 Lazy SMP (#27) · N persist/corrhist (#28) · Z datagen-bin (#22) ·
X1 correctness oracle (#38) · RV/PV/U/V2 review + equivalence tools · S/S3/T2 ship gates · L evidence ledger ·
**NP search structure (check-extension) + integration test + this scoreboard**.
