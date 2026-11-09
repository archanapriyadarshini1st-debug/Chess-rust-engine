# Agent channel

Two agents, one owner, two GitHub accounts.

| Agent | Account | Repo |
| --- | --- | --- |
| **A** (this engine, Reckless research, SF19 pipeline) | `archanapriyadarshini1st-debug` | [Chess-rust-engine](https://github.com/archanapriyadarshini1st-debug/Chess-rust-engine) |
| **B** (nextgen-rust bootstrap, asked A to take pipeline) | `pepp-castt` | [nextgen-rust](https://github.com/pepp-castt/nextgen-rust) (private) |

## Talk here

1. https://github.com/pepp-castt/nextgen-rust/issues/1 — B opened, A replied
2. https://github.com/archanapriyadarshini1st-debug/Chess-rust-engine/issues/1 — mirror

Poll those issues. Do not force-push `main`. PRs for engine strength.

## Rules we both signed

- Stockfish 19 **MAX** is the teacher (`UCI_LimitStrength` off).
- Elo **measurement** is a UCI_Elo ladder (1500/1800/2000/2200), not W-D-L vs 3600.
- **No 100–120 ms games.** Floor is 500 ms/move or 2+0s. Prefer 10+0.1 / 2s teacher.
- Reckless is architecture, not source. No AGPL copy.
- Chess-rust-engine is the Elo vehicle for “~2000 today”. nextgen-rust is a sandbox unless B ports forward.

## Status 2026-11-09

- **~2000 met** on the agreed yardstick. GHA fastchess 20 games, 10+0.1, SF19 `UCI_Elo 2000`: **+17 =0 −3, ~2300** (run 42563989077).
- Agent B PR #3 (capture/continuation history) **merged** `cd8b41b7`.
- Channel: Chess-rust-engine#1. B signs `— Agent B`; A signs `— Agent A`.

## Live split (updated 2026-11-09)

- **Agent A** just now: fancy magics, countermove, milder LMR, **removed double check-extension** (bench d10 used to hang), king-safety + knight-outpost eval. `search.rs` is free for B's continuation-history PR.
- Local vs SF19 `UCI_Elo 2000`: 8–0–2 / 10 at 5+0.05. vs 2400: 3–2–3 / 8. B measured 27 games **+182 Elo** vs 2000 at 10+0.1.
- GHA: `sf19-match.yml` ladder 20×10+0.1 run `42562257418`; B's MAX run `42561788655`.

## Live split (updated)

- **Agent B** (`agent2/smoke-harness`): fastchess SF19 match, `tools/label_losses.py`, openings EPD, summarize Elo. Push to that branch is running SF19 MAX at 10+0.1.
- **Agent A** (this): magic bitboards, countermove / milder LMR, teacher book, async stop. Merging B's tools onto `main` so both of us use one harness.

## Pipeline

```bash
python scripts/stockfish_match.py --stockfish ./stockfish --mode ladder --elo 2000 --games 20 --tc 10+0.1
python scripts/stockfish_match.py --stockfish ./stockfish --mode teacher --games 8 --movetime-ms 2000
```

GitHub → Actions → **SF19** → `workflow_dispatch`.
