#!/usr/bin/env python3
"""Ship gate: "test it five times before shipping" as code. [Agent S3]

A single SPRT stream answers "did this stop at a lucky moment?" badly and says nothing
about side effects. The ship gate runs the candidate through FIVE independent replicate
matches (disjoint opening slices, fixed game count, no early stopping), plus correctness
and side-effect probes, and only then returns SHIP.

Sub-commands (pure stdlib, runs anywhere):

  probe     bench determinism (N runs each), interleaved NPS ratio, binary hashes -> side.json
  parse     one fastchess PGN -> replicate JSON (W/D/L from the candidate's view, faults)
  verdict   side.json + replicate JSONs -> verdict.json + verdict.md, exit code
  calibrate Monte-Carlo false-ship rate / power of the decision rule
  selftest  statistics + decision-rule unit tests (the gate tests itself before it judges)

Exit codes of `verdict`:  0 SHIP | 1 REJECT | 2 INVESTIGATE | 3 INCONCLUSIVE

Decision rule (fixed BEFORE any result; do not edit after seeing one):

  Hard REJECT (any one):
    * perft failed
    * candidate bench not deterministic across probe runs (single thread)
    * candidate lost a game by time forfeit / illegal move / crash / disconnect
    * any replicate significantly negative (99% CI upper bound < 0 Elo)
    * pooled result significantly negative (95% CI upper bound < 0 Elo)
    * median NPS ratio < 0.90 (large unexplained slowdown)
    * --expect-node-identical and bench nodes differ from base
  INVESTIGATE: replicates disagree with each other (heterogeneity p < 0.01), or NPS ratio
    in [0.90, 0.95) (a slowdown must be explained by a search gain).
  mode=improve      SHIP needs pooled LOS >= 97.5%, pooled 95% CI lower bound > 0,
                    and a positive score in >= ceil(k/2) replicates.
  mode=noninferior  SHIP needs pooled 95% CI lower bound >= -margin Elo (default 8)
                    (use for refactors / speedups that claim "no strength change").
  Otherwise INCONCLUSIVE with an estimate of how many more games are needed.
  Fewer replicates / fewer games than required is always INCONCLUSIVE, never SHIP.
"""
import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time

Z95, Z99 = 1.959964, 2.575829


# ----------------------------------------------------------------------------- statistics
def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def elo_of(score):
    if score <= 0.0:
        return -math.inf
    if score >= 1.0:
        return math.inf
    return -400.0 * math.log10(1.0 / score - 1.0)


def stats(w, d, l, z=Z95):
    """Trinomial logistic-Elo estimate. Ignores opening-pair correlation, which makes
    the interval slightly *wider* than a pentanomial one, i.e. conservative."""
    n = w + d + l
    if n == 0:
        return dict(n=0, w=w, d=d, l=l, score=0.5, elo=0.0, lo=-math.inf, hi=math.inf,
                    se_elo=math.inf, los=0.5)
    s = (w + 0.5 * d) / n
    var = (w + 0.25 * d) / n - s * s
    se = math.sqrt(max(var, 1e-12) / n)
    lo = elo_of(max(s - z * se, 0.0))
    hi = elo_of(min(s + z * se, 1.0))
    los = 0.5 if w + l == 0 else norm_cdf((w - l) / math.sqrt(w + l))
    se_elo = (hi - lo) / (2 * z) if math.isfinite(hi - lo) else math.inf
    return dict(n=n, w=w, d=d, l=l, score=s, elo=elo_of(s), lo=lo, hi=hi, se_elo=se_elo, los=los)


def chi2_sf(x, df):
    """Survival function of chi-square via the regularised lower incomplete gamma series."""
    if x <= 0:
        return 1.0
    a, xx = df / 2.0, x / 2.0
    term = total = 1.0 / a
    k = 0
    while abs(term) > 1e-14 * abs(total) and k < 10000:
        k += 1
        term *= xx / (a + k)
        total += term
    p = total * math.exp(-xx + a * math.log(xx) - math.lgamma(a))
    return max(0.0, min(1.0, 1.0 - p))


