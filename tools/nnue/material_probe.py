#!/usr/bin/env python3
"""Material sanity probe: does a net know what a piece is worth?

Evaluates positions built from one quiet middlegame by removing material, with the engine's
own `eval` command (HCE vs net, side-to-move POV), and flags gross disagreement.
Val-MSE on balanced data cannot see this failure (Agent E: -676 Elo net, val MSE 0.003).

usage: material_probe.py ./engine path/to/net.bin   (exit 1 if the net fails the probe)
"""
import os, re, subprocess, sys

BASE = "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 7"
# (label, fen, minimum expected eval for the side to move in cp)
# Floor rule, applied uniformly: the net must credit at least 50% of the nominal value of the
# missing material (N=B=320 -> 160, R=500 -> 250, Q=900 -> 450). A sigmoid-space loss compresses
# large scores, so we deliberately do not demand the full HCE value.
CASES = [
    ("balanced", BASE, None),
    ("W up a knight", "r1bq1rk1/ppp2ppp/3p1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 7", 160),
    ("W up a rook", "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 7".replace("r1bq1rk1", "r1bq2k1"), 250),
    ("W up a queen", "r1b2rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 7", 450),
    ("B up a queen", "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1B2RK1 w - - 0 7", None),
    ("W down a rook", "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/2BQ1RK1 w - - 0 7", None),
    ("KQ v K", "4k3/8/8/8/8/8/8/3QK3 w - - 0 1", 450),
    ("KR v K", "4k3/8/8/8/8/8/8/3RK3 w - - 0 1", 250),
    ("K v KQ (stm loses)", "3qk3/8/8/8/8/8/8/4K3 w - - 0 1", None),
]


def run(engine, env, fens):
    inp = "".join(f"position fen {f}\neval\n" for f in fens) + "quit\n"
    out = subprocess.run([engine], input=inp, capture_output=True, text=True, env=env, timeout=60).stdout
    return re.findall(r"eval_hce (-?\d+) eval_nnue (-?\d+|none)", out)


def main():
    engine, net = sys.argv[1], sys.argv[2]
    env = dict(os.environ, CRE_NNUE_FILE=net)
    rows = run(engine, env, [c[1] for c in CASES])
    assert len(rows) == len(CASES), "engine did not answer every eval"
    bad = 0
    print(f"{'position':22} {'HCE':>7} {'net':>7}  note")
    for (name, _, floor), (h, n) in zip(CASES, rows):
        if n == "none":
            print(f"{name:22} {h:>7} {'none':>7}  NET NOT LOADED"); bad += 1; continue
        h, n = int(h), int(n)
        note = ""
        if floor is not None and n < floor:
            note = f"FAIL: expected >= {floor}"; bad += 1
        elif abs(n - h) > 400:
            note = "WARN: >400 cp from HCE"
        print(f"{name:22} {h:>7} {n:>7}  {note}")
    print("PROBE", "FAILED" if bad else "passed", f"({bad} failures)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
