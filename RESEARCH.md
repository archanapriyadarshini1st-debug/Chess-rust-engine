# Research: building a world-class chess engine in Rust

This note is the design bible for **Chess-rust-engine**. It is written from
public sources (Chess Programming Wiki, Reckless/Viridithas READMEs, CCRL/TCEC
coverage, OpenBench, Bullet) and from what actually moved Elo in 2023–2026.
Nothing here is a copy of Reckless or Stockfish source.

## 1. Where the Elo is in 2026

Approximate CCRL 40/15 (single-CPU class, late 2026):

| Engine | Lang | Eval | Ballpark Elo | Notes |
| --- | --- | --- | --- | --- |
| Stockfish 18/19 | C++ | NNUE | ~3650 | TCEC champion every season since 18 |
| **Reckless 0.9.0** | **Rust** | NNUE | **~3644** | TCEC Superfinal vs Stockfish |
| PlentyChess, pawnocchio, Cinder, Obsidian, Alexandria | C++/Rust | NNUE | 3630–3640 | |
| Hobbes, Stormphrax, Viridithas | Rust | NNUE | ~3630 | |
| Lc0 | C++ | GPU net + MCTS | weaker on CPU | different paradigm |

Rust is **not** an Elo handicap. Reckless, Cinder, Viridithas, Alexandria,
Stormphrax and Hobbes prove LLVM + zero-cost abstractions sit within a few
Elo of C++ if you care about NPS and SIMD. The gap to Stockfish is search
tuning + net quality + years of OpenBench, not the language.

Two paradigms still exist:

1. **Alpha-beta + NNUE** (Stockfish, Reckless, everyone in the top 20 except Lc0).
2. **MCTS + large net on GPU** (Lc0 / AlphaZero style).

We follow (1). It is what you can train on a CPU box and what GUIs expect.

## 2. Reckless — the Rust reference

Repo: https://github.com/codedeliveryservice/Reckless (AGPL-3.0).
Author: Arseniy Surkov (`codedeliveryservice`) with later co-authors.
First release May 2023 (~2000 CCRL). By March 2026 it is #2 in the world.

Elo history (from the Reckless README, CCRL 40/15 / Blitz):

| Ver | Date | Jump | What landed |
| --- | --- | --- | --- |
| 0.1 | May 2023 | ~2005 | bitboards, UCI |
| 0.2 | Oct 2023 | +340 | tapered eval, RFP, fail-soft, copy-make |
| 0.3 | Nov 2023 | +270 | search cleanup |
| 0.4 | Dec 2023 | +310 | IIR, futility, improving, log LMR, NMP |
| 0.5 | Feb 2024 | +285 | **NNUE replaces HCE**, self-play data |
| 0.6 | Mar 2024 | +100 | Lazy SMP |
| 0.7 | Aug 2024 | +100 | bigger net 384, 4 output buckets, SEE, MDP, time stability |
| 0.8 | Aug 2025 | +180 | CCC 2nd-place search/net work |
| 0.9 | Mar 2026 | ~#2 | TCEC Superfinalist |

The lesson: **HCE + modern search got them to ~2900. NNUE did the rest.**
v0.5 is the cliff. Everything after that is bigger nets, better data, SMP,
SEE, and time management.

### Reckless architecture (public README / wiki)

```
UCI (stdin/stdout)
  └─ ThreadPool  (Lazy SMP, shared lockless TT)
       └─ search::start  iterative deepening
            ├─ aspiration windows around previous score
            ├─ PVS alpha-beta  (Root / PV / NonPV node types)
            ├─ quiescence
            ├─ movepick + history / killers / continuation
            ├─ NNUE evaluate + correction history
            └─ time: soft/hard, score stability, best-move stability
Board: LERF bitboards, fancy magics, copy-make
Eval:  (768 -> 768)x2 -> 1   SCReLU, i16 quant (384, 64), self-play
Extras: Syzygy (Fathom), Chess960, PGO, OpenBench, Bullet trainer
```

UCI surface we copied the *shape* of: Hash, Threads, MultiPV, MoveOverhead,
Clear Hash, SyzygyPath, `perft`, `bench`, `d`, `eval`, `compiler`.

Build lesson: `RUSTFLAGS=-C target-cpu=native`, PGO (`cargo-pgo`), AVX2/AVX-512
binaries. Reckless reverted a cargo-config cleanup because **cargo-pgo ignores
`[build]` flags** — native codegen has to live in the Makefile.

## 3. Other Rust engines worth stealing ideas from (not code)