def heterogeneity(reps):
    """Do the replicate scores agree with one common score? (chi-square, k-1 dof)"""
    rs = [r for r in reps if r["n"] > 0]
    if len(rs) < 2:
        return 1.0
    tw = sum(r["w"] for r in rs)
    td = sum(r["d"] for r in rs)
    tl = sum(r["l"] for r in rs)
    p = stats(tw, td, tl)["score"]
    x = 0.0
    for r in rs:
        var = max((r["w"] + 0.25 * r["d"]) / r["n"] - r["score"] ** 2, 1e-12) / r["n"]
        x += (r["score"] - p) ** 2 / var
    return chi2_sf(x, len(rs) - 1)


def fmt_elo(e):
    return "inf" if e == math.inf else "-inf" if e == -math.inf else f"{e:+.1f}"


# ----------------------------------------------------------------------------- PGN parsing
FAULT_RE = re.compile(r"time forfeit|loses on time|out of time|illegal|disconnect|stall|crash|"
                      r"abandon|unresponsive|failed to start", re.I)


def split_games(text):
    return [g for g in re.split(r"\n\s*\n(?=\[Event )", text.strip()) if g.strip()]


def parse_pgn(path, cand="test", opp="base"):
    text = open(path, errors="replace").read()
    w = d = l = 0
    cand_faults, opp_faults, bad = [], [], 0
    for g in split_games(text):
        tags = dict(re.findall(r'\[(\w+) "([^"]*)"\]', g))
        res, white, black = tags.get("Result"), tags.get("White"), tags.get("Black")
        if res not in ("1-0", "0-1", "1/2-1/2") or {white, black} != {cand, opp}:
            bad += 1
            continue
        cand_white = white == cand
        if res == "1/2-1/2":
            d += 1
            continue
        cand_won = (res == "1-0") == cand_white
        if cand_won:
            w += 1
        else:
            l += 1
        # A fault only counts against the side that LOST the game
        blob = " ".join(tags.get(k, "") for k in ("Termination", "TerminationDetails", "Reason"))
        blob += " " + " ".join(re.findall(r"\{([^}]*)\}\s*(?:1-0|0-1|1/2-1/2|\*)\s*$", g))
        if FAULT_RE.search(blob):
            (opp_faults if cand_won else cand_faults).append(
                f"{tags.get('Round', '?')}: {blob.strip()[:80]}")
    return dict(w=w, d=d, l=l, n=w + d + l, skipped_games=bad,
                cand_faults=cand_faults, opp_faults=opp_faults)


# ----------------------------------------------------------------------------- probes
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def bench_once(engine, depth):
    t = time.perf_counter()
    out = subprocess.run([engine, "bench", str(depth)], capture_output=True, text=True,
                         timeout=300).stdout
    dt = time.perf_counter() - t
    m = None
    for m in re.finditer(r"(\d+)\s+nodes", out):
        pass
    if not m:
        raise RuntimeError(f"{engine} bench {depth}: no node count in output: {out[-200:]!r}")
    nodes = int(m.group(1))
    return nodes, nodes / dt


def cpu_model():
    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "unknown"


def cmd_probe(a):
    out = dict(test_sha256=sha256(a.test), base_sha256=sha256(a.base), depth=a.depth,
               runs=a.runs, cpu=cpu_model(), nproc=os.cpu_count(), perft_ok=a.perft_ok,
               rustflags=a.rustflags, test_nodes=[], base_nodes=[], test_nps=[], base_nps=[])
    bench_once(a.test, 8)  # warm-up (page cache, CPU frequency)
    bench_once(a.base, 8)
    for i in range(a.runs):  # interleave so slow drift hits both engines equally
        pair = [("test", a.test), ("base", a.base)]
        if i % 2:
            pair.reverse()
        for name, exe in pair:
            n, nps = bench_once(exe, a.depth)
            out[f"{name}_nodes"].append(n)
            out[f"{name}_nps"].append(nps)
    json.dump(out, open(a.out, "w"), indent=2)
    print(json.dumps({k: out[k] for k in ("test_nodes", "base_nodes")}))
    return 0


