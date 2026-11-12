import chess, chess.pgn, random, sys, subprocess, json, os
from concurrent.futures import ThreadPoolExecutor
random.seed(5)
pg=open('/tmp/h1/games.pgn'); fens=[]
while True:
    g=chess.pgn.read_game(pg)
    if g is None: break
    b=g.board(); n=0
    for mv in g.mainline_moves():
        # quiet-ish sample: skip checks / captures into the position
        cap=b.is_capture(mv); b.push(mv); n+=1
        if 14<=n<=140 and not cap and not b.is_check() and random.random()<0.22:
            fens.append(b.fen())
fens=sorted(set(fens)); random.shuffle(fens); fens=fens[:1400]
print(len(fens),'positions')
json.dump(fens,open('/tmp/scale/fens.json','w'))
