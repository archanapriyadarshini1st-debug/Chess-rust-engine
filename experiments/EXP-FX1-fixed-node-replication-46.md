# EXP-FX1: independent fixed-node replication of #46 toggles + LmrScale sweep

- **Agent:** FX (docs-only PR; no `src/` change, no workflow change)
- **Repository / commit:** `archanapriyadarshini1st-debug/Chess-rust-engine`, `main` 581b8ee; #46 head (`agentQ/lmr-pruning-toggles`) built locally.
- **Baseline:** the #46 binary with every toggle off. `bench 10` = **553783 nodes** on both `main` 581b8ee and #46 (toggles off), so they are node-identical.
- **Binary sha256 (first 16):** `main` 4d3b1bbc62d96479, #46 31d06edeedb05c83. Built with `cargo 1.99.1 --release`, repo `.cargo/config.toml` flags (x86-64-v2), LTO.
- **Hardware:** shared 4-vCPU sandbox VM, 3 GB RAM, Linux. fastchess v1.8.3-alpha, `-concurrency 4`.
- **Opponent/engine pair:** test = same binary + one option, base = same binary defaults. Not an SF19 match.
- **Config (identical for all runs):** `nodes=50000` per move (no clock), Hash 16, 1 thread, openings `tools/openings_book.epd`
  (`order=random`, `-repeat`, each opening played with both colours), draw adjudication movenumber 40/movecount 8/score 8,
  resign movecount 4/score 800. Seeds and game counts were fixed **before** any result was seen.

## Command (reproducible; engine is deterministic at fixed nodes)

```
fastchess -engine cmd=<bin> name=test option.<X>=<v> nodes=50000 -engine cmd=<bin> name=base nodes=50000 \
  -each proto=uci option.Hash=16 -rounds 500 -games 2 -repeat -concurrency 4 \
  -openings file=tools/openings_book.epd format=epd order=random -srand <seed> \
  -draw movenumber=40 movecount=8 score=8 -resign movecount=4 score=800
```

## Results (all 1000 games unless noted)

| ID | test option vs defaults | seed | W-L-D | score | Elo +- 95% CI | LOS | verdict |
|---|---|---|---|---|---|---|---|
| A/A | none vs none (400 g) | 11 | 118-118-164 | 50.00% | 0 +- 0 | n/a | harness check, see note |
| FX1a | `XCapLmr=1` | 21 | 251-276-473 | 48.75% | -8.7 +- 15.2 | 13.2% | inconclusive, leans negative; **do not promote** |
| FX1b | `XDeeper=1` | 31 | 264-268-468 | 49.80% | -1.4 +- 14.9 | 42.8% | null |
| FX1c | `LmrScale=60` (default 45) | 41 | 258-262-480 | 49.80% | -1.4 +- 15.6 | 43.1% | null |
| FX1d | `LmrScale=75` (default 45) | 51 | 254-265-481 | 49.45% | -3.8 +- 15.4 | 31.3% | null |

**A/A note.** All 200 pairs scored exactly 1-1 (Ptnml `[0,0,200,0,0]`): at fixed nodes, same binary, the colour-swapped game is a
mirror image. That shows the engine is deterministic and the harness has no colour bias. It does **not** estimate noise; the
+-15 Elo CIs on the A/B rows are the noise estimate to use.

## What this does and does not show

- Nothing here is distinguishable from 0 at +-15 Elo. A true effect of +-5..8 Elo would need roughly 5-10x more games; this is
  **preliminary**, not a ship/no-ship decision for #46.
- **XCapLmr** is the only one whose point estimate is clearly negative (-8.7). Q's own note that a late capture is often the
  refutation is consistent with that, but 13% LOS is not evidence of harm either.
- **LmrScale 45 -> 60 -> 75 is flat** (-0, -1.4, -3.8). Within this budget the LMR aggressiveness is not where the engine is leaving Elo,
  so spending more agents on LMR constants looks like poor value next to NNUE / evaluation / TT.
- Fixed-node play ignores per-node cost (e.g. extra work from SEE in capture-LMR) and ignores time management. It is a necessary
  check, not a replacement for the 5x time-based gate (#34/#35) or an SF19 downside check. **No Elo claim vs SF19 is made.**
- Raw PGNs/logs lived in the ephemeral sandbox and are not attached; the runs are reproducible from the command above because
  the engine is deterministic at fixed nodes.

## Decision

- XCapLmr: **investigate only if** a time-based 5-replicate run disagrees; otherwise keep default-off.
- XDeeper: **inconclusive**, no evidence of benefit or harm.
- LmrScale: **keep 45** (no evidence for change).
