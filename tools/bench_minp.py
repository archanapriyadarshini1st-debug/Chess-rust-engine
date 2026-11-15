#!/usr/bin/env python3
"""Noise-robust A/B timing of two engine binaries on the deterministic `bench` command.

Why: on shared 4-vCPU VMs (GitHub runners, sandboxes) the SAME binary swings +-20-30% NPS
between single runs (EXP-LP1 measured 913k..1344k NPS for one binary), and no hardware
perf counters are exposed. Single-shot or 5-sample NPS comparisons therefore produce
fake wins and fake losses. Noise can only ADD time, so compare low percentiles of many
interleaved, CPU-pinned runs of identical node counts.

usage: tools/bench_minp.py DEPTH RUNS BASE_BIN CAND_BIN [CPU]
Uses the engine-reported search time (nodes/nps), not process wall time.
Prints bench node counts (must match for a node-identical change) and min/p10/p25/median
ratios CAND/BASE (>1.0 means CAND is slower). Treat |ratio-1| < ~0.02 as "no difference".
"""
import statistics, subprocess, sys, time

depth, runs, base, cand = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
cpu = sys.argv[5] if len(sys.argv) > 5 else "3"
bins = {"base": base, "cand": cand}
T = {k: [] for k in bins}
nodes = {}
for r in range(runs):
    for k in (["base", "cand"] if r % 2 == 0 else ["cand", "base"]):  # alternate order
        out = subprocess.run(["taskset", "-c", cpu, bins[k]], input=f"bench {depth}\n",
                             capture_output=True, text=True).stdout.strip().splitlines()[-1]
        nodes[k] = int(out.split()[0])
        # search time from the engine's own "N nodes M nps" line: excludes the ~0.5 s process
        # start-up (attack tables) that would dilute wall-clock ratios of short benches.
        T[k].append(nodes[k] / int(out.split()[2]))
b, c = sorted(T["base"]), sorted(T["cand"])
print("bench nodes base/cand:", nodes["base"], nodes["cand"],
      "(IDENTICAL)" if nodes["base"] == nodes["cand"] else "(DIFFERENT: not a node-identical change)")
for name, i in (("min", 0), ("p10", runs // 10), ("p25", runs // 4)):
    print(f"{name:6s} base {b[i]:.4f}s cand {c[i]:.4f}s ratio {c[i] / b[i]:.3f}")
print(f"median base {statistics.median(b):.4f}s cand {statistics.median(c):.4f}s "
      f"ratio {statistics.median(c) / statistics.median(b):.3f}")
