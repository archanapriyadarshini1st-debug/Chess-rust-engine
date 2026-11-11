# EXP-KB1 - king-bucketed + file-mirrored NNUE inputs (CRN2)

- **Experiment ID:** EXP-KB1
- **Agent:** KB
- **Repository / baseline:** `archanapriyadarshini1st-debug/Chess-rust-engine` `main` **581b8ee** (engine = 40faeb7).
  `bench 10` = **553783** nodes on main and on this branch (5 interleaved rounds, identical every time).
- **Status:** implementation + parity done; **strength experiment pre-registered below, NOT yet run. No Elo claim.**

## Hypothesis
The current net uses 768 king-agnostic inputs. Every strong engine this project cites for architecture
(Stockfish HalfKA family, Viridithas, Reckless, Berserk) conditions the input layer on the friendly king
square (bucketed, with left-right mirroring). With the same ~15M Lichess positions and the same trainer,
a king-bucketed 8 x 768 input layer should lower held-out error **and** play stronger than the plain
768 net, because king safety / king-relative piece placement is exactly what a king-agnostic layer
cannot express and what the HCE currently hand-codes.

Counter-hypothesis (why this may fail): 8x more first-layer rows are fed by the same 15M positions, so
each row sees ~8x less data; the plain net may win at this data volume. That is a real possibility
and is what the experiment measures.

## Change (one variable: feature set)
- `src/nnue.rs`: new net magic `CRN2` (header unchanged, `features = 768 * 8`). Per perspective the row is
  `bucket(king) * 768 + CRN1_index(square ^ mirror_mask)`; `KB_TABLE[rank*4 + mirrored_file]`; mirror when
  the perspective's king is on files e-h. **CRN1 nets keep bucket 0 / mask 0 = bit-identical legacy indexing.**
  Default behaviour is unchanged: the embedded net is CRN1, HCE stays default.
- `tools/nnue/train.py`: `--kb` (CRN2 export), `--steps` (step-based LR schedule so arms see **equal samples**,
  `--minutes` becomes a safety cap and the log prints `!!` if the cap is hit).
- `tools/nnue/parity_check.py --kb`: independent python-chess reference (king via `board.king`) vs engine vs
  trainer `decode()`; the CI job runs it (with `--trainer`) before any training starts.
- `tools/gate_two_nets.sh`, `tools/pool_gates.py`, `.github/workflows/kb-ab.yml`.
- Not touched: `search.rs`, `board.rs`, `eval.rs`, `uci.rs`, `params.rs`. `nnue.rs` is also edited by NI's #52
  (incremental accumulator): the conflict is confined to `eval_impl`. With CRN2 an incremental accumulator must
  refresh a perspective when that king changes bucket or crosses the e/d file boundary; that is NI's follow-up,
  not claimed here. Full refresh per eval is correct for both formats.

## Correctness evidence (local, 2026-11-11, x86-64, rustc 1.99 stable, 4 vCPU)
| check | result |
| --- | --- |
| `cargo test --release` (whole suite) | all pass (11 + 3 + 4 + new nnue tests) |
| CRN2 constant-weight net == CRN1 constant-weight net on 7 FENs | pass |
| CRN2 left-right mirror invariance (random net, 7 FENs) | pass (exact equality) |
| CRN1 indexing unchanged (CRN1 net is *not* mirror invariant) | pass |
| `parity_check.py` CRN1, 400 positions, all 8 material buckets | PARITY OK, worst 1.01 cp |
| `parity_check.py --kb`, 400 positions | **PARITY OK, worst 1.02 cp**, trainer decode() 0.0000 cp |
| `bench 10`, embedded net, 5 interleaved rounds vs main | 553783 nodes every round |
| `bench 8`, random CRN1 net, 5 interleaved rounds vs main | 1,209,426 nodes every round |
| NPS, CRN1 path, branch vs main | -1% (embedded) / +2% (CRN1 net) medians; machine noise was +-8%, i.e. no measurable change |
| CRN2 path NPS (random net, bench 8) | 929k nps vs ~990k CRN1 (about 6% slower eval at full refresh; incremental accumulators remove most of it) |

## Strength experiment (pre-registered before any game; `.github/workflows/kb-ab.yml`)
- Data: R's converted Lichess shards 0 and 1 (run 43007306133 artifacts), byte-identical for both arms
  (`data_sha.txt` must match between arms). Score-only labels, `--lam 1.0`, no invented WDL.
- Arms: `plain` (CRN1) vs `kb` (CRN2). Same seed, H=128, 8 output buckets, batch 16384, lr 2e-3,
  `--steps 80000`. Validation split is the trainer's position-hash split (never trained on).
- Gate: **5 replicates** (distinct `-srand` 101/202/303/404/505), each 200 games KB-vs-PLAIN and 100 games
  KB-vs-HCE, 10+0.1, 1 thread, 64 MB, `openings_book.epd`, colours reversed, one engine binary.
- Pooled with `tools/pool_gates.py` (logistic Elo, trinomial 95% CI, LOS, chi-square heterogeneity).

**Decision rule (fixed now):**
1. **KEEP as candidate** iff pooled KB-vs-PLAIN lower 95% bound > 0 Elo **and** heterogeneity chi2 <= 9.49 (df 4)
   **and** pooled KB-vs-HCE is not below the PLAIN-vs-HCE reference (R: 60%/40 games, itself preliminary).
2. **REVERT / negative result** iff pooled upper bound < +5 Elo, or the replicates disagree.
3. Otherwise **inconclusive**: increase data (LS's EXP-LS2 lane) before re-running; do not re-tune the table to the result.
4. Even on KEEP: this is a *net-format* result. Promotion into the engine still needs the project's ship gate
   (5 replicas vs last-known-good, SF19 UCI_Elo downside check, second reviewer). HCE remains the default until then.

## Known limitations / downside
- 6% slower full-refresh eval for CRN2 (see table); only matters if the net is better.
- CRN2 nets are ~8x larger in the first layer (1.5 MB at H=128): embedding in the binary grows it.
- The bucket table is a first guess, not tuned. It was fixed before any data was seen and will not be
  adjusted after seeing results (changing it is a new experiment).
- A single 200-game run resolves only about +-45 Elo; that is why the gate is 5 pooled replicates.
