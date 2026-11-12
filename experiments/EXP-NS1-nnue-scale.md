# EXP-NS1: NNUE output scale vs the search margins (Agent NS)

- **Responsible agent:** NS (new session, owner's Composio connection as `archanapriyadarshini1st-debug`).
- **Baseline:** `agentSD/selfdistill-on-ni` @ `41422e1` (SD1 + NI incremental accumulator). Net: SD1 `sd-net` from Actions run
  43035169390, artifact digest `609bd950...`, `net.bin` sha256 `a598bf2f32472e34fe2ae43e9b629e1a612ddd5607b42d6e994bee99a0cf1f5d`
  (equals the `net_sha` in SD1's gate config). SF19 sha256 `0f83d24c...da19`, fastchess 1.8.3-alpha.
- **Hardware:** 4 vCPU Intel Xeon 2.6 GHz, 3.9 GB, rustc 1.99.1, `target-cpu=x86-64-v2` (repo default). Concurrency 3.
- **Status:** **INCONCLUSIVE. Not promoted. HCE stays the default.** Nothing here is a strength claim vs the owner's target.

## Hypothesis
The search margins (RFP, futility, razoring, SE, NMP eval/200, aspiration, SEE/history) were tuned for HCE scores. If the net's
score scale differs from HCE's, every margin silently changes meaning and a better evaluator can under-perform.

## Measurement 1 - score scale (preliminary, 1 sample of positions)
1083 quiet positions (no capture/check into them, ply 14-140) sampled from 60 NET-vs-HCE games (3+0.03); labelled by SF19 d12,
1 thread, **mate scores and |SF| >= 1000 dropped (57 positions)** -> N = 1026. Scripts + raw data in `EXP-NS1/`.

| eval | std (cp) | corr with SF19 | slope SF19 ~ eval |
|---|---|---|---|
| HCE | 337 | 0.834 | 1.06 |
| SD1 net | 509 | 0.823 | 0.69 |

Reading: HCE is already on SF19's scale; the net is about 1.45x wider. Likely cause (untested): 25 % of the SD1 target is the game
result through a fixed sigmoid K. Positions come from games the net itself played, so the sample is not independent of the net.

## Change (default-neutral)
`NnueScale` UCI spin (percent, default 100, 30..200). `nnue::output()` multiplies by it before the +-3000 clamp. At 100 this is
`x*100/100`: bench identical (465476 nodes with net, 553783 HCE), `cargo test --release` green. It does not affect HCE.

## Measurement 2 - does rescaling help? (screen)
Same binary, same net, only `NnueScale`: **70 vs 100**, 5 replicates x 60 games, 5+0.05, Hash 64, 1 thread, `openings_book.epd`
(sha256 `f1d9e14283d1...`), colours reversed (`-repeat`), `-srand` 1037/1074/1111/1148/1185. Logs + PGN in `EXP-NS1/`.

| rep | W-D-L (70 as CAND) | score |
|---|---|---|
| 1 | 10-35-15 | 45.8 % |
| 2 | 17-30-13 | 53.3 % |
| 3 | 18-33-9 | 57.5 % |
| 4 | 7-41-12 | 45.8 % |
| 5 | 13-40-7 | 55.0 % |
| **pooled** | **65-179-56 / 300** | **51.5 %, +10.4 Elo [-14.5, +35.5], LOS 79 %** |

Pre-registered rule (fixed before any game): screen is positive only if pooled > 52 % AND >= 4/5 replicates > 50 %.
Observed 51.5 % and 3/5 -> **rule not met**. 0 illegal moves / crashes / time losses in 300 games.
Limits: no A/A control was run (so the noise floor is taken from other agents' A/A rows: a 600-game run is about +-17 Elo,
a 300-game run about +-25); 5+0.05 only; one scale value only. +10 Elo would need ~3000 games to resolve.

**Decision: inconclusive; keep `NnueScale=100`.** The scale mismatch is real as a measurement, but at 70 it does not show an Elo
effect large enough to see in 300 games. It is not evidence that the margins are well tuned for the net: it means a 1-parameter
rescale is not a large lever. Re-tuning the margins jointly with the net on (SPSA) remains untested.

## Measurement 3 - endgame sanity audit of the net (operational downside check, 13 hand-picked positions)
`EXP-NS1/endgames.py`, depth 14 engine vs SF19 depth 20, legal positions only (checked with python-chess).
No crash, KBvK/KNvK/wrong-bishop = 0, 50-move clock at 98 = 0. But on drawish endgames the net is **more** optimistic than HCE and both
are far from SF19: KPK opposition +443 net / +301 HCE / 0 SF19; same-colour bishops +251 / +104 / +7; KRvKB +452 / +307 / +33;
KRPvKR -220 / -127 / 0. KNNvK is +648 for both (SF19 0). Anecdotal (13 positions) but it matches the "net is wider" finding and points to
drawishness damping (cf. #48 EG) as the next thing to test for the net path.

## Robustness note (low severity, not fixed here)
`position fen` with the side NOT to move in check (illegal) then `go` panics: `attacks.rs:397 index out of bounds (64)`, the king
gets captured in search. GUIs do not send such FENs; a one-line validity check in the FEN parser would remove it. Found by
accident via my own malformed test FENs.

## Next (what I would test, each as its own experiment)
1. A/A control + 10+0.1 repeat only if someone wants this axis; otherwise fold `NnueScale` into SPSA with the net on.
2. Drawishness damping on the net output for low-material / fifty-move states (separate EXP).
3. Train-side fix at the source: lower WDL weight or fit the sigmoid K to the SD1 score scale, then re-gate (needs training compute; TL/IV lanes).
