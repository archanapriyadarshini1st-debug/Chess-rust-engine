#!/usr/bin/env python3
"""Ship gate aggregator: "test it 5 times, and look for the downside, before shipping".

Written by Agent S. Pure stdlib. Used by .github/workflows/ship-gate.yml.

Why this exists
---------------
A single SPRT (sprt.yml) has a 5% false-pass rate, cannot see harness bias, and
says nothing about downsides. PR #5 (pawn correction history) shipped with an
IDENTICAL bench and then scored 12.5% vs UCI_Elo 2400 (70.8% before). Bench is
not strength. This gate therefore demands, before a change may be called
"shippable":

  1. K independent fixed-size replications (default 5) of TEST vs BASE, each
     with a different opening seed. Fixed size, no optional stopping.
  2. An A/A control (BASE vs BASE, same harness). If the harness shows an
     "Elo" for identical binaries, every verdict is INVALID.
  3. A downside check against an EXTERNAL opponent (SF19 UCI_Elo N): self-play
     can hide regressions that an independent opponent exposes.
  4. Reliability: no crashes / illegal moves / time forfeits by TEST that BASE
     does not also have, bench ran, perft green.
  5. Cost: NPS ratio and node-count change, reported next to the Elo.

Decision rules (FIXED BEFORE ANY RESULT, see experiments/EXP-S1-ship-gate.md):

  per-replication "significantly negative":  elo + 2.576*se < 0   (Bonferroni:
        5 reps x 0.5% one-sided ~ 2.5% family-wise false alarm)
  pooled LOS = P(TEST > BASE) from the pooled pentanomial normal approximation.
  heterogeneity = Cochran Q across replications, chi-square p < 0.01.

  BLOCK         any rep significantly negative, OR pooled LOS <= 2.5%, OR
                SF19 downside z <= -1.96, OR TEST has reliability failures
                that BASE does not.
  INVALID       missing/short replications or A/A control fails
                (|aa_elo| > 2.576*se_aa).
  INVESTIGATE   heterogeneity p < 0.01, OR SF19 downside z <= -1.28 (soft).
  SHIP          mode=improve : pooled LOS >= 99%, pooled elo >= --min-gain,
                               >= ceil(0.8*K) reps with elo > 0.
                mode=neutral : pooled elo - 1.96*se >= -margin (default 10),
                               i.e. we can rule out a loss larger than `margin`.
                mode=perf    : bench nodes IDENTICAL, NPS ratio >= 1.0 and
                               pooled not significantly negative.
  INCONCLUSIVE  none of the above: more games, not a claim.

Exit codes: 0 SHIP, 1 BLOCK, 2 INVALID, 3 INCONCLUSIVE, 4 INVESTIGATE.
"""
import argparse
import json
import math
import os
import re
import sys

ANSI = re.compile(r"\x1b\[[0-9;]*m")
Z99 = 2.5758293035489004   # two-sided 99% / one-sided 99.5%
Z95 = 1.959963984540054
Z90 = 1.2815515655446004   # one-sided 90%

EXIT = {"SHIP": 0, "BLOCK": 1, "INVALID": 2, "INCONCLUSIVE": 3, "INVESTIGATE": 4}


# ---------------------------------------------------------------- statistics
def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def elo_of(mu):
    mu = min(max(mu, 1e-9), 1 - 1e-9)
    return -400.0 * math.log10(1.0 / mu - 1.0)


def chi2_sf(x, k):
    """Survival function of chi-square with k dof (regularised upper gamma)."""
    if x <= 0:
        return 1.0
    a, xx = k / 2.0, x / 2.0
    term = 1.0 / a
    total = term
    n = 0
    while n < 2000:
        n += 1
        term *= xx / (a + n)
        total += term
        if term < 1e-14 * total:
            break
    p_lower = total * math.exp(-xx + a * math.log(xx) - math.lgamma(a))
    return max(0.0, min(1.0, 1.0 - p_lower))


