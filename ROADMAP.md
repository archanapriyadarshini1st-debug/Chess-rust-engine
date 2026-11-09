# Roadmap: this engine → Reckless-class

v0.1 is a **correct, UCI, modern-search HCE engine**. That is the right
foundation. It is **not** close to Reckless 0.9. The gap is not “more PST
terms”. It is the loop Reckless actually ran for three years.

Estimated Elo is CCRL-blitz-shaped and **hand-wavy**. Use it as a sequence,
not a promise. Merge only on SPRT.

## Phase 0 — freeze correctness (now)

- [x] CPW perft suite green (see `tests/perft.rs`)
- [x] UCI + `bench` line `N nodes M nps`
- [x] OpenBench-shaped Makefile
- [ ] Add `go` stop on a second stdin thread (Cute Chess `stop`)
- [ ] Deterministic bench (same nodes every run, no time in the search)
- [ ] More positions: CPW perft 6 startpos, Chess960 later

Do not touch eval constants until bench nodes are stable.

## Phase 1 — search completeness (~+150–300 over naive αβ)

Already in: TT, ID, aspiration, PVS, NMP, LMR, RFP, LMP, IIR, SEE, killers,
history, qsearch, check extensions, mate-distance, time soft/hard.

Still missing, in SPRT order (Vendetta / Reckless / SF folklore):

1. **Countermove + continuation history** (~+20–40)
2. **Singular extensions** (~+40–70) — biggest remaining classical gain
3. **ProbCut** (~+10–20)
4. **Static eval correction history** (pawn / minor / non-pawn hashes)
5. **History-adjusted LMR** (Reckless v0.4 formula)
6. **Capture history** (for noisy move ordering beyond MVV-LVA)
7. **MultiPV**
8. Tune margins with SPSA, not intuition

Also: **magic bitboards or PEXT** for sliders. Ray-blocker is correct; magics
are NPS. NPS × branching ≈ Elo in the HCE era.

## Phase 2 — Texel-tune the HCE (~+50–150)

PeSTO is a public prior, not *our* minimum. Dump quiet positions from
self-play, Texel-tune material, PST, pawn and mobility weights.
Stop when the tuner overfits. This is a local maximum around **club/master
engine** strength. Reckless left this phase at v0.4 (~2900) and never went
back.

## Phase 3 — NNUE, the wall (~+400–800)

This is Reckless v0.5. Skip it and you never see 3000.

1. **Feature set:** 768 = 12×64, both perspectives. (HalfKP later.)
2. **Architecture:** `(768 → H)×2 → 1`, H = 16 then 64 then 256.
   Activation: SCReLU (Reckless). Quantize i16.
3. **Inference:** incremental accumulator on make. AVX2 first, AVX-512 later.
4. **Data:** self-play with *this* engine, depth 8–12, 10⁸ then 10⁹ positions.
   Store FEN + result + search score.
5. **Trainer:** [Bullet](https://github.com/jw1912/bullet) (Reckless, Oxide).
6. **Loop:** train → embed net → SPRT vs previous net → keep iff +Elo.
7. Grow H, add output buckets by material (Reckless v0.7: 4 buckets),
   king buckets, threat features only after the small net SPRTs green.

Do **not** embed a Stockfish net. That is a license/ethics mess and teaches
you nothing. Reckless trains on original self-play; Viridithas does too.

## Phase 4 — scale

| Item | Why |
| --- | --- |
| Lazy SMP (shared lockless TT — already XOR) | +50–80 / extra cores |
| PGO (`cargo pgo instrument && bench && optimize`) | free NPS |
| Syzygy via Fathom | long TC, TCEC |
| Datagen binary + resume | nets eat data |
| OpenBench instance (or a friend’s) | the real test harness |
| Chess960 | Stormphrax-style, TCEC |
| NUMA pin | only once Threads > 64 |

## Phase 5 — live with the engine

- Hardware: Reckless has a contributor farm. You need *games*, not a 7950X
  for one match.
- Never merge a patch that fails SPRT even if it “looks stronger”.
- One functional change per commit. Bench nodes in the commit message
  (Reckless style: `Bench: 2569707`).
- When a net lands, delete HCE. Stockfish did. Reckless did.

## Concrete next commits

```
1. magic bitboards          (NPS, bench should rise, nodes may change)
2. stop-thread for UCI      (no Elo, GUI correctness)
3. continuation history     (SPRT)
4. singular extensions      (SPRT)
5. datagen stub             (FEN dumps from search)
6. Bullet 768×16 net        (first NNUE, expect a cliff)
```

## What “strongest point” actually means

There is no local trick that turns PeSTO + PVS into Stockfish. The strongest
point of *this* codebase is:

> a clean, perft-correct, OpenBench-ready engine whose next 1000 Elo are a
> straight line through NNUE self-play.

That is exactly the line Reckless walked from 0.1 (2005) to 0.9 (~3640).
We start at 0.1 with a better search already installed. The rest is data,
a net, and discipline.
