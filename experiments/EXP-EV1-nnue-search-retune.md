# EXP-EV1: net audit gate + search retune under NNUE (Agent EV)

Repository / baseline: `archanapriyadarshini1st-debug/Chess-rust-engine` `main` **73d0379**, `bench 10` = **553783** nodes.
Engine binary sha256 (release, `-C target-cpu=native`, rustc 1.100): recorded in the results section.
Stockfish 19 universal sha256 prefix `0f83d24cc46d2c66` (pinned). fastchess 1.8.3-alpha.
Hardware: 4 vCPU / 3.9 GB sandbox, 1 thread per engine, Hash 16 (fixed-node) / 64 (real TC).

## Part 1: net audit (tools/net_eval_audit.py)
Hypothesis: a net whose static eval agrees with SF19 (depth 12) worse than the HCE does is defective and
will lose to HCE; agreement can therefore be used as a free pre-gate before spending games.

| net | sha256[:12] | r vs SF19 d12 | sign agree | fixed-node vs HCE (same binary) |
|---|---|---|---|---|
| HCE | - | 0.913 | 0.910 | - |
| stage0-selfd7 | 9650210ad84e | 0.918 | 0.929 | not run |
| lichess-bulk-43007306133 | bb5bb8a868c1 | 0.934 | 0.962 | not run |
| lichess-bulk-43234447213 | 964d07413bac | 0.936 | 0.964 | 34-2-4 / 40 @100k nodes (preliminary) |
| ft-43234452295 | 7253b07162ce | **0.683** | **0.737** | **0-0-40 @100k, 0-0-40 @20k** |

n = 1,200 positions from engine-vs-engine games (biased toward reachable positions), labels cached by FEN.
Decision: **reject `nnue/ft-43234452295`** (do not gate it). Root cause not determined (suspect stm/perspective
handling or a diverged fine-tune; the FT run's training log would settle it).

## Part 2: search retune under NNUE
Hypothesis: the search margins in `src/params.rs` were set for the HCE score distribution; with a net they are
sub-optimal and SPSA on the net recovers Elo.

Change: **none in `src/`**. Only `tools/spsa.py --nodes N` (fixed nodes per move instead of a clock; floor 20000).
SPSA: 12 params (RfpMargin, RfpImproving, NmpEvalDiv, FutilityMargin, SeeQuiet, SeeCapture, LmrScale, LmrHistDiv,
HistPrune, LmpBase, SeMargin, AspWindow), net lichess-bulk-43234447213, 40k nodes/move, 8 games/iteration,
<= 600 iterations, Polyak average of the last 25%.

Pre-registered decision rule (fixed before any result):
1. tuned vs default, same binary via `setoption`, **5 replicates x >= 400 games, fixed 100k nodes**, distinct `-srand`; plus an A/A control.
2. **5 x 100 games at 10+0.1** (fixed nodes ignore NPS and time management).
3. downside check: tuned and default each vs SF19 `UCI_Elo 3000`, same games.
KEEP only if pooled CI lower bound > 0, >= 4/5 replicates > 50% at both fixed nodes and real TC. If fixed nodes and
real TC disagree, the real-TC result decides and the discrepancy is reported. Negative results are kept.

## Results
(filled in below as they arrive)