def stats_from_ptnml(p):
    """p = [LL, LD, DD+WL, WD, WW] pair counts (fastchess order). Pair-level
    variance is the correct one for colour-swapped paired openings."""
    pairs = sum(p)
    if pairs <= 0:
        return None
    vals = [0.0, 0.25, 0.5, 0.75, 1.0]   # per-game score of the pair
    mu = sum(n * v for n, v in zip(p, vals)) / pairs
    var = sum(n * (v - mu) ** 2 for n, v in zip(p, vals)) / pairs
    return _finish(mu, var / pairs, 2 * pairs)


def stats_from_wdl(w, d, l):
    n = w + d + l
    if n <= 0:
        return None
    mu = (w + 0.5 * d) / n
    var = (w * (1 - mu) ** 2 + d * (0.5 - mu) ** 2 + l * (0 - mu) ** 2) / n
    return _finish(mu, var / n, n)


def _finish(mu, var_mu, games):
    se_mu = math.sqrt(max(var_mu, 1e-12))
    mu_c = min(max(mu, 1e-6), 1 - 1e-6)
    slope = 400.0 / (math.log(10) * mu_c * (1 - mu_c))
    return {
        "score": mu, "games": games, "elo": elo_of(mu), "se": se_mu * slope,
        "los": phi((mu - 0.5) / se_mu), "se_mu": se_mu,
    }


def pool_ptnml(plist):
    return [sum(x) for x in zip(*plist)]


# ------------------------------------------------------------------- parsing
def parse_log(path):
    """Last fastchess report in a log: W/D/L, ptnml. First engine = TEST."""
    text = ANSI.sub("", open(path, errors="replace").read())
    res = None
    for res in re.finditer(r"Results of (.+?) vs (.+?) \(", text):
        pass
    games = None
    for games in re.finditer(r"^Games: (\d+), Wins: (\d+), Losses: (\d+), Draws: (\d+)", text, re.M):
        pass
    ptn = None
    for ptn in re.finditer(r"^Ptnml\(0-2\):\s*\[?([\d,\s]+)\]?", text, re.M):
        pass
    if not games:
        return None
    out = {
        "games": int(games.group(1)), "w": int(games.group(2)),
        "l": int(games.group(3)), "d": int(games.group(4)),
        "first": res.group(1) if res else None, "second": res.group(2) if res else None,
    }
    if ptn:
        nums = [int(x) for x in re.findall(r"\d+", ptn.group(1))]
        if len(nums) == 5:
            out["ptnml"] = nums
    return out


def stats_of(rec):
    if rec is None:
        return None
    if "ptnml" in rec and sum(rec["ptnml"]) * 2 >= rec["games"] - 1:
        s = stats_from_ptnml(rec["ptnml"])
    else:
        s = stats_from_wdl(rec["w"], rec["d"], rec["l"])
    if s:
        s.update(w=rec["w"], d=rec["d"], l=rec["l"])
    return s


RELIAB = re.compile(r"illegal|time forfeit|loses on time|disconnect|stall|crash|unresponsive", re.I)


def reliability(pgn_path, test_name="test", base_name="base"):
    """Count abnormal terminations per engine (the loser of the game)."""
    cnt = {test_name: 0, base_name: 0}
    if not pgn_path or not os.path.exists(pgn_path):
        return None
    text = open(pgn_path, errors="replace").read()
    for g in re.split(r"\n\n(?=\[Event )", text):
        if not RELIAB.search(g):
            continue
        w = re.search(r'\[White "([^"]+)"\]', g)
        b = re.search(r'\[Black "([^"]+)"\]', g)
        r = re.search(r'\[Result "([^"]+)"\]', g)
        if not (w and b and r):
            continue
        loser = w.group(1) if r.group(1) == "0-1" else b.group(1) if r.group(1) == "1-0" else None
        if loser in cnt:
            cnt[loser] += 1
    return cnt


