import chess,chess.pgn,chess.engine,json,os
from multiprocessing import Pool
ENG='/tmp/run/main_581b8ee'; NET='/tmp/run/lnet/net.bin'; SF='/tmp/tools/stockfish'
def positions():
    out=[]
    for gi,p in enumerate(['/tmp/run/sf3000_a.pgn','/tmp/run/sf3000_b.pgn']):
        f=open(p); k=0
        while True:
            g=chess.pgn.read_game(f)
            if g is None: break
            k+=1
            rw=g.headers['White']=='Rust'
            nodes=list(g.mainline())
            for target in (30,50):
                for n in (target,target+1):
                    if n<=len(nodes):
                        b=nodes[n-1].board()
                        if b.turn==(chess.WHITE if rw else chess.BLACK) and not b.is_game_over():
                            out.append((gi,k,n,b.fen())); break
    return out
def work(chunk):
    sf=chess.engine.SimpleEngine.popen_uci(SF); sf.configure({'Threads':1,'Hash':64})
    h=chess.engine.SimpleEngine.popen_uci([ENG])
    n=chess.engine.SimpleEngine.popen_uci([ENG],env={**os.environ,'CRE_NNUE_FILE':NET})
    res=[]
    for gi,k,ply,fen in chunk:
        b=chess.Board(fen)
        t=sf.analyse(b,chess.engine.Limit(time=1.5))['score'].pov(b.turn).score(mate_score=10000)
        a=h.analyse(b,chess.engine.Limit(depth=12))['score'].pov(b.turn).score(mate_score=10000)
        c=n.analyse(b,chess.engine.Limit(depth=12))['score'].pov(b.turn).score(mate_score=10000)
        res.append(dict(pgn=gi,game=k,ply=ply,fen=fen,teacher=t,hce=a,nnue=c))
    sf.quit();h.quit();n.quit(); return res
if __name__=='__main__':
    P=positions(); print('positions',len(P),flush=True)
    chunks=[P[i::3] for i in range(3)]
    with Pool(3) as pool: R=sum(pool.map(work,chunks),[])
    json.dump(R,open('/tmp/run/control.json','w')); print('done')
