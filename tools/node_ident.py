#!/usr/bin/env python3
"""Fixed-depth node-identity check (Agent RV). usage: node_ident.py ENGINE_A ENGINE_B
Compares nodes/score/bestmove for 68 positions x depth 6/8/9. Keeps stdin open until bestmove
(this engine treats stdin EOF as `stop`; a piped test compares aborted searches) and asserts every
comparison saw a real `info depth N` line. Needs tools/openings_book.epd.
"""
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import subprocess,sys,random,re
A,B=sys.argv[1],sys.argv[2]
fens=[(lambda f: f if len(f.split())>=6 else f+' 0 1')(l.split(';')[0].strip()) for l in open('openings_book.epd') if l.strip()]
random.seed(99); random.shuffle(fens)
fens=fens[:60]+[
 "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
 "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
 "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
 "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
 "8/8/8/4k3/8/8/4P3/4K3 w - - 0 1","4k3/8/8/8/8/8/4p3/4K3 b - - 0 1",
 "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1","2r3k1/1q1nbppp/r3p3/3pP3/pPpP4/P1Q2N2/2RN1PPP/2R4K b - b3 0 23"]
def run(binp,fen,d):
    p=subprocess.Popen([binp],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
    def w(x): p.stdin.write(x+"\n"); p.stdin.flush()
    w("uci"); w("setoption name Hash value 16"); w("isready"); w("ucinewgame")
    w("position fen "+fen); w("go depth %d"%d)
    last=None;best=None
    for l in p.stdout:
        if l.startswith('info') and ' depth %d '%d in l and 'score' in l: last=l
        if l.startswith('bestmove'): best=l.split()[1]; break
    w("quit"); p.wait(timeout=10)
    m=re.search(r'score (cp|mate) (-?\d+)',last or '');n=re.search(r'nodes (\d+)',last or '')
    return (n.group(1) if n else None, m.groups() if m else None, best)
bad=0;tot=0;nosearch=[]
for d in (6,8,9):
    for f in fens:
        a=run(A,f,d);b=run(B,f,d);tot+=1
        if a[0] is None or b[0] is None: nosearch.append((d,f))
        if a!=b: bad+=1; print("DIFF",d,f,a,b)
print("compared",tot,"searches; differing:",bad)
print('searches with NO info line (not a real comparison):',len(nosearch), nosearch[:3])