def cmd_parse(a):
    r = parse_pgn(a.pgn)
    st = stats(r["w"], r["d"], r["l"])
    r.update(replicate=a.replicate, score=st["score"], elo=st["elo"], lo=st["lo"], hi=st["hi"],
             los=st["los"])
    r = {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in r.items()}
    json.dump(r, open(a.out, "w"), indent=2)
    print(f"replicate {a.replicate}: +{r['w']} -{r['l']} ={r['d']}  score {r['score']:.3f}")
    return 0


# ----------------------------------------------------------------------------- verdict
def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if len(xs) % 2 else 0.5 * (xs[len(xs) // 2 - 1] + xs[len(xs) // 2])


def decide(side, reps, mode="improve", margin=8.0, expect_replicates=5, min_games=100,
           expect_node_identical=False):
    """Pure function: (probe json, replicate dicts) -> (verdict, reasons, numbers)."""
    rejects, invest, notes = [], [], []
    rs = []
    for r in reps:
        s = stats(r["w"], r["d"], r["l"])
        s99 = stats(r["w"], r["d"], r["l"], z=Z99)
        s.update(hi99=s99["hi"], lo99=s99["lo"], replicate=r.get("replicate"),
                 cand_faults=r.get("cand_faults", []), opp_faults=r.get("opp_faults", []))
        rs.append(s)
    pooled = stats(sum(r["w"] for r in rs), sum(r["d"] for r in rs), sum(r["l"] for r in rs))
    het = heterogeneity(rs)
    positive = sum(1 for r in rs if r["score"] > 0.5)

    tn, bn = side.get("test_nodes", []), side.get("base_nodes", [])
    if not side.get("perft_ok", False):
        rejects.append("perft failed")
    if len(set(tn)) != 1:
        rejects.append(f"candidate bench is not deterministic across runs: {sorted(set(tn))}")
    if len(set(bn)) != 1:
        notes.append(f"base bench is not deterministic across runs: {sorted(set(bn))}")
    nodes_same = len(set(tn)) == 1 and len(set(bn)) == 1 and tn[0] == bn[0]
    if expect_node_identical and not nodes_same:
        rejects.append("claimed node-identical, but bench nodes differ "
                       f"(test {sorted(set(tn))} vs base {sorted(set(bn))})")
    ratios = [t / b for t, b in zip(side.get("test_nps", []), side.get("base_nps", [])) if b > 0]
    nps_ratio = median(ratios) if ratios else None
    if nps_ratio is not None:
        if nps_ratio < 0.90:
            rejects.append(f"median NPS ratio {nps_ratio:.3f} < 0.90")
        elif nps_ratio < 0.95:
            invest.append(f"median NPS ratio {nps_ratio:.3f}: slowdown must be justified by search gain")

    for r in rs:
        if r["cand_faults"]:
            rejects.append(f"replicate {r['replicate']}: candidate lost by fault: {r['cand_faults'][:2]}")
        if r["n"] and r["hi99"] < 0:
            rejects.append(f"replicate {r['replicate']} significantly negative "
                           f"({fmt_elo(r['elo'])}, 99% upper {fmt_elo(r['hi99'])})")
    if pooled["n"] and pooled["hi"] < 0:
        rejects.append(f"pooled result significantly negative ({fmt_elo(pooled['elo'])}, "
                       f"95% upper {fmt_elo(pooled['hi'])})")
    if het < 0.01:
        invest.append(f"replicates disagree (heterogeneity p={het:.4f}); something is unstable")

    incomplete = len(rs) < expect_replicates or any(r["n"] < min_games for r in rs)
    if mode == "improve":
        gain_ok = pooled["los"] >= 0.975 and pooled["lo"] > 0 and positive >= math.ceil(len(rs) / 2)
    else:
        gain_ok = pooled["lo"] >= -margin

    if rejects:
        verdict = "REJECT"
    elif invest:
        verdict = "INVESTIGATE"
    elif incomplete:
        verdict = "INCONCLUSIVE"
        notes.append(f"incomplete: {len(rs)}/{expect_replicates} replicates, "
                     f"min games per replicate {min((r['n'] for r in rs), default=0)} (need {min_games})")
    elif gain_ok:
        verdict = "SHIP"
    else:
        verdict = "INCONCLUSIVE"
        if mode == "improve":
            target = pooled["elo"] if pooled["elo"] > 1 else None
        else:
            target = margin + max(pooled["elo"], 0.0)
        if pooled["n"] and target and math.isfinite(pooled["se_elo"]):
            need = pooled["n"] * (Z95 * pooled["se_elo"] / target) ** 2
            notes.append(f"~{int(need)} total games needed to resolve at the observed effect "
                         f"(have {pooled['n']}); an effect that small may not be worth shipping")
    num = dict(pooled=pooled, replicates=rs, heterogeneity_p=het, replicates_positive=positive,
               nps_ratio=nps_ratio, bench_nodes_identical=nodes_same)
    return verdict, rejects + invest + notes, num


EXIT = {"SHIP": 0, "REJECT": 1, "INVESTIGATE": 2, "INCONCLUSIVE": 3}


def render_md(verdict, reasons, num, side, meta):
    p = num["pooled"]
    L = [f"## Ship gate verdict: **{verdict}**", "",
         f"`{meta.get('test')}` vs `{meta.get('base')}` | mode `{meta.get('mode')}` | tc `{meta.get('tc')}` "
         f"| run `{meta.get('run_id', '?')}`", "",
         "| replicate | +W | -L | =D | score | Elo | 95% CI | faults |", "|---|---|---|---|---|---|---|---|"]
    for r in num["replicates"]:
        L.append(f"| {r['replicate']} | {r['w']} | {r['l']} | {r['d']} | {r['score']*100:.1f}% | "
                 f"{fmt_elo(r['elo'])} | [{fmt_elo(r['lo'])}, {fmt_elo(r['hi'])}] | {len(r['cand_faults'])} |")
    L.append(f"| **pooled** | {p['w']} | {p['l']} | {p['d']} | {p['score']*100:.1f}% | {fmt_elo(p['elo'])} | "
             f"[{fmt_elo(p['lo'])}, {fmt_elo(p['hi'])}] | |")
    nps = f"- median NPS ratio test/base: {num['nps_ratio']:.3f}" if num["nps_ratio"] else "- NPS ratio: n/a"
    L += ["", f"- pooled LOS **{p['los']*100:.1f}%**; replicates positive **{num['replicates_positive']}/{len(num['replicates'])}**; "
          f"heterogeneity p = {num['heterogeneity_p']:.3f}",
          f"- bench nodes (depth {side.get('depth')}): test {sorted(set(side.get('test_nodes', [])))} "
          f"base {sorted(set(side.get('base_nodes', [])))} -> {'identical' if num['bench_nodes_identical'] else 'differ'}",
          nps,
          f"- perft: {'ok' if side.get('perft_ok') else 'FAILED'}; test sha256 `{side.get('test_sha256', '')[:16]}` "
          f"base sha256 `{side.get('base_sha256', '')[:16]}`",
          f"- hardware: {side.get('cpu')} ({side.get('nproc')} vCPU); flags `{side.get('rustflags')}`"]
    if reasons:
        L += ["", "**Reasons / notes**"] + [f"- {x}" for x in reasons]
    L += ["", "_Statistics: trinomial logistic Elo, conservative (ignores opening-pair correlation). "
          "Pooled games are exactly the union of the replicate games; nothing is dropped or re-selected._"]
    return "\n".join(L) + "\n"


def cmd_verdict(a):
    side = json.load(open(a.side))
    reps = [json.load(open(os.path.join(a.dir, f))) for f in sorted(os.listdir(a.dir))
            if f.startswith("rep") and f.endswith(".json")]
    verdict, reasons, num = decide(side, reps, a.mode, a.margin, a.replicates, a.min_games,
                                   a.expect_node_identical)
    meta = dict(test=a.test, base=a.base, mode=a.mode, tc=a.tc, run_id=os.environ.get("GITHUB_RUN_ID"))
    md = render_md(verdict, reasons, num, side, meta)
    blob = json.dumps(dict(verdict=verdict, reasons=reasons, meta=meta, side=side, **num), default=str)
    blob = blob.replace("Infinity", "null").replace("-null", "null").replace("NaN", "null")
    open(a.json_out, "w").write(json.dumps(json.loads(blob), indent=2))
    open(a.md_out, "w").write(md)
    print(md)
    return EXIT[verdict]


# ----------------------------------------------------------------------------- calibration
def cmd_calibrate(a):
    """Monte-Carlo the decision rule: how often does it ship a truly equal patch, and how
    often does it ship a truly +X Elo patch?  Honest error rates, not assumed ones."""
    import random
    rng = random.Random(a.seed)
    good = dict(perft_ok=True, test_nodes=[1] * 5, base_nodes=[1] * 5, test_nps=[1.0] * 5, base_nps=[1.0] * 5)

    def play(n, p_win, p_loss):
        w = l = 0
        for _ in range(n):
            u = rng.random()
            if u < p_win:
                w += 1
            elif u < p_win + p_loss:
                l += 1
        return w, n - w - l, l

    print(f"games/replicate={a.games} replicates=5 draw_rate={a.draw:.0%} trials={a.trials} mode={a.mode}")
    print("true Elo | SHIP    REJECT  INVEST  INCONCL")
    for true_elo in a.elos:
        score = 1 / (1 + 10 ** (-true_elo / 400))
        p_w = score - a.draw / 2
        p_l = 1 - a.draw - p_w
        cnt = dict(SHIP=0, REJECT=0, INVESTIGATE=0, INCONCLUSIVE=0)
        for _ in range(a.trials):
            reps = []
            for i in range(5):
                w, d, l = play(a.games, p_w, p_l)
                reps.append(dict(replicate=i, w=w, d=d, l=l, cand_faults=[], opp_faults=[]))
            v, _, _ = decide(good, reps, a.mode, a.margin)
            cnt[v] += 1
        t = a.trials
        print(f"{true_elo:+8.0f} | " + "  ".join(f"{cnt[k]/t*100:6.1f}%" for k in
                                                  ("SHIP", "REJECT", "INVESTIGATE", "INCONCLUSIVE")))
    return 0


# ----------------------------------------------------------------------------- self-test
def cmd_selftest(_a=None):
    def close(x, y, t):
        assert abs(x - y) < t, (x, y)

    close(elo_of(0.5), 0.0, 1e-9)
    close(elo_of(0.64), 100.0, 3.0)                      # 64% ~ +100 Elo
    s = stats(100, 100, 100)
    close(s["score"], 0.5, 1e-12)
    close(s["los"], 0.5, 1e-9)
    close(stats(60, 0, 40)["los"], 0.977, 0.005)         # (60-40)/sqrt(100)=2 sigma
    close(chi2_sf(9.4877, 4), 0.05, 0.002)               # chi2 table, df=4
    close(chi2_sf(13.2767, 4), 0.01, 0.001)
    close(chi2_sf(3.8415, 1), 0.05, 0.002)
    ci = stats(500, 500, 500)
    assert ci["lo"] < 0 < ci["hi"] and ci["se_elo"] > 0

    good = dict(perft_ok=True, test_nodes=[100] * 5, base_nodes=[100] * 5,
                test_nps=[1.0e6] * 5, base_nps=[1.0e6] * 5)

    def rep(i, w, d, l):
        return dict(replicate=i, w=w, d=d, l=l, cand_faults=[], opp_faults=[])

    strong = [rep(i, 120, 80, 38 + i) for i in range(5)]           # clearly better everywhere
    v, _, _ = decide(good, strong)
    assert v == "SHIP", v
    equal = [rep(i, *t) for i, t in enumerate([(85, 70, 83), (80, 72, 86), (88, 66, 84),
                                               (81, 70, 87), (86, 69, 83)])]  # A/A: must NOT ship
    v, _, _ = decide(good, equal)
    assert v == "INCONCLUSIVE", v
    one_bad = strong[:4] + [rep(4, 40, 40, 158)]                   # one replicate collapses
    v, why, _ = decide(good, one_bad)
    assert v == "REJECT", (v, why)
    v, _, _ = decide(good, strong[:3])                             # only 3 of 5 replicates
    assert v == "INCONCLUSIVE", v
    v, _, _ = decide(dict(good, perft_ok=False), strong)
    assert v == "REJECT"
    v, _, _ = decide(dict(good, test_nodes=[1, 2, 1, 1, 1]), strong)
    assert v == "REJECT"
    v, _, _ = decide(dict(good, test_nps=[8e5] * 5), strong)       # -20% NPS
    assert v == "REJECT"
    v, _, _ = decide(dict(good, test_nps=[9.3e5] * 5), strong)
    assert v == "INVESTIGATE"
    v, _, _ = decide(dict(good, test_nodes=[99] * 5), strong, expect_node_identical=True)
    assert v == "REJECT", v
    faulty = [dict(strong[0], cand_faults=["3: time forfeit"])] + strong[1:]
    v, _, _ = decide(good, faulty)
    assert v == "REJECT"
    split = [rep(0, 150, 60, 28), rep(1, 28, 60, 150)] + [rep(i, 90, 60, 88) for i in (2, 3, 4)]
    v, _, _ = decide(good, split)
    assert v in ("REJECT", "INVESTIGATE"), v                       # unstable replicates
    v, _, _ = decide(good, equal, mode="noninferior", margin=30)
    assert v == "SHIP", v
    v, _, _ = decide(good, [rep(i, 70, 70, 98) for i in range(5)], mode="noninferior", margin=2)
    assert v in ("INCONCLUSIVE", "REJECT"), v

    pgn = ('[Event "x"]\n[Round "1"]\n[White "test"]\n[Black "base"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n\n'
           '[Event "x"]\n[Round "1"]\n[White "base"]\n[Black "test"]\n[Result "1/2-1/2"]\n\n1. d4 d5 1/2-1/2\n\n'
           '[Event "x"]\n[Round "2"]\n[White "test"]\n[Black "base"]\n[Result "0-1"]\n'
           '[Termination "time forfeit"]\n\n1. e4 e5 0-1\n')
    p = "/tmp/_ship_gate_selftest.pgn"
    open(p, "w").write(pgn)
    r = parse_pgn(p)
    assert (r["w"], r["d"], r["l"]) == (1, 1, 1) and len(r["cand_faults"]) == 1, r
    os.remove(p)
    print("ship_gate selftest: all checks passed")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("probe")
    p.add_argument("--test", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--depth", type=int, default=11)
    p.add_argument("--perft-ok", type=lambda s: s.lower() == "true", default=False)
    p.add_argument("--rustflags", default="")
    p.add_argument("--out", required=True)
    p.set_defaults(f=cmd_probe)
    p = sp.add_parser("parse")
    p.add_argument("pgn")
    p.add_argument("--replicate", type=int, required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(f=cmd_parse)
    p = sp.add_parser("verdict")
    p.add_argument("--side", required=True)
    p.add_argument("--dir", required=True)
    p.add_argument("--mode", choices=["improve", "noninferior"], default="improve")
    p.add_argument("--margin", type=float, default=8.0)
    p.add_argument("--replicates", type=int, default=5)
    p.add_argument("--min-games", type=int, default=100)
    p.add_argument("--expect-node-identical", action="store_true")
    p.add_argument("--test", default="?")
    p.add_argument("--base", default="?")
    p.add_argument("--tc", default="?")
    p.add_argument("--json-out", default="verdict.json")
    p.add_argument("--md-out", default="verdict.md")
    p.set_defaults(f=cmd_verdict)
    p = sp.add_parser("calibrate")
    p.add_argument("--games", type=int, default=238, help="games per replicate")
    p.add_argument("--draw", type=float, default=0.40)
    p.add_argument("--trials", type=int, default=2000)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--mode", choices=["improve", "noninferior"], default="improve")
    p.add_argument("--margin", type=float, default=8.0)
    p.add_argument("--elos", type=float, nargs="+", default=[-10, -5, 0, 5, 10, 15, 20, 30, 50])
    p.set_defaults(f=cmd_calibrate)
    p = sp.add_parser("selftest")
    p.set_defaults(f=cmd_selftest)
    a = ap.parse_args()
    sys.exit(a.f(a))


if __name__ == "__main__":
    main()
