import subprocess,sys,re
def run(binp,fen,depth):
    p=subprocess.Popen([binp],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
    p.stdin.write(f"uci\nisready\nposition fen {fen}\ngo depth {depth}\n"); p.stdin.flush()
    last=None
    for line in p.stdout:
        if line.startswith("info depth"): last=line
        if line.startswith("bestmove"): bm=line.split()[1]; break
    p.stdin.write("quit\n"); p.stdin.flush(); p.wait(timeout=5)
    nodes=int(re.search(r"nodes (\d+)",last).group(1)); sc=re.search(r"score (\w+ -?\d+)",last).group(1)
    return nodes,sc,bm
fens=[l.split(';')[0].strip() for l in open('/tmp/book.epd') if l.strip()]
import random; random.seed(7); sample=random.sample(fens,40)
extra=["r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1","8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1","8/5k2/8/8/8/8/1K6/1B6 w - - 0 1","8/8/4k3/8/2p5/8/B2P2K1/8 w - - 0 1"]
A,B=sys.argv[1],sys.argv[2]; same=diff=0
for fen in sample+extra:
    fen = fen if len(fen.split())>=4 else fen
    if len(fen.split())==4: fen+=" 0 1"
    for d in (6,8):
        a=run(A,fen,d); b=run(B,fen,d)
        if a==b: same+=1
        else: diff+=1; print("DIFF",d,fen,a,b)
print(f"identical={same} different={diff} (nodes,score,bestmove at depth 6 and 8)")
