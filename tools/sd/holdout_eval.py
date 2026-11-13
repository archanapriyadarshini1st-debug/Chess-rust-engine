#!/usr/bin/env python3
"""Game-disjoint holdout loss of an exported CRN1 net (the number train.py's own val loss cannot give,
because train.py splits by position hash and neighbouring positions of one game leak across it).
Also prints the loss of the trivial constant predictor so the number has a scale."""
import argparse, importlib.util, json, sys
import numpy as np
import torch

ap = argparse.ArgumentParser()
ap.add_argument("--net", required=True)
ap.add_argument("--holdout", required=True)
ap.add_argument("--lam", type=float, default=0.75)
ap.add_argument("--trainer", default="tools/nnue/train.py")
ap.add_argument("--json", default=None)
a = ap.parse_args()
spec = importlib.util.spec_from_file_location("trainer", a.trainer)
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
recs = np.fromfile(a.holdout, dtype=T.REC)
net = T.Net()
T.load_net(net, a.net)
net.eval()
A, B, K, S, W = T.decode(recs)
tot = const = 0.0
with torch.no_grad():
    t_all = a.lam * torch.sigmoid(torch.from_numpy(S) / T.SCALE) + (1 - a.lam) * torch.from_numpy(W)
    mean = t_all.mean()
    for i in range(0, len(recs), 65536):
        sl = slice(i, i + 65536)
        o = net(torch.from_numpy(A[sl]).long(), torch.from_numpy(B[sl]).long(), torch.from_numpy(K[sl]))
        tot += ((torch.sigmoid(o) - t_all[sl]) ** 2).sum().item()
        const += ((mean - t_all[sl]) ** 2).sum().item()
res = {"holdout_positions": len(recs), "game_disjoint_mse": tot / len(recs), "constant_predictor_mse": const / len(recs)}
res["explained_variance"] = 1 - res["game_disjoint_mse"] / res["constant_predictor_mse"]
print(json.dumps(res, indent=1))
if a.json:
    json.dump(res, open(a.json, "w"), indent=1)
