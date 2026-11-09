#!/usr/bin/env python3
"""Train a (768→64)×2→1 SCReLU net and emit nets/v1.bin (CRN1 i16).

Input lines:  fen | cp_from_stm | wdl_from_stm
wdl is 0/0.5/1. Target is a blend of search score and game result.
"""
from __future__ import annotations

import argparse
import os
import random
import struct
import sys

import numpy as np

H = 64
F = 768
QA = 255.0
QB = 64.0
SCALE = 400.0
MAGIC = b"CRN1"


def feat_index(stm_white: bool, piece: str, sq: int) -> int:
    # piece fen char
    white = piece.isupper()
    ty = "PNBRQKpnbrqk".index(piece) % 6
    if not stm_white:
        sq ^= 56
    side = 0 if (white == stm_white) else 6
    return (side + ty) * 64 + sq


def parse_fen_pieces_correct(fen: str):
    board, stm, *_ = fen.split()
    stm_w = stm == "w"
    us, them = [], []
    rank = 7
    file = 0
    for c in board:
        if c == "/":
            rank -= 1
            file = 0
            continue
        if c.isdigit():
            file += int(c)
            continue
        sq = rank * 8 + file
        us.append(feat_index(stm_w, c, sq))
        them.append(feat_index(not stm_w, c, sq))
        file += 1
    return us, them


def load_data(paths, cap=None, lam=1.0):
    xs = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 2:
                    continue
                fen, cp_s = parts[0], parts[1]
                wdl = float(parts[2]) if len(parts) > 2 else 0.5
                try:
                    cp = float(cp_s)
                except ValueError:
                    continue
                try:
                    us, them = parse_fen_pieces_correct(fen)
                except Exception:
                    continue
                if not us:
                    continue
                # blend search + result in wdl space. lambda_cp=1 is pure eval
                # (needed so KQK does not collapse toward 0.5 WDL).
                t = lam * np.tanh(cp / SCALE) + (1.0 - lam) * (2.0 * wdl - 1.0)
                xs.append((us, them, float(t)))
                if cap and len(xs) >= cap:
                    return xs
    return xs


def screlu(x):
    y = np.clip(x, 0.0, 1.0)
    return y * y


def dscrelu(x):
    # d/dx (clip(x,0,1)^2)
    g = np.zeros_like(x)
    m = (x > 0) & (x < 1)
    g[m] = 2.0 * x[m]
    return g


def train(data, epochs=8, batch=1024, lr=0.001):
    rng = np.random.default_rng(0)
    w1 = rng.normal(0, 0.1 / np.sqrt(F), size=(H, F)).astype(np.float64)
    b1 = np.zeros(H, dtype=np.float64)
    w2 = rng.normal(0, 0.1 / np.sqrt(2 * H), size=(2 * H,)).astype(np.float64)
    b2 = 0.0

    # adam
    m = [np.zeros_like(w1), np.zeros_like(b1), np.zeros_like(w2), 0.0]
    v = [np.zeros_like(w1), np.zeros_like(b1), np.zeros_like(w2), 0.0]
    tstep = 0
    beta1, beta2, eps = 0.9, 0.999, 1e-8

    def adam(i, g, param, is_scalar=False):
        nonlocal tstep
        m[i] = beta1 * m[i] + (1 - beta1) * g
        v[i] = beta2 * v[i] + (1 - beta2) * (g * g)
        mh = m[i] / (1 - beta1 ** tstep)
        vh = v[i] / (1 - beta2 ** tstep)
        return param - lr * mh / (np.sqrt(vh) + eps)

    n = len(data)
    for ep in range(epochs):
        rng.shuffle(data)
        total = 0.0
        seen = 0
        for i0 in range(0, n, batch):
            chunk = data[i0 : i0 + batch]
            if not chunk:
                continue
            tstep += 1
            B = len(chunk)
            gw1 = np.zeros_like(w1)
            gb1 = np.zeros_like(b1)
            gw2 = np.zeros_like(w2)
            gb2 = 0.0
            loss = 0.0
            for us, them, target in chunk:
                acc_u = b1.copy()
                acc_t = b1.copy()
                for f in us:
                    acc_u += w1[:, f]
                for f in them:
                    acc_t += w1[:, f]
                hu = screlu(acc_u)
                ht = screlu(acc_t)
                h = np.concatenate([hu, ht])
                pred = float(h.dot(w2) + b2)
                # tanh space
                pt = np.tanh(pred)
                err = pt - target
                loss += 0.5 * err * err
                # dL/dpred
                dpred = err * (1 - pt * pt)
                gb2 += dpred
                gw2 += dpred * h
                dh = dpred * w2
                dhu = dh[:H] * dscrelu(acc_u)
                dht = dh[H:] * dscrelu(acc_t)
                gb1 += dhu + dht
                for f in us:
                    gw1[:, f] += dhu
                for f in them:
                    gw1[:, f] += dht
            inv = 1.0 / B
            w1 = adam(0, gw1 * inv, w1)
            b1 = adam(1, gb1 * inv, b1)
            w2 = adam(2, gw2 * inv, w2)
            b2 = adam(3, gb2 * inv, b2, True)
            total += loss
            seen += B
        print(f"epoch {ep+1}/{epochs} loss {total/max(seen,1):.5f} n={seen}", flush=True)
    return w1, b1, w2, b2


def quantize(w1, b1, w2, b2) -> bytes:
    w1q = np.clip(np.round(w1 * QA), -32767, 32767).astype(np.int16)
    b1q = np.clip(np.round(b1 * QA), -32767, 32767).astype(np.int16)
    w2q = np.clip(np.round(w2 * QB), -32767, 32767).astype(np.int16)
    b2q = int(np.clip(np.round(b2 * QB), -32767, 32767))
    buf = bytearray()
    buf += MAGIC
    buf += struct.pack("<I", H)
    buf += w1q.tobytes()
    buf += b1q.tobytes()
    buf += w2q.tobytes()
    buf += struct.pack("<h", b2q)
    return bytes(buf)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("data", nargs="+")
    p.add_argument("--out", default="nets/v1.bin")
    p.add_argument("--epochs", type=int, default=6)
    p.add_argument("--batch", type=int, default=512)
    p.add_argument("--lr", type=float, default=0.0008)
    p.add_argument("--cap", type=int, default=0)
    p.add_argument(
        "--lambda-cp",
        type=float,
        default=1.0,
        help="1=pure eval tanh(cp/400), 0=pure WDL. Default 1 so material survives.",
    )
    args = p.parse_args()
    cap = args.cap or None
    data = load_data(args.data, cap, lam=args.lambda_cp)
    print(f"loaded {len(data)} positions", flush=True)
    if len(data) < 100:
        print("not enough data", file=sys.stderr)
        return 2
    w1, b1, w2, b2 = train(data, epochs=args.epochs, batch=args.batch, lr=args.lr)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    blob = quantize(w1, b1, w2, b2)
    with open(args.out, "wb") as f:
        f.write(blob)
    print(f"wrote {args.out} ({len(blob)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
