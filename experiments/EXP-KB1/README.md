# EXP-KB1 raw artifacts

| file | what |
| --- | --- |
| `sf3000_a.pgn`, `sf3000_b.pgn` | the two 60-game matches (seeds 4242, 7777), fastchess PGN with per-move eval/depth/time |
| `sf3000_{a,b}.json` | `tools/summarize.py --json` output for each |
| `sf3000_{a,b}.fastchess.log.gz` | raw fastchess logs |
| `blindspots_a.jsonl` | first line = provenance, then 39 SF19-MAX-relabelled blind-spot positions (`tools/blindspots.py`, replicate A) |
| `control.json` | 232 fixed-ply positions (ply ~30 and ~50, our side to move) from both PGNs: teacher / HCE / NNUE depth-12 scores |
| `audit.py` | eval-lag + "blind at the decisive moment" audit over a PGN |
| `control.py`, `ctl_stats.py` | build `control.json` and compute correlation / sign accuracy / paired bootstrap |
| `nnue_vs_hce.py` | static + depth-14 comparison on the blind-spot positions (selection-biased, see the record) |

Scripts have absolute `/tmp/run` paths because that is where they ran. Edit the constants at the top to re-run.