# --------------------------------------------------------------- the verdict
def evaluate(reps, aa, sf, bench, rel, a):
    """reps: list of stats dicts (None for missing); returns (verdict, report)."""
    notes, blockers, invalid, investigate, warns = [], [], [], [], []
    have = [r for r in reps if r]
    k = a.reps

    if len(have) < k:
        invalid.append(f"only {len(have)}/{k} replications produced a result")
    for i, r in enumerate(reps, 1):
        if r and r["games"] < a.min_games:
            invalid.append(f"rep{i} has {r['games']} games (< {a.min_games})")

    aa_ok = None
    if aa is None:
        if not a.allow_no_control:
            invalid.append("A/A control missing")
    else:
        aa_ok = abs(aa["elo"]) <= Z99 * aa["se"]
        if not aa_ok:
            invalid.append(f"A/A control shows {aa['elo']:+.1f} +/- {aa['se']:.1f} (99% bound exceeded): "
                           "harness is biased, no verdict is trustworthy")

    pooled = None
    het_p = None
    positives = 0
    if have:
        if all("ptnml" in r for r in have):
            pooled = stats_from_ptnml(pool_ptnml([r["ptnml"] for r in have]))
        else:
            pooled = stats_from_wdl(sum(r["w"] for r in have), sum(r["d"] for r in have),
                                    sum(r["l"] for r in have))
        for i, r in enumerate(reps, 1):
            if not r:
                continue
            if r["elo"] > 0:
                positives += 1
            if r["elo"] + Z99 * r["se"] < 0:
                blockers.append(f"rep{i} significantly NEGATIVE: {r['elo']:+.1f} +/- {r['se']:.1f} (99% upper bound < 0)")
        if len(have) >= 2:
            ws = [1.0 / (r["se"] ** 2) for r in have]
            mean = sum(w * r["elo"] for w, r in zip(ws, have)) / sum(ws)
            q = sum(w * (r["elo"] - mean) ** 2 for w, r in zip(ws, have))
            het_p = chi2_sf(q, len(have) - 1)
            if het_p < 0.01:
                investigate.append(f"replications disagree (Cochran Q p={het_p:.4f}): result is not "
                                   "reproducible, find out why before shipping")
        if pooled and pooled["los"] <= 0.025:
            blockers.append(f"pooled result significantly WORSE: {pooled['elo']:+.1f} +/- {pooled['se']:.1f}, "
                            f"LOS {pooled['los']*100:.1f}%")

    sf_z = None
    if sf and sf.get("test") and sf.get("base"):
        t, b = sf["test"], sf["base"]
        diff = t["score"] - b["score"]
        se = math.sqrt(t["se_mu"] ** 2 + b["se_mu"] ** 2)
        sf_z = diff / se if se > 0 else 0.0
        if sf_z <= -Z95:
            blockers.append(f"DOWNSIDE vs SF19: TEST scores {t['score']*100:.1f}% vs BASE {b['score']*100:.1f}% "
                            f"(z={sf_z:.2f}, significantly worse against an independent opponent)")
        elif sf_z <= -Z90:
            investigate.append(f"soft downside vs SF19: TEST {t['score']*100:.1f}% vs BASE {b['score']*100:.1f}% (z={sf_z:.2f})")
    elif a.require_sf:
        invalid.append("SF19 downside check required but missing")

    if rel:
        t_bad, b_bad = rel.get("test", 0), rel.get("base", 0)
        if t_bad > b_bad:
            blockers.append(f"RELIABILITY: TEST has {t_bad} crash/illegal/time-forfeit losses vs BASE {b_bad}")
        elif t_bad:
            warns.append(f"both engines show abnormal terminations (test {t_bad}, base {b_bad})")

    if bench:
        if bench.get("perft_ok") is False:
            blockers.append("perft FAILED on TEST")
        if bench.get("bench_ok") is False:
            blockers.append("bench did not complete on TEST")
        nps = bench.get("nps_ratio")
        if nps is not None and nps < 0.90:
            warns.append(f"NPS ratio {nps:.3f} (TEST is >10% slower; must be paid for by Elo)")
        nr = bench.get("nodes_ratio")
        if nr is not None and nr > 1.30:
            warns.append(f"bench nodes x{nr:.2f} at fixed depth (search is much wider)")

    if invalid:
        verdict = "INVALID"
    elif blockers:
        verdict = "BLOCK"
    elif investigate:
        verdict = "INVESTIGATE"
    else:
        need_pos = math.ceil(0.8 * k)
        if a.mode == "improve":
            ok = bool(pooled and pooled["los"] >= 0.99 and pooled["elo"] >= a.min_gain and positives >= need_pos)
            verdict = "SHIP" if ok else "INCONCLUSIVE"
            if not ok and pooled and pooled["los"] >= 0.99 and positives < need_pos:
                notes.append(f"pooled LOS ok but only {positives}/{k} reps positive (< {need_pos})")
        elif a.mode == "neutral":
            ok = bool(pooled and pooled["elo"] - Z95 * pooled["se"] >= -a.margin)
            verdict = "SHIP" if ok else "INCONCLUSIVE"
        elif a.mode == "perf":
            identical = bool(bench) and bench.get("nodes_identical") is True
            fast = bool(bench) and (bench.get("nps_ratio") or 0) >= 1.0
            verdict = "SHIP" if (identical and fast) else "INCONCLUSIVE"
            if not identical:
                notes.append("mode=perf requires bench nodes IDENTICAL (a search-changing patch is not a perf patch)")
            if not fast:
                notes.append("mode=perf requires NPS ratio >= 1.0")
        else:
            verdict = "INCONCLUSIVE"

    report = {
        "verdict": verdict, "mode": a.mode, "reps": reps, "aa": aa, "aa_ok": aa_ok,
        "pooled": pooled, "positives": positives, "cochran_p": het_p,
        "sf": sf, "sf_z": sf_z, "reliability": rel, "bench": bench,
        "blockers": blockers, "invalid": invalid, "investigate": investigate,
        "warnings": warns, "notes": notes,
    }
    return verdict, report


