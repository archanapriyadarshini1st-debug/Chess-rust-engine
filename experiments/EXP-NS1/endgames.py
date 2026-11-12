import subprocess, re, os
P=[("KBvK draw","8/8/8/4k3/8/8/3KB3/8 w - - 0 1"),
("KNvK draw","8/8/8/4k3/8/8/3KN3/8 w - - 0 1"),
("KBNK win","8/8/4k3/8/8/3K4/3B4/3N4 w - - 0 1"),
("wrong-bishop rook pawn draw","7k/8/7P/8/8/8/8/K4B2 b - - 0 1"),
("KRvK win","8/8/8/5k2/8/8/3KR3/8 w - - 0 1"),
("KRPvKR Philidor-ish draw","3r4/8/3k4/3P4/3K4/8/8/4R3 b - - 0 1"),
("KPK opposition draw","8/8/8/3k4/8/3K4/3P4/8 w - - 0 1"),
("KPK win","8/8/8/8/3k4/8/3PK3/8 w - - 0 1"),
("same-colour bishops pawn up","8/5k2/4b3/8/3PB3/4K3/8/8 w - - 0 1"),
("KQvKP 7th rook-pawn draw-ish","8/8/8/8/8/2K1k3/p7/1Q6 w - - 0 1"),
("KNNvK draw","8/8/8/4k3/8/8/3KNN2/8 w - - 0 1"),
("fortress-ish KRvKB","8/8/8/4k3/4b3/8/3KR3/8 w - - 0 1"),
("50-move clock 98, big edge","8/8/8/5k2/8/8/3KR3/8 w - - 98 80"),
]
def run(cmd,env,setup,fen,go):
    p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,env=env)
    p.stdin.write(setup+f'position fen {fen}\n{go}\n'); p.stdin.flush(); last=None
    for l in p.stdout:
        m=re.search(r'score (cp|mate) (-?\d+)',l)
        if m: last=f'{m.group(1)}{int(m.group(2)):+d}'
        if l.startswith('bestmove'): break
    p.stdin.write('quit\n'); p.stdin.flush(); p.wait(); return last
net=dict(os.environ,CRE_NNUE_FILE='/tmp/sd1/net.bin')
print(f'{"position":34} {"NET d14":>9} {"HCE d14":>9} {"SF19 d20":>9}')
import chess
for name,f in P:
    if not chess.Board(f).is_valid(): print('SKIP invalid',name); continue
    try: a=run(['/tmp/sd_engine'],net,'uci\n',f,'go depth 14')
    except Exception as e: a='CRASH'
    try: b=run(['/tmp/sd_engine'],net,'uci\nsetoption name UseNNUE value false\n',f,'go depth 14')
    except Exception as e: b='CRASH'
    c=run(['/tmp/sf/stockfish/stockfish-linux-x86-64-universal'],os.environ,'',f,'go depth 20')
    print(f'{name:34} {str(a):>9} {str(b):>9} {str(c):>9}')
