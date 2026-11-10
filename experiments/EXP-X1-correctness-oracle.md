# EXP-X1: independent correctness oracle + independent review of #25/#26 [Agent X1]

Responsible agent: **X1** (independent reviewer; wrote neither #25 nor #26). Repo: `archanapriyadarshini1st-debug/Chess-rust-engine`.
Baseline: `main` @ `52cb805`. Candidates: `pr25` (agentY/perf-nps) + `pr26` (agentY/noisy-gen), merged locally on `52cb805` (clean merge, `8cf385b`).
Files owned: `tools/correctness_oracle.py`, `.github/workflows/correctness-oracle.yml`, this file. No `src/` change.

## Why
Existing gates measure *strength* (SPRT, ship gate) and *speed* (perf_equiv). Nothing independently checked that the **rules
implementation** still matches a reference. The owner's rule is "test it 5 times, find the downside". A strength gate cannot see a
move-generation bug that costs one node in 10^4 positions, or a promotion/castling edge case that only matters in rare games.

## Oracle design (`tools/correctness_oracle.py`)
Random-walk games (half from the 595-position book, half from startpos; half capture-biased to reach promotions/endgames).
Reference: python-chess 1.11.2 (a different code base from the engine and its Rust tests).
1. engine legal-move **set** (`divide 1`) == reference at **every** ply
2. engine `divide 3` per-move counts == reference perft(2) every 9th ply
3. `go depth 5` bestmove is legal, engine does not hang/crash (every 25th ply)
4. UCI-terminal positions (mate/stalemate only) do not crash and return a null move
5. state replayed through `position fen .. moves ..` (castling rights, ep square, promotions) produces the same legal set
Exit 1 on mismatch, prints the move list. Seeds are explicit, so a failure is reproducible.

## Validity of the oracle itself (mutation testing, `main` + one planted bug)
| mutant | caught? | evidence |
|---|---|---|
| Black en passant never generated | **yes**, first failing perft3 positions within seconds | perft3 off by 2 nodes (`1254 vs 1256`) |
| Black O-O-O ignores attack on **d8** (pass-through square) | **yes** | perft3 off by 1 node (`1860 vs 1859`) |
| Black O-O-O ignores attack on **c8** (landing square) | no, **equivalent mutant** | landing-square legality is also enforced by the generic king-in-check filter, so behaviour is unchanged |

## Results (5 seeds x 60 games x 170 plies, python-chess 1.11.2)
| binary | seeds | verdict | totals per seed (approx.) |
|---|---|---|---|
| `main` 52cb805 | 1,2,3,4,5 | **5/5 PASS** | ~9.8k plies, ~1.1k perft-3 comparisons, ~400 searches, ~50 promotions |
| `#25+#26` on 52cb805 | 1,2,3,4,5 | **5/5 PASS** | same |

(A first run reported "terminal-bestmove" failures; those were an oracle bug, `is_game_over()` also treats insufficient material
as terminal, which is not terminal in UCI. Fixed before any result was recorded; the first-run logs are not counted.)

**Coverage caveat (honest):** random walks reach en passant and castling rarely (4 seeds: 8 ep, 15 castles). They complement,
not replace, `tests/perft.rs` (Kiwipete, position 3/4/5). A targeted ep/castling generator is future work.

## Independent review of #25 and #26 (5-replicate rule)
| check | result |
|---|---|
| (nodes, score, bestmove), 5 disjoint 24-position slices of the book (`book[i::5]`), depth 8 | **120/120 identical** |
| same at depth 12 (5 x 6 positions) | **30/30 identical** |
| sanity: positions really parsed (6 distinct node counts / 3 distinct moves at depth 6) | yes (guards against a vacuous "all startpos" pass) |
| `bench 10` nodes | 553,783 on both |
| `cargo test --release` on the merged tree | all pass |
| `bench 10` NPS, 7 interleaved rounds, **ratio new/main** | 1.126 1.105 1.157 1.385 1.189 1.077 1.188 -> **median 1.157** |
| A/A control (same binary vs itself) | 0.929 0.859 1.066 1.22 1.015 0.918 1.025 -> median 1.015 |
| clock safety, `go wtime 100/300 ms`, `1000+100`, 30 positions each | 0/30 over-clock moves in all 6 cells, both binaries; max 289 ms at 1000+100 |
| merge conflicts with other open PRs | no new ones. Already conflicting with plain `main`: #27, #28 (`src/search.rs`). #12 conflicts in `src/datagen.rs`. #18, #19, #22, #24 merge clean on top |

Noise note: shared 4-vCPU VM; the A/A ratios span 0.86-1.22, so "+15.7%" is directional (7/7 above 1.0, A/A median 1.015), not a
precise figure. Build here has no `target-cpu=native`.

### Code review notes
- `tt.prefetch`: index is `hash & mask` (in bounds), `_mm_prefetch` is a hint, `cfg`-gated for non-x86_64. No behaviour change.
- `.cargo/config.toml` (#25) sets `target-cpu=x86-64-v2`. **Downside to know:** it makes plain `cargo build` binaries require
  SSE4.2/POPCNT (every x86-64 CPU since ~2009, fine). All Elo/gate workflows set `RUSTFLAGS=-C target-cpu=native`, and the
  `RUSTFLAGS` env var **overrides** the config file, so their measurements are unaffected (the +4-5% popcnt claim does not apply to
  them, and the config cannot make a gate unfair). Release artifacts built by plain `cargo build` will not run on pre-2009 CPUs.
- Not tested here (code-read only): `position fen <invalid>` is silently ignored (engine keeps the previous position).

## Decision
- **#25 + #26: node-identical, no correctness or time-safety downside found, faster -> APPROVE (merge #26 then #25, disjoint files).**
  This is a performance/neutral patch: **no Elo claim**.
- Oracle: **keep**; CI workflow added so every `src/` PR gets the check.

## Provenance
- Binaries (plain `cargo build --release`, rustc 1.99.1, no RUSTFLAGS; hashes are machine-specific, not portable): main `fcc7b31a44d800fe...`, #25+#26 `923e97e54e215f9f...` (sha256 prefix).
- Hardware: Intel Xeon @ 2.60 GHz, 4 vCPU, 3.9 GB, Linux 6.1 x86_64, shared VM. Hash 16 MB, 1 thread, `CRE_NO_NNUE=1`.
- Book: `tools/openings_book.epd` (595 positions). Seeds 1-5. Reference: python-chess 1.11.2.
- Reproduce: `pip install chess && cargo build --release && python3 tools/correctness_oracle.py target/release/chess-rust-engine --games 60 --plies 170 --seed 1 --book tools/openings_book.epd`
