# EXP-V2: regression isolation record, SE contribution gate, PR merge-conflict matrix

- **Experiment ID:** EXP-V2
- **Responsible agent:** Agent V2 (integration / evidence; second session on the V account, distinct from the
  EXP-V1 fix-arbitration lane, which this file does not touch)
- **Repository / commit:** `archanapriyadarshini1st-debug/Chess-rust-engine` @ `7793ad7` (main). Nothing here is from the fork.
- **Touches:** this one new file only. No `src/`, no workflows, no `main`.

## 1. Q's isolation runs, read from raw job logs (nobody had posted them yet)

Source: GitHub Actions `sprt.yml`, 10+0.1, 595-position book, 1 thread, BASE = `451d933` (pre-PR#5, last known good),
bounds logistic [-15, 0]. Runs `42797148762`, `42797153320`, `42797159801`, branches by Agent Q. I only read the logs
and recomputed the statistics (trinomial 95% CI, normal-approx LOS).

| run | TEST branch | corrhist | singular ext. | bench 10 (TEST) | W-D-L (TEST pov) | score | Elo vs `451d933` | verdict printed |
|---|---|---|---|---|---|---|---|---|
| 42797153320 | `agentQ/diag-nose` `fabce7e` | **on** | off | 380431 | 1-1-138 | 1.1% | undefined (catastrophic) | FAIL (stopped at 140 games) |
| 42797148762 | `agentQ/diag-nocorr` `18dd8eb` | off | **on** | 553783 | 113-358-129 | 48.67% | **-9.3** [-27.0, +8.4], LOS 15% | INCONCLUSIVE, LLR -0.29 |
| 42797159801 | `agentQ/diag-both` `56b0040` | off | off | **356715** | 127-353-120 | 50.58% | **+4.1** [-13.8, +21.9], LOS 67% | INCONCLUSIVE, LLR +2.34 |

(W-D-L order above is W-D-L as listed in the workflow summary `+W -L =D`; the table column reads W-D-L.)

What this establishes:

1. **The corrhist table from PR #5 is the entire regression.** SE off + corrhist on loses 1 / 140. Corrhist off (with or
   without SE) is within error of `451d933`. Agrees with Agent N (fixed nodes +336) and Agent Q (205-0-3 old vs main).
2. **`diag-both` bench 10 = 356715 = `451d933` bench 10, exactly.** Agent V's EXP-V1 assumed this; it is now confirmed.
   So "PR #5 minus corrhist minus SE" is search-identical to the last known good commit.
3. **Singular extension is not shown to help at 10+0.1.** SE-on vs SE-off, compared *indirectly* through the common base,
   is -13 Elo with an error bar of roughly +-25. That is **not** a significant result in either direction. It also costs
   **+55% nodes at fixed depth 10** (553783 vs 356715). A node-count increase that does not buy Elo is a candidate for
   removal or retuning (margin, depth gate, TT-depth gate). This is a hypothesis, not a finding: see section 2.
4. Corrhist read and corrhist update were disabled together in `diag-nocorr`/`diag-both` (one-line change), so these
   rows cannot say whether a *bounded* corrhist adds Elo. That is EXP-V1 / PR #28's question.

## 2. Pre-registered: direct SE gate (written before any result)

- **Hypothesis:** with the corrhist bug removed, singular extension as implemented (`search.rs`, depth >= 8,
  `tt_depth >= depth-3`, margin `se_margin()+depth`, multicut return when `!is_pv && s >= beta`) does **not** gain
  >= +2.5 Elo at 10+0.1.
- **Test:** TEST = `agentQ/diag-nocorr` (SE on), BASE = `agentQ/diag-both` (SE off). They differ only in SE; both have
  corrhist disabled, so the comparison is clean and needs no new code.
- **Config:** `sprt.yml`, 10+0.1, 595-book, 1 thread, concurrency 3, logistic **[0, 5]**, round cap 1000 (2000 games).
  Dispatched as run `42815020269`.
- **Decision rule (fixed now):** H1 accepted -> keep SE. H0 accepted -> SE is not earning its nodes; open a follow-up to
  retune or drop it, gated against `diag-both`. Cap reached with LLR in between -> inconclusive; keep status quo, do not
  claim anything. I will post W-D-L, LLR and run id whatever happens and will not change bounds after the fact.
- **Caveat:** this tests SE on the *pre-fix* corrhist-off base. If #28 or `corrhist-off` lands and changes the
  eval-noise regime, SE's value could differ; re-test on the final base before removing anything.

Result: _pending (run 42815020269)_.

## 3. Open-PR merge-conflict matrix (real `git merge`, each pair applied on top of `7793ad7`)

Method: for each ordered pair (A, B) of open PR heads, `git merge A` onto `7793ad7`, then `git merge B`. "CONF" = textual
conflict on the second merge. Textual cleanliness is **not** semantic compatibility.

| | #18 | #22 | #24 | #25 | #26 | #27 | #28 |
|---|---|---|---|---|---|---|---|
| #18 probcut (search.rs) | - | ok | ok | ok | ok | **CONF** | ok |
| #22 datagen-bin | ok | - | ok | ok | ok | ok | ok |
| #24 eval/time | ok | ok | - | ok | ok | ok | ok |
| #25 perf (eval/search/tt) | ok | ok | ok | - | ok | ok | ok |
| #26 noisy-gen (movegen) | ok | ok | ok | ok | - | ok | ok |
| #27 Lazy SMP (search/uci/main) | **CONF** | ok | ok | ok | ok | - | **CONF** |
| #28 corrhist + persist (search/uci) | ok | ok | ok | ok | ok | **CONF** | - |

- **#12 (stage-0 self-play tools, `datagen.rs`) does not merge onto current `main` at all** (conflicts with the merged
  datagen seed fix, #16). Needs a rebase by its author before it can be considered.
- **#27 Lazy SMP is the only PR that conflicts with the others** (`search.rs` + `uci.rs` against #28; `search.rs` against #18).
  #28 keeps one persisted `ThreadData` per game; SMP needs one per thread, so the rebase is semantic, not just textual.
- #25, #26, #24, #22 are mutually and individually clean against everything. They are node-identical or non-search
  changes by their own claims; those claims still need the usual bench check on the final base.

### Suggested merge order (a suggestion for the owner and agents to confirm, not a decision)

1. Fixed base chosen by EXP-V1 (Q-off or #28), then re-gated against `451d933`, not against `main`.
2. #25, #26 (node-identical; confirm bench) - clean against everything.
3. #24, #18 - each needs its own SPRT on the fixed base.
4. #27 Lazy SMP, rebased by its author onto the chosen base.
5. NNUE net re-gate on the fixed search (Q's point: earlier "net does not beat HCE" verdicts ran on a broken search).

## 4. Honest scale

This is evidence bookkeeping for a regression fix. It is not strength progress toward the 80%-vs-UCI_Elo-2600 target
and supports no 2600 or 3000 claim. `451d933` remains the rollback reference.
