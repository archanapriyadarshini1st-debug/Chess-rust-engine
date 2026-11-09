# Chess-rust-engine

A from-scratch **UCI chess engine in Rust**, structured the way the current
top engines are structured — especially [Reckless](https://github.com/codedeliveryservice/Reckless)
(Rust, TCEC Superfinalist, ~#2 on CCRL in 2026), [Viridithas](https://github.com/cosmobobak/viridithas),
[Cinder](https://github.com/Arzam18/cinder), [Stormphrax](https://github.com/Ciekce/Stormphrax)
and [Stockfish](https://github.com/official-stockfish/Stockfish).

This is **original code**. It is not a fork of Reckless (AGPL) or Stockfish (GPL).
The architecture, search ideas and evaluation starting point are the public
chess-programming canon documented in `RESEARCH.md` and `ROADMAP.md`.

| What you get in v0.1 | Status |
| --- | --- |
| Bitboards, LERF, copy-make | done |
| Correct legal move gen (CPW perft suite) | done |
| UCI (`uci`, `position`, `go`, Hash, bench, perft) | done |
| Fail-soft PVS, ID, aspiration, TT, killers, history | done |
| NMP, LMR, RFP, LMP, IIR, check extensions, SEE | done |
| Quiescence + delta / SEE pruning | done |
| Tapered PeSTO + bishop pair, pawns, rooks, mobility | done |
| OpenBench-shaped `Makefile` + `bench` | done |
| NNUE (the Elo wall) | **next** — see `ROADMAP.md` |

Honest strength: a correct modern-search HCE engine like this typically lands
in the **~1800–2400 CCRL** band once time management and ordering are tuned.
Reckless 0.9 sits near **3600**. The entire gap is **self-play NNUE + OpenBench
SPRT**, not more alpha-beta tricks. That path is written down in `ROADMAP.md`.

## Build

```bash
# any CPU
cargo build --release

# native (best NPS on your machine) — same as Reckless / OpenBench
make
# ./chess-rust-engine
```

Requires Rust 1.70+. No C dependencies (Syzygy/Fathom is a later optional).

## Use

It is a UCI engine, not a GUI. Point Cute Chess, Fastchess, En Croissant,
Nibbler or Arena at the binary.

```
uci
isready
position startpos
go depth 12
# info depth 12 ... pv d2d4 ...
# bestmove d2d4
```

CLI helpers (Reckless-style):

```bash
./chess-rust-engine bench 10     # OpenBench node/nps line
./chess-rust-engine perft 6
# inside UCI:  d | eval | perft 5 | divide 5 | compiler
```

### UCI options

| Name | Default | Meaning |
| --- | --- | --- |
| Hash | 16 | Transposition table, MiB |
| Threads | 1 | Lazy SMP is on the roadmap |
| MoveOverhead | 20 | GUI / network latency, ms |
| Clear Hash | button | Drop the TT |

## Layout

```
src/
  types.rs      16-bit moves, LERF squares, mate scores
  bitboard.rs   LERF constants, shifts
  attacks.rs    leapers + ray/first-blocker sliders
  board.rs      copy-make position, FEN, checkers
  movegen.rs    pseudo-legal + legality filter
  zobrist.rs    const SplitMix64 keys
  eval.rs       PeSTO tapered + structure / mobility
  see.rs        static exchange
  tt.rs         lockless XOR TT (SMP-ready)
  search.rs     ID / PVS / qsearch / pruning
  time.rs       soft/hard bounds
  uci.rs        protocol
  perft.rs      CPW suite
```

## Stockfish 19 (teacher + Elo ladder)

Do **not** train on 100–120 ms games. The other codebase (`nextgen-chess-engine`) already proved that: SF19 MAX, 120 ms, 0–100–0, junk labels.

```bash
# measure ~2000: SF19 limited to UCI_Elo 2000, 10+0.1
python scripts/stockfish_match.py --stockfish ./stockfish \
  --mode ladder --elo 2000 --games 20 --tc 10+0.1

# teacher: SF19 MAX, 2 seconds per move, writes datasets/teacher_book.txt
python scripts/stockfish_match.py --stockfish ./stockfish \
  --mode teacher --games 8 --movetime-ms 2000
```

GitHub Actions → **SF19** → `workflow_dispatch` (`ladder` / `teacher` / `smoke`).
Coordination with the other agent: `AGENT_CHANNEL.md` and issue #1.

## Tests

```bash
cargo test --release --test perft
```

The CPW suite (startpos, Kiwipete, pos 3–6) is green, including en passant,
castling, promotions and pinned EP.

## Getting it to Reckless strength

Read, in order:

1. `RESEARCH.md` — how Reckless, Viridithas, Cinder, Stormphrax, Alexandria,
   Hobbes, Gaia and Stockfish actually work in 2026.
2. `ROADMAP.md` — the Elo ladder from this commit to a 3500+ net, with the
   testing protocol (OpenBench SPRT, Bullet trainer, datagen, PGO, Syzygy,
   Lazy SMP, singular extensions, correction history).

Short version: **do not hand-tune PST numbers hoping to catch Stockfish.**
Generate self-play, train an NNUE with [Bullet](https://github.com/jw1912/bullet),
test every change with a SPRT, and only merge +Elo.

## References

- Reckless — https://github.com/codedeliveryservice/Reckless
- Viridithas — https://github.com/cosmobobak/viridithas
- Chess Programming Wiki — https://www.chessprogramming.org/
- OpenBench — https://github.com/AndyGrant/OpenBench
- Bullet NNUE trainer — https://github.com/jw1912/bullet
- PeSTO evaluation — https://www.chessprogramming.org/PeSTO%27s_Evaluation_Function

## License

GPL-3.0-or-later. Original work; not derived from Reckless or Stockfish sources.
