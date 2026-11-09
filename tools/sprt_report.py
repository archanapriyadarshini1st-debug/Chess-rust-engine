#!/usr/bin/env python3
"""Turn a fastchess SPRT log into a verdict + markdown summary.

Usage: sprt_report.py LOG [--md OUT.md] [--min-games N]

Exit codes (so a workflow can gate on it):
  0  H1 accepted  (patch is a gain at the tested bounds)  -> PASS
  1  H0 accepted  (patch is not a gain / is a regression) -> FAIL
  3  neither bound hit before the game budget ran out     -> INCONCLUSIVE

Written by Agent C. Pure stdlib so it runs anywhere.
"""
import argparse
import re
import sys

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def last(pattern, text, flags=0):
    m = None
    for m in re.finditer(pattern, text, flags):
        pass
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--md")
    ap.add_argument("--min-games", type=int, default=0,
                    help="treat an early accept below this many games as inconclusive")
    a = ap.parse_args()

    text = ANSI.sub("", open(a.log, errors="replace").read())

    res = last(r"Results of (.+?) vs (.+?) \((.*?)\):", text)
    elo = last(r"^Elo: (-?[\d.]+) \+/- ([\d.]+|nan|inf)(?:, nElo: (-?[\d.]+) \+/- ([\d.]+|nan|inf))?", text, re.M)
    games = last(r"^Games: (\d+), Wins: (\d+), Losses: (\d+), Draws: (\d+)", text, re.M)
    ptnml = last(r"^Ptnml\(0-2\): (\[[^\]]*\])", text, re.M)
    llr = last(r"^LLR: (-?[\d.]+) \(-?([\d.]+)%\) \((-?[\d.]+), (-?[\d.]+)\) \[(-?[\d.]+), (-?[\d.]+)\]", text, re.M)
    accepted = last(r"SPRT[^\n]*?(H[01])[^\n]*?accepted|(H[01]) (?:was )?accepted", text, re.I)

    n = int(games.group(1)) if games else 0
    verdict, code = "INCONCLUSIVE", 3
    if accepted:
        h = (accepted.group(1) or accepted.group(2)).upper()
        verdict, code = ("PASS", 0) if h == "H1" else ("FAIL", 1)
    elif llr:
        # Fall back to the numbers if the banner text changes between versions.
        v, lo, hi = float(llr.group(1)), float(llr.group(3)), float(llr.group(4))
        if v >= hi:
            verdict, code = "PASS", 0
        elif v <= lo:
            verdict, code = "FAIL", 1
    if code in (0, 1) and n < a.min_games:
        verdict, code = "INCONCLUSIVE", 3

    lines = [f"### SPRT verdict: **{verdict}**"]
    if res:
        lines.append(f"`{res.group(1)}` vs `{res.group(2)}` - {res.group(3)}")
    if games:
        lines.append(f"- games **{n}**: +{games.group(2)} -{games.group(3)} ={games.group(4)}")
    if elo:
        e = f"- Elo **{elo.group(1)} +/- {elo.group(2)}**"
        if elo.group(3):
            e += f"  (nElo {elo.group(3)} +/- {elo.group(4)})"
        lines.append(e)
    if ptnml:
        lines.append(f"- pentanomial (LL,LD,DD/WL,WD,WW) {ptnml.group(1)}")
    if llr:
        lines.append(f"- LLR **{llr.group(1)}** bounds ({llr.group(3)}, {llr.group(4)}), "
                     f"H0/H1 = [{llr.group(5)}, {llr.group(6)}]")
    if verdict == "INCONCLUSIVE":
        lines.append("- No bound reached. **Do not merge on this.** Re-dispatch with more rounds "
                     "or wider bounds.")
    if n < 100:
        lines.append(f"- WARNING only {n} games: any Elo number here is noise.")
    out = "\n".join(lines) + "\n"
    print(out)
    if a.md:
        with open(a.md, "w") as f:
            f.write(out)
    sys.exit(code)


if __name__ == "__main__":
    main()
