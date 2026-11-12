import json, subprocess, sys, re
from concurrent.futures import ThreadPoolExecutor
fens=json.load(open('/tmp/scale/fens.json'))
def uci(cmd, lines, stop_on):
    p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,env=cmd_env)
    p.stdin.write(lines); p.stdin.flush(); out=[]
    for l in p.stdout:
        out.append(l)
        if stop_on(l): break
    p.stdin.write('quit\n'); p.stdin.flush(); p.wait(); return out
import os
cmd_env=dict(os.environ, CRE_NNUE_FILE='/tmp/sd1/net.bin')
# engine eval for all
inp='uci\n'+''.join(f'position fen {f}\neval\n' for f in fens)+'isready\n'
p=subprocess.Popen(['/tmp/sd_engine'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,env=cmd_env)
out,_=p.communicate(inp+'quit\n')
ev=[(int(a),int(b)) for a,b in re.findall(r'eval_hce (-?\d+) eval_nnue (-?\d+)',out)]
print(len(ev),'engine evals')
def sf(f):
    p=subprocess.Popen(['/tmp/sf/stockfish/stockfish-linux-x86-64-universal'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    p.stdin.write(f'setoption name Threads value 1\nsetoption name Hash value 16\nposition fen {f}\ngo depth 12\n'); p.stdin.flush()
    last=None
    for l in p.stdout:
        m=re.search(r'score (cp|mate) (-?\d+)',l)
        if m and ' depth ' in l: last=(m.group(1),int(m.group(2)))
        if l.startswith('bestmove'): break
    p.stdin.write('quit\n'); p.stdin.flush(); p.wait()
    if last is None: return None
    return last[1] if last[0]=='cp' else (30000 if last[1]>0 else -30000)
with ThreadPoolExecutor(4) as ex: labs=list(ex.map(sf,fens))
json.dump({'fens':fens,'ev':ev,'sf':labs},open('/tmp/scale/data.json','w'))
print('done')
