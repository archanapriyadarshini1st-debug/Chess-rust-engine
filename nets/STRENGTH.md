# S45 net — do not merge to main until SPRT vs persist

- branch: `nnue/lichess-bulk-43358406911`
- file: `nets/default.nnue`
- sha256: `7739137cf112c64020d3b81d270d0ca992cfb6f3f23c7e844598359add1ba13a`
- source: GHA lichess-bulk run 43358406911, shards 4+5, 16M, lam=1.0, val_loss 0.00677
- vs HCE 10+0.1: **97.5%/40** (38–2–0)
- vs SF19 UCI_Elo 2900 10+0.1 Hash=64 1t: **62.5%/24** (13–4–7, +89±132)
- 80% vs 2900 still unmet. HCE PeSTO stays `main`.

Promote workflow commit message still says "15.2M / 60% vs HCE" — that template is stale. These numbers are the gate.

— Agent A
