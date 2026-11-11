# EXP-KB1 - Where do we lose against SF19 UCI_Elo 3000? (primary-target audit + NNUE position-level check)

- **Experiment ID:** EXP-KB1
- **Responsible agent:** Agent KB (session started 2026-11-11 ~14:20Z)
- **Repository / baseline:** `archanapriyadarshini1st-debug/Chess-rust-engine`, `main` `581b8ee`, engine source = `40faeb7`
- **Binary:** sha256 `4d3b1bbc62d96479...`, `bench 10` = **553783** nodes (reproduced independently; matches X1/RV/CC/FN/TR)
- **Opponent:** Stockfish 19 `stockfish-linux-x86-64-universal` sha256 `0f83d24cc46d2c66...`
- **Net used in part 3:** R's Lichess net, run 43007306133, `net.bin` sha256 `bb5bb8a868c12387...` (same short sha LS cited)
- **Hardware:** Intel Xeon @ 2.60 GHz, 4 vCPU, 3.9 GB, Linux 6.1; rustc 1.99.1, `.cargo/config.toml` as shipped (`x86-64-v2`)
- **Status:** diagnostic measurement. **No engine change. No strength claim for any candidate.**

## Hypotheses (written before the first game)

1. The owner-target matchup may contain non-strength failures (time forfeits, crashes, illegal moves) that are free Elo and that contaminate gates.
2. If there are none, the losses come from somewhere in {search, eval, time}; the match PGN's own per-move scores can discriminate eval-vs-search.

Decision rule: any non-strength failure becomes a fix PR with its own 5-replicate ship gate. Otherwise report cleanly.

## Part 1 - the match (two independent replicates, labelled PRELIMINARY)

Config for both: fastchess v1.8.3-alpha, `tc=10+0.1`, `Threads=1`, `Hash=64` both engines, SF19 `UCI_LimitStrength=true UCI_Elo=3000`,
`tools/openings_book.epd` (sha256 `f1d9e14283d12cb3...`, 595 positions), colours reversed per opening (`-games 2 -repeat`), 30 rounds,
concurrency 2, adjudication `-draw 40/8/20 -resign 3/600`. Seeds differ.

| replicate | seed | W-D-L | score | Elo vs opp. (limiter scale) | 95% CI |
| --- | --- | --- | --- | --- | --- |
| A | 4242 | 6-15-39 | 22.5% | -215 | [-315, -139] |
| B | 7777 | 3-12-45 | 15.0% | -301 | [-425, -219] |
| **pooled (120 games)** | | **9-27-84** | **18.75%** | **-255** | **[-327, -197]** |

A and B differ by 1.05 sigma, i.e. consistent with each other. This also lines up with AU's reported 27.5%/60 (not re-counted here).
Gap to the owner's 80% gate: 80% is +241 limiter-Elo, so **about +496 Elo from here**. UCI_Elo is not CCRL Elo; I make no 3000 claim.

**Hypothesis 1 result: rejected.** Across 120 games: 0 time forfeits, 0 illegal moves, 0 disconnects/crashes/stalls (grep of raw logs for
`loses on time|illegal|disconnect|stall|crash` = 0 in both). Max single-move time 1.59 s / 1.75 s at 10+0.1. Loss terminations are
adjudications at |score| >= 6.00 (81) plus 3 "normal" terminations (mate/stalemate). **Nothing to fix there; the time manager is not what is losing games.**

## Part 2 - where do the losses come from? (hypothesis 2)

Method (`audit.py`, `tools/blindspots.py`): for each lost game, find the first ply where SF's *own reported* score is >= +1.00 for
three consecutive SF moves ("SF-decisive"), and the first ply where *our own* reported score is <= -1.00 for three consecutive moves
("we are aware"). Thresholds are applied on each engine's own scale, so the lag measure is not a cp-calibration artefact.

| | replicate A | replicate B |
| --- | --- | --- |
| mean search depth, Rust / SF19@3000 | 17.7 / 14.9 | 17.7 / 14.3 |
| losses | 39 | 45 |
| median SF-decisive ply | 35 | 36 |
| Rust's own eval at that moment >= -0.30 ("blind") | 33 / 39 | 35 / 45 |
| **median lag until Rust itself sees -1.00** | **21 plies** | **17 plies** |
| lag >= 10 plies | 29 / 39 | n/a (median 17) |
| lag <= 2 plies | 0 / 39 | - |
| losses where Rust never saw -1.00 before the end | 0 | 0 |

So Rust searches **deeper** than the limited SF, and still needs ~8-10 full moves longer than SF to realise it is worse. It is not
unaware to the end; it is late, in the early middlegame.

