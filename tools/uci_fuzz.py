#!/usr/bin/env python3
"""UCI robustness fuzz (Agent RV). usage: uci_fuzz.py ENGINE SEED N  (needs python-chess)
Randomised go movetime/wtime/depth/infinite+stop, ucinewgame mid-game, Hash changes, FEN jumps.
Checks: crash, hang, illegal bestmove, clock overrun. Exit text lists problems. Not a strength test.
"""
import subprocess,random,time,sys,chess,threading,queue
BIN=sys.argv[1]; SEED=int(sys.argv[2]); N=int(sys.argv[3])
random.seed(SEED)
p=subprocess.Popen([BIN],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
q=queue.Queue()
threading.Thread(target=lambda:[q.put(l.strip()) for l in p.stdout],daemon=True).start()
err=[]
threading.Thread(target=lambda:[err.append(l) for l in p.stderr],daemon=True).start()
def w(x): p.stdin.write(x+"\n"); p.stdin.flush()
def best(timeout):
    t0=time.time()
    while time.time()-t0<timeout:
        try: l=q.get(timeout=0.05)
        except queue.Empty:
            if p.poll() is not None: return 'CRASH',time.time()-t0
            continue
        if l.startswith('bestmove'): return l.split()[1],time.time()-t0
    return 'HANG',timeout
def sync():
    w("isready")
    while True:
        l=q.get(timeout=10)
        if l=='readyok': return
w("uci"); sync()
stats=dict(go=0,illegal=0,hang=0,crash=0,maxover=0.0,stops=0)
problems=[]
b=chess.Board(); moves=[]; base=chess.STARTING_FEN
w("ucinewgame"); sync()
for i in range(N):
    r=random.random()
    if r<0.06:   # new game
        w("ucinewgame"); sync(); b=chess.Board(); moves=[]; base=chess.STARTING_FEN
    elif r<0.10: # hash change
        w("setoption name Hash value %d"%random.choice([1,4,16,64])); sync()
    if b.is_game_over() or len(moves)>160:
        w("ucinewgame"); sync(); b=chess.Board(); moves=[]; base=chess.STARTING_FEN
    if random.random()<0.08:  # position jump with fen (no ucinewgame)
        b=chess.Board(); 
        for _ in range(random.randint(0,30)):
            ms=list(b.legal_moves)
            if not ms: break
            b.push(random.choice(ms))
        if b.is_game_over(): b=chess.Board()
        base=b.fen(); moves=[]
    w("position fen "+base+(" moves "+" ".join(moves) if moves else ""))
    if False: pass
    mode=random.random()
    if mode<0.35:
        w("go movetime %d"%random.choice([20,50,100])); lim=1.5
    elif mode<0.7:
        t=random.choice([300,1000,3000]); w("go wtime %d btime %d winc 50 binc 50"%(t,t)); lim=t/1000*0.5+0.5
    elif mode<0.85:
        w("go depth %d"%random.choice([3,6,8])); lim=20
    else:
        w("go infinite"); time.sleep(random.choice([0.01,0.05,0.2])); w("stop"); stats['stops']+=1; lim=2
    bm,dt=best(lim+1.0); stats['go']+=1
    if bm=='CRASH': stats['crash']+=1; problems.append(('crash',b.fen())); break
    if bm=='HANG': stats['hang']+=1; problems.append(('hang',b.fen(),mode)); w("stop"); best(3); continue
    mv=chess.Move.from_uci(bm) if bm not in('0000','(none)') else None
    if mv is None or mv not in b.legal_moves:
        stats['illegal']+=1; problems.append(('illegal',bm,b.fen())); w("ucinewgame"); sync(); b=chess.Board(); moves=[]; base=chess.STARTING_FEN; continue
    stats['maxover']=max(stats['maxover'],dt-lim)
    b.push(mv)
    moves.append(bm)
w("quit")
print(SEED,stats,'stderr_lines',len(err),problems[:3])
