# EXP-U1 — independent verification of the open "node-identical" PRs + merge-conflict map

Agent U (integration verifier). Touches **no `src/`**, no workflows, nothing in anyone's lane. This file only.
Repo: `archanapriyadarshini1st-debug/Chess-rust-engine`, baseline `main` = `7793ad75dd4c`.
Hardware: 4 vCPU Intel Xeon @ 2.60 GHz, 3.9 GB, Linux, rustc 1.99.1, **plain `cargo build --release` (no target-cpu=native)**.
All numbers below are from this one box. NPS is box- and load-specific; node counts are not.

## Why
Four open PRs claim "node-identical" or "bench-identical" behaviour (#25, #26, #27 and, partially, #18/#24/#28 which
change nodes on purpose). Rule 9.4/9.7 says a perf patch must preserve correctness, and "bench-identical" is a claim
that anyone can check in under a minute. Nobody had posted an independent check, and several PRs edit the same hunks
of `search.rs` / `uci.rs`, so the merge order matters.

## 1. Bench determinism and node-identity (each run twice, same node count both times)

| branch | head | `bench 10` nodes | vs main |
|---|---|---|---|
| main | `7793ad75dd4c` | 469049 | — |
| #25 Y1 shared attacks + TT prefetch | `506bdb5e9af9` | 469049 | **identical** |
| #26 Y2 noisy-move generator | `3929fc99e61d` | 469049 | **identical** |
| #27 Lazy SMP (Threads=1) | `2d70eb96946e` | 469049 | **identical** |
| #18 A qsearch-TT + razoring + ProbCut | `7646d643785a` | 432876 | changes search (intended) |
| #24 A rook-behind-passer + time | `3bbe0e49709d` | 500578 | changes eval (intended) |
| #28 N persistence + bounded corrhist | `959288355a65` | 540934 | changes search (intended); matches V's quoted number |
| Q-off (corrhist disabled) | `0f062cc7dd5f` | 553783 | changes search (intended); matches Q/V |

`bench 11`: main = #25 = #26 = **836287** (5 interleaved runs each).

## 2. NPS (interleaved A/B/A/B, 5 runs, `bench 11`, single thread, node-identical so this is pure speed)

| branch | mean nps | note |
|---|---|---|
| main | 1,700,227 | min 1.62M / max 1.74M |
| #25 | 1,949,484 | **+14.7%** (author claims +17.5%; direction and size reproduce) |
| #26 | 1,835,645 | **+8.0%** |
| bundle #25+#26+#27 (merge commit `bba1fdaac021`) | 2,119,827 vs main 1,718,255 (same session) | **+23%**, nodes identical |

Throughput only. This is not an Elo claim; it must still be seen to help in games (it should: same tree, less time).

## 3. Composition test
`main` + #25 + #26 + #27 merged in that order: **no conflicts**, builds, `bench 10`=469049, `bench 11`=836287
(identical to main), `cargo test --release` green (perft, params, NNUE parity, and the 4 new SMP tests).
So the three node-identical PRs are safe to land in any order relative to each other.

## 4. Pairwise merge-conflict matrix (`git merge-tree --write-tree`, all against the same base)

Only these pairs conflict (every other pair among #18 #24 #25 #26 #27 #28 Q-off V-persist merges cleanly):

| pair | files |
|---|---|
| #27 (SMP) x #28 (persist+corrhist) | `search.rs`, `uci.rs` |
| #27 (SMP) x V-persist | `search.rs`, `uci.rs` |
| #27 (SMP) x #18 (ProbCut) | `search.rs` |
| #28 x Q-off | `search.rs` (same corrhist lines — expected, they are alternatives) |
| #28 x V-persist | `search.rs` (same `prepare()` lines — expected, V copies N) |

Consequence: **land #25 and #26 first (clean against everything), then whichever of Q-off / V-persist / #28 wins the V
arbitration, then rebase #27 once** on the result (SMP is the thinnest wrapper, so it is the cheapest to rebase and
it needs to know whether helper threads share or clone the persisted `ThreadData`). #18 must be re-benched after the
corrhist decision regardless, because it was measured on an engine with the broken table.

## 6. Eval-equivalence check for #25 (the +533/-100-line eval rewrite)
`position fen X` + `eval` on **895 FENs** (`experiments/EXP-P1-data/fens300.txt` = 300 mixed middlegame/endgame +
`tools/openings_book.epd` = 595 opening positions), main vs #25 and main vs the 3-PR bundle: **0 differences** in both
`eval` and `eval_hce` outputs. Positive control: main vs #24 (eval changed on purpose) differs on **14 / 300** FENs, so
the harness can see a 1-term eval change. Script: `evaldiff.py` (30 lines, pasted in the issue comment). Limits: HCE only
(no net exists), and 895 positions with no extreme endgames / promotions-heavy positions; it makes an accidental eval
change very unlikely, not impossible.

## 5. What this does NOT show
* Nothing about playing strength. #25/#26/#27 are node-identical, so a strength SPRT adds nothing at fixed nodes; at fixed
  time they should only help. No Elo is claimed.
* Nothing about SMP scaling beyond "Threads=1 is unchanged and the tests pass".
* I did not review the eval rewrite inside #25 line by line. I verified it behaviourally: see section 6.

## Reproduce
```
git fetch origin pull/25/head:pr25 pull/26/head:pr26 pull/27/head:pr27
for b in main pr25 pr26; do git worktree add ../wt_$b $b; (cd ../wt_$b && cargo build --release); done
for r in 1 2 3 4 5; do for b in main pr25 pr26; do ../wt_$b/target/release/chess-rust-engine bench 11 | tail -1; done; done
git merge-tree --write-tree pr27 pr28     # exits non-zero on conflict
```

## Next (Agent U)
1. (done, section 6) eval-equivalence for #25.
2. Re-run the 2600 gate (A's 20-game ladder harness) on the merged result of the V arbitration.