Teacher relabel of the 39 replicate-A decisive positions (`blindspots_a.jsonl`; SF19 **full strength**, 2 s, 1 thread, MultiPV 3;
Rust depth 14; all from Rust's point of view, Rust to move):

- median teacher **-184 cp** vs Rust **+14 cp**: median overrate **+215 cp**; overrate >= 100 cp in **34 / 39**
- **27 / 39 have |material diff| <= 100 cp**: the deficit is positional, not a hung piece
- Rust's chosen move lies in the teacher's MultiPV-3 in **28 / 39**: move choice is not the main problem; the position was already worse
- median 23 pieces on the board (middlegame)

Rerunning the same extractor twice moved these numbers by a few cp / one position (teacher 2 s on 1 thread is not deterministic).

**Hypothesis 2 result: supported (preliminary).** Evidence points at static evaluation in quiet middlegames, not at depth, the clock,
or tactics. This agrees with LS's and the roadmap's NNUE-first conclusion and with SP/FN's finding that search patches are +/-10 Elo.

**Caveats (not hidden):** (a) the limited SF's early +1.00 is itself noisy, but the independent full-strength 2 s teacher confirms
(median -184 cp); (b) HCE cp and SF-normalised cp are different scales, which is why the lag test uses own-scale thresholds;
(c) positions come from games, so they are biased toward lines the HCE engine walks into.

## Part 3 - does R's net see these positions better? (position level, NOT a strength test)

Careful: the 39 positions above were *selected* because HCE was wrong, so any pessimistic evaluator would look good on them.
I report that number and then discard it in favour of an unselected control:

- selection-biased (n=39): NNUE depth-14 search is negative in 36/39 (HCE 6/39 negative statically, depth-14 median +14). **Do not cite.**
- **unbiased control (`control.py`, n=232):** every game of both PGNs, position at ply 30 and ply 50 (adjacent ply if needed so Rust is
  to move), regardless of outcome. Teacher = SF19 MAX 1.5 s 1 thread. HCE and NNUE both run the *same binary*, depth 12; NNUE via
  `CRE_NNUE_FILE`. Scores clipped to +/-600.

| evaluator | corr. with teacher (95% bootstrap CI) | sign accuracy where abs(teacher) >= 100 (n=115) | mean bias vs teacher |
| --- | --- | --- | --- |
| HCE | 0.741 [0.686, 0.789] | 76.5% | +145 cp |
| R's Lichess net | **0.928** [0.912, 0.942] | **97.4%** | +56 cp |
| paired difference | **+0.186 [+0.143, +0.236]** | | |

Per replicate (independent games): HCE 0.734 / 0.747, NNUE 0.919 / 0.935. Same direction both times.

**Why this is not a promotion argument.** (1) The net was trained on SF-derived Lichess evals, so high agreement with SF19 is
*teacher fidelity*, not playing strength; (2) the bias comparison favours a net trained on SF-scale labels; (3) nothing here measures
nps loss or how the net behaves in search over a whole game. LS's 5 x 200-game gate vs HCE is the test that decides. What this does
add: a **mechanism** for R's 60% / 40-game lead (the net removes most of the specific blindness that is losing games at the owner's
target), and independent support that the volume hypothesis (more Lichess shards, LS-2) is the right lever.

## Decision

- Hypothesis 1: rejected, nothing to fix. **Keep current time management as is** (CX/TH6 own that change).
- Hypothesis 2: supported, preliminary. **Evidence-ranked priority: eval/NNUE over any search patch.**
- No code in `src/` changes. Result is a diagnostic, not a candidate.

## What I will not claim

- No Elo rating. 120 games resolve about +/-70 limiter-Elo, and UCI_Elo is not calibrated this high.
- No claim that the net is stronger than HCE in play. Needs LS's gate.
- 3000 and 80% are not near; the measured gap is ~+500 limiter-Elo.

## Reproduce

```bash
cargo build --release
fastchess -engine cmd=./target/release/chess-rust-engine name=Rust option.Hash=64 option.Threads=1 \
  -engine cmd=./stockfish name=SF19e3000 option.Hash=64 option.Threads=1 option.UCI_LimitStrength=true option.UCI_Elo=3000 \
  -each tc=10+0.1 -rounds 30 -games 2 -repeat -concurrency 2 -srand 4242 \
  -openings file=tools/openings_book.epd format=epd order=random \
  -draw movenumber=40 movecount=8 score=20 -resign movecount=3 score=600 -maxmoves 400 -pgnout file=a.pgn
python tools/summarize.py a.pgn --engine Rust --opp-elo 3000
python tools/blindspots.py a.pgn --engine Rust --ours ./target/release/chess-rust-engine --stockfish ./stockfish --out b.jsonl
python experiments/EXP-KB1/audit.py a.pgn
```
