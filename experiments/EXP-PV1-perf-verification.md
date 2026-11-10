# EXP-PV1 — do the node-identical perf PRs (#25, #26) really change nothing but speed?

- **Responsible agent:** PV (performance verifier). New session, same owner account. Touches no `src/`, no workflow, no `main`.
- **Repository / baseline:** `archanapriyadarshini1st-debug/Chess-rust-engine` `main` = `52cb805` (after #30, corrhist reverted, SE kept).
- **Candidates:** PR #25 (`506bdb5`) and PR #26 (`3929fc9`), each merged onto `52cb805` locally, plus both together.
- **Hypothesis:** both PRs are *search-neutral*: for every position and depth they produce the same nodes, score and best move as `main`, and they are faster.
- **Why a new check:** `bench` is a single position set. PR #5 and `main` both printed `178914` at d8 while one of them played 12.5% vs UCI_Elo 2400. "Bench-identical" is therefore not enough evidence that a patch is search-neutral. `tools/perf_equiv.py` (added here) is the stronger check.
- **Possible regressions looked for:** changed node counts (hidden search change), changed best move/score, slower in some conditions, test failures, unsafe-code faults.

## Method (`tools/perf_equiv.py`, one command, reproducible)

1. **Determinism control** - `main` run twice; must agree with itself on every search, otherwise the comparison is meaningless and the tool aborts.
2. **Equivalence** - 40 positions (7 hand-picked tactical/endgame + 33 from the 595-position book, seed 1) x depths 6, 8, 10 = **120 searches**, fresh process per search, Hash 16, 1 thread. Compare `(nodes, score, bestmove)`.
3. **Speed** - `--rounds` interleaved rounds of the engine's own `bench 10` (excludes process start-up; a first draft that timed whole processes read 0.045 Mnps, i.e. measured start-up, and was discarded). Verdict uses best-of-N because this sandbox is noisy.

```
python3 tools/perf_equiv.py --base ./bin_main --test ./bin_pr --positions 40 --depths 6,8,10 --rounds 5 --json out.json
```

## Environment

Intel Xeon @ 2.60 GHz, 4 vCPU shared sandbox, Linux 6.1.189, rustc 1.99.1, `RUSTFLAGS="-C target-cpu=native"`, release profile from `Cargo.toml` (LTO, 1 CGU).
One machine, shared tenancy: **speed numbers are indicative, not publishable**; run-to-run CV was 4-9%.
Binary sha256 (first 16): main `2e0a138ac504afd3`, #25 `03ed3ab024ced767`, #26 `31a7232e1da2c30d`, #25+#26 `5ecbf4a5f92581d9`. Book sha256 `f1d9e142...` (matches Agent O). Raw JSON in `EXP-PV1-data/`.

## Results

| candidate (on top of `52cb805`) | determinism | identical searches | NPS best-of-N | NPS median-of-rounds | `cargo test --release` | verdict |
|---|---|---|---|---|---|---|
| #25 (shared attacks in eval, TT prefetch) | ok | **120/120** | +8.1% (7 rounds) | +9.1% | not rerun alone | PASS |
| #26 (captures-only qsearch generator) | ok | **120/120** | +10.0% (7 rounds) | +7.1% | not rerun alone | PASS |
| **#25 + #26 together** | ok | **120/120** | **+12.8%** (5 rounds) | **+20.9%** | **all pass (7+3+4)**, incl. #26's new `noisy_gen_equals_filtered_pseudo_legal` | PASS |

Bench 10 nodes: 553783 for base, #25, #26 (all identical). #25 and #26 touch disjoint files, merge cleanly, and the merge is still node-identical.

## Code review (read-only)

- **#26:** `gen::<NOISY>` returns exactly `pseudo_legal` filtered to captures/promotions/EP, same order (so ordering and therefore the tree are unchanged). Promotion-pushes are kept via the last-rank mask; double pushes and castling are skipped. The new unit test walks 8 FENs x 80 random games x 120 plies (>40k positions) comparing the two lists element-by-element and asserts it exercised promotions and en passant. I have no correctness objection.
- **#25:** `prefetch` indexes with `hash & mask` (in bounds); a prefetch hint cannot fault or change a result. `unsafe` is limited to that one intrinsic call and is `cfg`-gated to x86_64. No objection.

## Also found

- **#27 (Lazy SMP) does not merge cleanly with current `main`**: conflict in `src/search.rs` (it predates the #30 corrhist revert). It needs a rebase by its author before any gate result on it is meaningful. I did not touch it.

## Decision

**KEEP / recommend merge of #25 and #26** (reviewer sign-off from someone who did not write them). No Elo claim: node-identical means the *search* is unchanged, so the only strength effect is more nodes per second at fixed time; I have not measured that in games and do not claim it. Note for Agent K's fixed-node ruler: fixed-node results are unaffected by these PRs by construction.

## Limits (not hidden)

120 searches at depth <= 10 cannot prove identity at every depth/position (no test can); it makes an accidental behavioural change very unlikely and, unlike `bench`, would have caught a PR-#5-style change. SMP (`Threads>1`) is not deterministic and is out of scope here. Speed was not measured on quiet hardware.

## Addendum - 5x replicated side-effect probe (games, NOT an Elo measurement)

Owner rule: "test it 5 times before shipping; does it have a downside?". `main` (52cb805) vs `#25+#26` (local merge, bin sha `5ecbf4a5f92581d9`),
fastchess 1.8.3-alpha, **5 independent replicates** (srand 20269029, 20276948, 20284867, 20292786, 20300705), 12 games each, 5+0.05, Hash 64,
concurrency 2, 595-position book, colours swapped (`-repeat`), draw/resign adjudication as in `sprt.yml`. Raw PGNs: `EXP-PV1-data/rep{1..5}.pgn`.

| replicate | #25+#26 W-D-L vs main | score |
|---|---|---|
| 1 | 1-9-2 | 45.8% |
| 2 | 6-5-1 | 70.8% |
| 3 | 2-5-5 | 37.5% |
| 4 | 4-8-0 | 66.7% |
| 5 | 1-10-1 | 50.0% |
| **pooled** | **14-37-9** | **54.2% over 60 games** |

- **Side effects:** 0 illegal moves, 0 disconnects/stalls/crashes, 0 time losses in all 60 games (grep of all five logs; terminations: 34 normal, 26 adjudication).
- **What the spread teaches:** identical engines-pair, identical settings, replicate scores range 37.5%-70.8%. A single 12-game (or even 20-game) match cannot rank a patch; that is the reason for replicating and for SPRT.
- **What it does not show:** 60 games has a +/- ~8 percentage-point (about +/-55 Elo) error bar. The pooled 54.2% is consistent with "no downside, small gain from speed", and equally with "no effect". I make **no strength claim**; the evidence for safety is the 120/120 node-identity result, the games only confirm there is no operational problem (crashes, illegal moves, time forfeits) with the faster binary.
