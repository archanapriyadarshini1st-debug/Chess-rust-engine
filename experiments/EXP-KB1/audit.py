import chess.pgn,re,sys,statistics as st,collections
f=open(sys.argv[1]); rows=[]
def parse(c):
    m=re.match(r'\s*([+-]?\d+\.\d+|[+-]?M\d+|[+-]?#\d+)/(\d+)\s+([\d.]+)s',c)
    if not m: return None
    s=m.group(1)
    if 'M' in s or '#' in s: v=(1 if not s.startswith('-') else -1)*100.0
    else: v=float(s)
    return v,int(m.group(2)),float(m.group(3))
stats=collections.defaultdict(list); out=[]
mind=[]
while True:
    g=chess.pgn.read_game(f)
    if g is None: break
    rust_white=g.headers['White']=='Rust'; res=g.headers['Result']
    rscore={'1-0':1,'0-1':0,'1/2-1/2':.5}[res]; rscore=rscore if rust_white else 1-rscore
    node=g; ply=0; rs=[]; ss=[]; depthR=[]; depthS=[]; tR=[]
    while node.variations:
        node=node.variations[0]; ply+=1
        p=parse(node.comment); 
        if not p: continue
        white_moved=(ply%2==1)
        rust_moved=(white_moved==rust_white)
        (rs if rust_moved else ss).append((ply,p[0]))
        (depthR if rust_moved else depthS).append(p[1])
        if rust_moved: tR.append(p[2])
    # first ply where SF's own eval >= +1.0 (SF pov) for 3 consecutive SF moves
    first=None
    for i in range(len(ss)-2):
        if all(x[1]>=1.0 for x in ss[i:i+3]): first=ss[i][0]; break
    rust_at=None
    if first is not None:
        near=[x[1] for x in rs if abs(x[0]-first)<=3]
        rust_at=st.mean(near) if near else None
    out.append((rscore,first,rust_at,ply,st.mean(depthR),st.mean(depthS),max(tR)))
    stats['dR'].append(st.mean(depthR)); stats['dS'].append(st.mean(depthS)); stats['maxt'].append(max(tR))
print('mean depth Rust %.1f  SF %.1f ; max single-move time Rust %.2fs'%(st.mean(stats['dR']),st.mean(stats['dS']),max(stats['maxt'])))
L=[o for o in out if o[0]==0]
print('losses',len(L))
fl=[o for o in L if o[1] is not None]
print('losses where SF pov >= +1.00 x3 reached:',len(fl))
print('  at that moment Rust own eval (its pov) mean %.2f median %.2f'%(st.mean([-o[2] if False else o[2] for o in fl if o[2] is not None]),st.median([o[2] for o in fl if o[2] is not None])))
blind=[o for o in fl if o[2] is not None and o[2]>=-0.3]
print('  Rust still evaluated itself >= -0.30 (blind):',len(blind),'of',len(fl))
print('  decisive ply (median) %s ; game len median %s'%(st.median([o[1] for o in fl]),st.median([o[3] for o in L])))
D=[o for o in out if o[0]==.5]; W=[o for o in out if o[0]==1]
print('wins plies med',st.median([o[3] for o in W]) if W else None,'draws',st.median([o[3] for o in D]))

# ---- lag analysis (scale-robust): plies between SF seeing >=+1.0 and Rust itself seeing <=-1.0 (x3)
f=open(sys.argv[1]); lags=[]; never=0; detail=[]
while True:
    g=chess.pgn.read_game(f)
    if g is None: break
    rust_white=g.headers['White']=='Rust'; res=g.headers['Result']
    rscore={'1-0':1,'0-1':0,'1/2-1/2':.5}[res]; rscore=rscore if rust_white else 1-rscore
    if rscore!=0: continue
    node=g; ply=0; rs=[]; ss=[]
    while node.variations:
        node=node.variations[0]; ply+=1
        p=parse(node.comment)
        if not p: continue
        (rs if ((ply%2==1)==rust_white) else ss).append((ply,p[0]))
    sf=next((ss[i][0] for i in range(len(ss)-2) if all(x[1]>=1.0 for x in ss[i:i+3])),None)
    ru=next((rs[i][0] for i in range(len(rs)-2) if all(x[1]<=-1.0 for x in rs[i:i+3])),None)
    if ru is None: never+=1
    else: lags.append(ru-sf)
    detail.append((sf,ru,ply))
print('losses where Rust never itself reached <=-1.0 x3 before the end:',never,'of',len(detail))
print('lag plies (Rust sees -1.0 minus SF sees +1.0): median %s  mean %.1f  n=%d'%(st.median(lags),st.mean(lags),len(lags)))
print('lag>=10 plies:',sum(1 for l in lags if l>=10),'  lag<=2:',sum(1 for l in lags if l<=2))
