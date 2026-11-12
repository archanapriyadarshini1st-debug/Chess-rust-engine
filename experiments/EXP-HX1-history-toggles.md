# EXP-HX1 - threat-aware ordering, pawn history, 4-ply continuation history, singular double extension

Responsible agent: **HX**. Repo: `archanapriyadarshini1st-debug/Chess-rust-engine` (authoritative).
Baseline: `main` **581b8ee** (bench 10 = **553783**). Branch `agentHX/history-toggles` (changes pushed as the `agentHX/t1..t12` aliases, all at one commit).
Nothing here is a rating claim. UCI_Elo is a limiter scale, not CCRL.

## Hypothesis
`quiet_hist` is a plain `[side][from][to]` butterfly + 1/2-ply continuation history. Four documented ideas (Stockfish / Berserk /
Viridithas / Reckless; re-implemented independently, no source copied) each improve move ordering or tree shape:

| toggle (UCI spin, default 0 = off) | change | why it might help | why it might hurt |
|---|---|---|---|
| `XThreatOrd` (+`XThreatScale`=100) | quiet ordering bonus for moving a piece attacked by a lesser enemy piece, malus for stepping onto a square a lesser piece attacks (ordering only, never pruning/LMR) | finds escape/avoid-loss moves earlier, better cutoffs | extra 6 attack lookups per interior node (NPS); wrong sign on defended squares |
| `XPawnHist` | history `[pawn-structure slot 512][piece][to]` added to `quiet_hist` (so also LMR / history pruning) | structure-specific move quality | changes magnitude of `mv_hist` seen by LMR/pruning thresholds (tuned for the old range); 786 KB table |
| `XConthist4` | ply-4 continuation history added to `quiet_hist` and updated | longer-range move pairing | same magnitude shift; sparser table |
| `XDblExt` (+`XDblMargin`=30) | singular extension becomes +2 when the singular search fails low by > margin, non-PV only, <= 3 per path | resolves forced lines | the old code hung bench d10 on stacked extensions - capped per path, but tree explosion is the risk |

Defaults are off: `bench 10` = **553783 nodes** (identical to main, verified), `cargo test --release` green incl. new `tests/hx_toggles.rs`
(defaults 0, default search deterministic and restored exactly after toggling, each toggle returns a legal move with no node explosion on 6 positions).

## Fixed-depth side effect (NOT a strength result)
`bench 10` nodes with the toggle on (main = 553783): XThreatOrd 528134 (-4.6%), XPawnHist 535156 (-3.4%), XConthist4 563228 (+1.7%), XDblExt 548288 (-1.0%). NPS 1.67M / 1.73M / 1.75M / 1.83M vs 1.75M. Fewer nodes at equal depth is not proof of strength.

## Method (pre-registered before any game of this experiment was played)
Same-binary A/B: TEST = branch with `option.X...=1`, BASE = identical commit with all toggles at default. Build noise excluded.
`sprt.yml` 10+0.1, Hash 16, 1 thread, `openings_book.epd`, colours swapped, **450 rounds = 900 games per run, bounds (-2, +2) so the SPRT cannot stop early (v2; see the failed v1 below)**. Distinct `test` aliases keep the workflow concurrency group from cancelling replicas.

| arm | runs | toggles |
|---|---|---|
| TP (bundle) | 3 | XThreatOrd + XPawnHist |
| T | 2 | XThreatOrd |
| P | 2 | XPawnHist |
| C4 | 2 | XConthist4 |
| D | 2 | XDblExt |
| A/A control | 1 | none (identical engines) |

Plus a local, independent-hardware replication of TP: 5 x 160 games at 5+0.05 (4 vCPU sandbox, fastchess 1.8.3-alpha, 3 concurrent).

Decision rule (fixed now): an arm is **PROMISING** only if pooled Elo 95% CI lower bound > 0 and no replica < 45%. PROMISING earns 5 more replicas
(7+ total) and a 5x SF19 UCI_Elo downside check; only then a merge request. Else **NOT SHOWN** (kept here as negative/inconclusive result).
The A/A run must be consistent with 0 or the whole experiment is void. Trinomial 95% CI, logistic Elo, recomputed from raw W/D/L.
Not claimed in advance: any amount of Elo.

## Runs v2 (valid design, dispatch order)
- TP-1: run 43226471910 (test ref agentHX/t1) in_progress 2026-11-12T13:21:14Z
- TP-2: run 43226476610 (test ref agentHX/t2) in_progress 2026-11-12T13:21:16Z
- TP-3: run 43226481520 (test ref agentHX/t3) in_progress 2026-11-12T13:21:18Z
- T-4: run 43226486863 (test ref agentHX/t4) in_progress 2026-11-12T13:21:20Z
- T-5: run 43226490704 (test ref agentHX/t5) in_progress 2026-11-12T13:21:21Z
- P-6: run 43226495610 (test ref agentHX/t6) in_progress 2026-11-12T13:21:23Z
- P-7: run 43226500664 (test ref agentHX/t7) in_progress 2026-11-12T13:21:25Z
- C4-8: run 43226504635 (test ref agentHX/t8) in_progress 2026-11-12T13:21:27Z
- C4-9: run 43226508624 (test ref agentHX/t9) in_progress 2026-11-12T13:21:28Z
- D-10: run 43226514237 (test ref agentHX/t10) pending 2026-11-12T13:21:30Z
- D-11: run 43226519836 (test ref agentHX/t11) in_progress 2026-11-12T13:21:32Z
- AA-12: run 43226524955 (test ref agentHX/t12) pending 2026-11-12T13:21:34Z

## Runs v1 - VOID (methodology failure, kept on purpose)
I first dispatched with bounds (-50, +50) believing that would prevent early stopping. It does the opposite: LLR crossed +-2.94
after 22-66 games on every run I inspected (TP-1 7-1-14/22, TP-2 W10 L14 D42 over 66, T-4 W12 L18 D36 over 66 ... see run logs) and the workflow printed
"SPRT completed - H1 was accepted" on a +97 +-89 Elo estimate over 22 games. These runs are not used for any claim.
- TP-1: run 43224315995 (test ref agentHX/t1) in_progress
- TP-2: run 43224319746 (test ref agentHX/t2) in_progress
- TP-3: run 43224323186 (test ref agentHX/t3) in_progress
- T-4: run 43224327361 (test ref agentHX/t4) in_progress
- T-5: run 43224332220 (test ref agentHX/t5) in_progress
- P-6: run 43224336476 (test ref agentHX/t6) in_progress
- P-7: run 43224340911 (test ref agentHX/t7) in_progress
- C4-8: run 43224345541 (test ref agentHX/t8) in_progress
- C4-9: run 43224349887 (test ref agentHX/t9) in_progress
- D-10: run 43224354459 (test ref agentHX/t10) in_progress
- D-11: run 43224358909 (test ref agentHX/t11) in_progress
- AA-12: run 43224363701 (test ref agentHX/t12) in_progress

## Results
(to be appended)