| Engine | Why look | Takeaway |
| --- | --- | --- |
| [Viridithas](https://github.com/cosmobobak/viridithas) | Longest-running strong Rust engine; excellent module split | NNUE on *original* self-play only; datagen CLI; Syzygy via Fathom; `stats` feature |
| [Cinder](https://github.com/Arzam18/cinder) | ~3638 CCRL, compact | Same UCI option set; SyzygyPath |
| [Stormphrax](https://github.com/Ciekce/Stormphrax) | Chess960 specialist, NNUE successor of Polaris | SIMD is mandatory for NNUE NPS; FRC as a first-class path |
| [Hobbes](https://github.com/kelseyde/hobbes-chess-engine) | MIT, self-play nets, OpenBench Makefile | `network.txt` + curl the net in `make openbench` |
| [Alexandria](https://github.com/PGG106/Alexandria) | Top-10, often cited as “Rust ≈ C++ NPS” | Search is C++-style; language is not the bottleneck |
| [Gaia](https://github.com/jromang/gaiachess) | Huge feature net, Skill Level, NUMA | King-bucketed inputs, output stacks by material, optional HCE fallback |
| [Oxide](https://github.com/Miguevrgo/Oxide) | Readable + NNUE trained on Lc0 data with Bullet | Obstruction-difference movegen is a legal alternative to magics |
| [Vendetta](https://github.com/Fab2bprog/Rust-Vendetta-Chess-Engine) | Explicit Elo-gain table for each search trick | Use it as a checklist, not as gospel (gains overlap) |

Didactic / library engines (do **not** use as a strength target): Pleco,
shakmaty, cozy-chess, Carp. Great for move-gen tests, wrong for NPS.

## 4. The machine: subsystems, in the order they pay Elo

### 4.1 Board representation — bitboards, LERF

64-bit sets, a1 = bit 0, h1 = 7, a8 = 56, h8 = 63. Universal in Reckless,
Stockfish, Viridithas. Mailbox `[Piece; 64]` sits next to the bitboards for
O(1) “what is on this square?”.

Copy-make (Reckless v0.2) vs make/unmake: a `Position` is ~200 bytes. Copying
it is cheaper than you think and deletes a class of undo bugs. We copy-make.

### 4.2 Move generation

Leapers (pawn/knight/king): precomputed tables.
Sliders: three legal designs, all used at the top:

1. **Fancy magic bitboards** (Reckless, Stockfish) — fastest portable.
2. **PEXT / BMI2** — faster on Intel, slower or unavailable on some AMD.
3. **Ray + first blocker** (this engine, v0.1) — simple, correct, ~good enough
   until magics show up on a SPRT.

Must be **perft-perfect** before any search work. CPW suite:

| Position | d1 | d2 | d3 | d4 | d5 |
| --- | --- | --- | --- | --- | --- |
| Startpos | 20 | 400 | 8902 | 197281 | 4865609 |
| Kiwipete | 48 | 2039 | 97862 | 4085603 | 193690690 |
| Pos3 | 14 | 191 | 2812 | 43238 | 674624 |
| Pos4 | 6 | 264 | 9467 | 422333 | 15833292 |
| Pos5 | 44 | 1486 | 62379 | 2103487 | 89941194 |
| Pos6 | 46 | 2079 | 89890 | 3894594 | 164075551 |

v0.1 matches all of these at the depths in `tests/perft.rs`.

16-bit move encoding (CPW “from-to + nibble flags”) is what the TT, killers
and history index. Reckless does the same.

### 4.3 Search — this is still 50% of strength *after* NNUE

Fail-soft PVS, iterative deepening, aspiration windows. Then the 2020s stack:

| Technique | Typical gain if missing | Notes |
| --- | --- | --- |
| TT (Zobrist, depth-preferred, mate-score ply adjust) | +100–150 | lockless XOR = SMP-ready |
| MVV-LVA + TT-move + killers + history | +50–80 | continuation / countermove on top |
| Quiescence + SEE / delta | +50–80 | losing captures must not explode qsearch |
| NMP with zugzwang guard | +40–80 | skip in pawn endgames |
| LMR (log×log, history-adjusted) | +50–100 | re-search on fail-high |
| RFP / futility / LMP | +20–50 | `improving` flag matters |
| IIR | +10–20 | no TT move → reduce |
| Check extension | +20–40 | cheap |
| **Singular extension** | **+40–70** | the last big classical search gain |
| Aspiration + time (score / best-move stability) | +20–40 | Reckless v0.7 |
| Lazy SMP | +50–80 / extra cores | shared TT, no split |
| Correction history | +10–30 | Reckless eval pipeline |

Node types (Root / PV / NonPV) as compile-time generics are a Reckless /
Stockfish trick: PV nodes search full windows and skip the nastier prunes.

### 4.4 Evaluation — HCE then NNUE, never both forever

**Phase A, this repo:** PeSTO tapered PSTs (Ronald Friederich / RofChade,
Texel-tuned, public tables) plus bishop pair, doubled/isolated/passed pawns,
rook files, mobility, king shield, tempo. PeSTO replaced Michniewski’s
“simplified eval” across the hobby scene; Pawel Koziol measured ~+200 Elo
in TSCP.

**Phase B, the wall:** NNUE.

- Invented for shogi, landed in Stockfish 12 (2020), **+80 to +100 Elo overnight**.
- Stockfish deleted the last of its hand-crafted eval in 2023.
- Reckless v0.5 did the same.

Modern CPU NNUE shape (Reckless 0.9 public):

```
input: 768 = 12 piece-types × 64 squares   (side-to-move perspective, duplicated)
hidden: (N)x2  accumulators, SCReLU
output: 1  (or 4–8 material buckets)
quant:  i16 weights, SIMD (AVX2 / AVX-512)
update: incremental accumulator (add/sub the moved piece), not a full pass
```

HalfKP / king-buckets / threat features (Gaia, later SF nets) are later
Elo. Start with 768→H×2→1, H=16 then 64 then 256 then 768 as data grows.

Trainer of choice in the Rust community: **[Bullet](https://github.com/jw1912/bullet)**
(used by Reckless, Oxide, many others). Data: self-play at modest depth,
WDL + eval targets, billions of positions, quantization-aware.

### 4.5 Time, SMP, endgames, build

- Soft bound ≈ `remaining/20 + 0.8*inc`, hard ≈ 3× soft, minus MoveOverhead.
- Scale by score stability and best-move stability (Reckless #42, #50).
- Lazy SMP: N threads, same position, shared lockless TT, slight diversity
  (different aspiration / extra reduction on helpers).
- Syzygy via Fathom (C). Optional; huge in long TC, small at blitz.
- PGO + `target-cpu=native` is free Elo at zero Elo risk.
- OpenBench + Fastchess SPRT is the only merge rule that scales.

## 5. Testing protocol (non-negotiable)

A patch that is not SPRT’d is a coin flip. Reckless, Viridithas, Stockfish
all live on this loop:

```
change → make native → bench (nodes must be deterministic)
      → smoke (perft, a few matches)
      → OpenBench SPRT  (e.g. 10s+0.1, 10k games, bounds 0–5 Elo or 0–10)
      → merge iff LLR hits H1
```

`./engine bench` **must** print `N nodes M nps` on stdout. Our Makefile
exposes `openbench` / `native` the way Hobbes / Reckless do.

Never test two changes at once. Never tune search constants by eye once you
have a net — use SPSA / Tune on OpenBench.

## 6. What this repo implements vs. Reckless

| Subsystem | Chess-rust-engine v0.1 | Reckless 0.9 |
| --- | --- | --- |
| Language | Rust, zero deps | Rust + Fathom C |
| Board | LERF bitboards, copy-make | LERF, fancy magics, copy-make |
| Sliders | ray + first blocker | fancy magics |
| Search | PVS, ID, aspiration, TT, NMP, LMR, RFP, LMP, IIR, SEE, qsearch | all of that + SE, correction hist, MultiPV, 512 threads |
| Eval | PeSTO + structure | SCReLU NNUE, self-play |
| SMP | TT is lockless, Threads=1 | Lazy SMP |
| TB | — | Syzygy |
| Datagen | — | built-in |
| Strength | hobby / club, HCE-limited | world class |

The code is original. The *checklist* is Reckless/Stockfish/CPW.

## 7. Sources

- Reckless README and DeepWiki overview — architecture, UCI, NNUE, history.
- Reckless Elo table (README) and TCEC Superfinal coverage.
- Viridithas DeepWiki — module map, datagen, original-data NNUE.
- Chess Programming Wiki — bitboards, magics, encoding moves, PeSTO, LMR, SEE.
- OpenBench wiki — bench line, Makefile `EXE=`.
- Bullet — NNUE trainer used by Reckless.
- Friederich, PeSTO’s Evaluation Function (CPW).
- CCRL / ramachess.com 2026 lists — Reckless ~#2, Stockfish #1.