def fmt(s):
    if not s:
        return "n/a"
    return (f"{s['elo']:+.1f} +/- {Z95*s['se']:.1f} (95%), LOS {s['los']*100:.1f}%, "
            f"{s['games']}g +{s['w']} -{s['l']} ={s['d']}, score {s['score']*100:.1f}%")


def markdown(rep, meta):
    L = [f"## Ship gate: **{rep['verdict']}**  (mode `{rep['mode']}`)", ""]
    for k in ("test", "base", "tc", "book_sha256", "test_bin_sha256", "base_bin_sha256",
              "fastchess", "sf19_sha256", "seed_base", "rounds"):
        if k in meta:
            L.append(f"- {k}: `{meta[k]}`")
    L += ["", "| run | result |", "|---|---|"]
    for i, r in enumerate(rep["reps"], 1):
        L.append(f"| rep{i} | {fmt(r)} |")
    L.append(f"| **pooled** | {fmt(rep['pooled'])} |")
    aa_state = "OK" if rep["aa_ok"] else ("FAIL" if rep["aa_ok"] is False else "missing")
    L.append(f"| A/A control | {fmt(rep['aa'])} -> {aa_state} |")
    if rep["cochran_p"] is not None:
        L.append(f"| heterogeneity | Cochran Q p = {rep['cochran_p']:.4f} |")
    L.append(f"| reps positive | {rep['positives']}/{len([r for r in rep['reps'] if r])} |")
    sf = rep["sf"]
    if sf and sf.get("test") and sf.get("base"):
        L.append(f"| SF19 TEST | {fmt(sf['test'])} |")
        L.append(f"| SF19 BASE | {fmt(sf['base'])} |")
        L.append(f"| SF19 z (test-base) | {rep['sf_z']:+.2f} |")
    if rep["reliability"]:
        L.append(f"| abnormal terminations | {rep['reliability']} |")
    b = rep["bench"]
    if b:
        L.append(f"| bench | nodes test/base {b.get('test_nodes')}/{b.get('base_nodes')}, "
                 f"NPS ratio {b.get('nps_ratio')}, perft_ok {b.get('perft_ok')} |")
    for title, key in (("BLOCKERS", "blockers"), ("INVALID", "invalid"),
                       ("INVESTIGATE", "investigate"), ("Warnings", "warnings"), ("Notes", "notes")):
        if rep[key]:
            L += ["", f"**{title}**"] + [f"- {x}" for x in rep[key]]
    L += ["", "_Elo from pentanomial pair statistics, normal approximation. Fixed-size replications, "
          "no optional stopping. This is a development gate, not a rating._"]
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------- CLI
def load_dir(d, k):
    def maybe(p):
        return stats_of(parse_log(p)) if os.path.exists(p) else None
    reps = [maybe(os.path.join(d, f"rep{i}", "run.log")) for i in range(1, k + 1)]
    aa = maybe(os.path.join(d, "aa", "run.log"))
    sf = {"test": maybe(os.path.join(d, "sf", "sf_test.log")),
          "base": maybe(os.path.join(d, "sf", "sf_base.log"))}
    rel = {"test": 0, "base": 0}
    seen = False
    for i in range(1, k + 1):
        r = reliability(os.path.join(d, f"rep{i}", "run.pgn"))
        if r is not None:
            seen = True
            rel["test"] += r["test"]
            rel["base"] += r["base"]
    bench = None
    bp = os.path.join(d, "rep1", "bench.json")
    if os.path.exists(bp):
        bench = json.load(open(bp))
    meta = {}
    mp = os.path.join(d, "rep1", "meta.json")
    if os.path.exists(mp):
        meta = json.load(open(mp))
    return reps, aa, sf, bench, (rel if seen else None), meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--mode", choices=["improve", "neutral", "perf"], default="improve")
    ap.add_argument("--min-gain", type=float, default=0.0)
    ap.add_argument("--margin", type=float, default=10.0)
    ap.add_argument("--min-games", type=int, default=100)
    ap.add_argument("--allow-no-control", action="store_true")
    ap.add_argument("--require-sf", action="store_true")
    ap.add_argument("--md")
    ap.add_argument("--json")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.dir:
        ap.error("dir required")
    reps, aa, sf, bench, rel, meta = load_dir(a.dir, a.reps)
    verdict, rep = evaluate(reps, aa, sf, bench, rel, a)
    rep["meta"] = meta
    md = markdown(rep, meta)
    print(md)
    if a.md:
        open(a.md, "w").write(md)
    if a.json:
        json.dump(rep, open(a.json, "w"), indent=2, default=str)
    return EXIT[verdict]


# ------------------------------------------------------------------ selftest
def _mk(w, d, l):
    """Expected pair counts for independent games with the given W/D/L split."""
    tot = w + d + l
    n = tot // 2
    mw, md_, ml = w / tot, d / tot, l / tot
    p = [ml * ml, 2 * ml * md_, md_ * md_ + 2 * mw * ml, 2 * mw * md_, mw * mw]
    cnt = [round(x * n) for x in p]
    return {"games": 2 * sum(cnt), "w": w, "d": d, "l": l, "ptnml": cnt}


def selftest():
    class A:
        reps = 5; mode = "improve"; min_gain = 0.0; margin = 10.0; min_games = 100
        allow_no_control = False; require_sf = False

    def run(reps_wdl, aa_wdl=(100, 200, 100), sf=None, bench=None, rel=None, mode="improve", **kw):
        a = A()
        a.mode = mode
        for k, v in kw.items():
            setattr(a, k, v)
        reps = [stats_of(_mk(*x)) for x in reps_wdl]
        aa = stats_of(_mk(*aa_wdl)) if aa_wdl else None
        sfd = None
        if sf:
            sfd = {"test": stats_of(_mk(*sf[0])), "base": stats_of(_mk(*sf[1]))}
        return evaluate(reps, aa, sfd, bench, rel, a)

    ok = True

    def check(name, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print(("PASS " if good else "FAIL ") + f"{name}: got {got}, want {want}")

    s = stats_from_wdl(50, 0, 50)
    check("equal -> elo 0", round(s["elo"], 6), 0.0)
    check("75% -> +191 Elo", round(elo_of(0.75)), 191)
    check("chi2 sf(9.488,4)=0.05", round(chi2_sf(9.488, 4), 3), 0.05)
    check("chi2 sf(6.635,1)=0.01", round(chi2_sf(6.635, 1), 3), 0.01)

    gain = (120, 240, 100)
    v, _ = run([gain] * 5)
    check("consistent gain -> SHIP", v, "SHIP")
    v, _ = run([(100, 260, 100)] * 5)
    check("no gain -> INCONCLUSIVE", v, "INCONCLUSIVE")
    v, _ = run([(20, 150, 290)] * 5)
    check("PR#5-style collapse -> BLOCK", v, "BLOCK")
    v, _ = run([gain, gain, gain, gain, (40, 160, 260)])
    check("one bad rep -> BLOCK", v, "BLOCK")
    v, _ = run([gain] * 5, aa_wdl=(130, 200, 70))
    check("A/A failure -> INVALID", v, "INVALID")
    v, _ = run([gain] * 4)
    check("missing rep -> INVALID", v, "INVALID")
    v, _ = run([gain] * 5, sf=((30, 40, 30), (55, 34, 11)))
    check("SF19 downside -> BLOCK", v, "BLOCK")
    v, _ = run([gain] * 5, sf=((40, 44, 16), (55, 34, 11)))
    check("SF19 soft downside -> INVESTIGATE", v, "INVESTIGATE")
    v, _ = run([gain] * 5, sf=((50, 30, 20), (50, 30, 20)))
    check("SF19 equal -> SHIP", v, "SHIP")
    v, _ = run([gain] * 5, rel={"test": 3, "base": 0})
    check("test crashes -> BLOCK", v, "BLOCK")
    v, _ = run([gain] * 5, bench={"perft_ok": False})
    check("perft fail -> BLOCK", v, "BLOCK")
    v, _ = run([(100, 260, 100)] * 5, mode="perf",
               bench={"nodes_identical": True, "nps_ratio": 1.12, "perft_ok": True, "bench_ok": True})
    check("perf identical+faster -> SHIP", v, "SHIP")
    v, _ = run([(100, 260, 100)] * 5, mode="perf",
               bench={"nodes_identical": False, "nps_ratio": 1.12, "perft_ok": True, "bench_ok": True})
    check("perf but nodes differ -> INCONCLUSIVE", v, "INCONCLUSIVE")
    v, _ = run([(190, 160, 110), (110, 160, 190), (150, 160, 150), (190, 160, 110), (110, 160, 190)])
    check("inconsistent reps -> BLOCK or INVESTIGATE", v in ("BLOCK", "INVESTIGATE"), True)

    # parser round-trip on a fastchess-shaped log
    import tempfile
    log = ("Results of test vs base (10+0.1, 1t, 16MB, openings_book.epd):\n"
           "Elo: 12.50 +/- 20.1, nElo: 20.0 +/- 30.0\nLOS: 90.00 %, DrawRatio: 60.00 %, PairsRatio: 1.20\n"
           "Games: 300, Wins: 90, Losses: 80, Draws: 130, Points: 155.0 (51.67 %)\n"
           "Ptnml(0-2): [10, 40, 60, 30, 10], WL/DD Ratio: 1.0\n")
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
        f.write("\x1b[0m" + log)
    rec = parse_log(f.name)
    check("parse ptnml", rec.get("ptnml"), [10, 40, 60, 30, 10])
    check("parse wdl", (rec["w"], rec["d"], rec["l"]), (90, 130, 80))

    # whole-gate false-SHIP rate under H0 (identical engines), simulated
    import random
    random.seed(7)
    ships, trials = 0, 1000
    for _ in range(trials):
        reps = []
        for _i in range(5):
            w = l = d = 0
            for _p in range(150):
                for _g in range(2):
                    x = random.random()
                    if x < 0.2:
                        w += 1
                    elif x < 0.4:
                        l += 1
                    else:
                        d += 1
            reps.append(stats_of(_mk(w, d, l)))
        aa = stats_of(_mk(150, 300, 150))
        v, _ = evaluate(reps, aa, None, None, None, A())
        ships += v == "SHIP"
    rate = ships / trials
    print(f"INFO H0 false-SHIP rate over {trials} simulated gates: {rate*100:.1f}% (target <= 2%)")
    ok &= rate <= 0.02
    print("SELFTEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
