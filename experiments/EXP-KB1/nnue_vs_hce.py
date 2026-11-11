import json,re,subprocess,statistics as st,os,sys,chess,chess.engine
recs=[json.loads(l) for l in open('/tmp/run/blindspots_a.jsonl')][1:]
ENG='/tmp/run/main_581b8ee'; NET='/tmp/run/lnet/net.bin'
def static(fen,env):
    o=subprocess.run([ENG],input=f"position fen {fen}\neval\nquit\n",capture_output=True,text=True,env={**os.environ,**env}).stdout
    h=int(re.search(r'eval_hce (-?\d+)',o).group(1)); n=re.search(r'eval_nnue (-?\d+|none)',o).group(1)
    return h,(None if n=='none' else int(n))
rows=[]
for r in recs:
    h,n=static(r['fen'],{'CRE_NNUE_FILE':NET})
    rows.append((r['teacher_cp'],h,n,r))
print('net loaded:',all(x[2] is not None for x in rows))
# static: HCE and NNUE both side-to-move POV (= ours). teacher_cp also ours POV.
for name,idx in (('HCE static',1),('NNUE static',2)):
    v=[x[idx] for x in rows]; t=[x[0] for x in rows]
    over=[a-b for a,b in zip(v,t)]
    print(f"{name}: median {st.median(v):+.0f}  median overrate vs teacher {st.median(over):+.0f}  overrate>=100: {sum(o>=100 for o in over)}/{len(rows)}  sign agrees (both<0): {sum(1 for a in v if a<0)}/{len(rows)}")
# search at depth 14 with the net enabled
def search(fen,env):
    e=chess.engine.SimpleEngine.popen_uci([ENG],env={**os.environ,**env})
    b=chess.Board(fen); i=e.analyse(b,chess.engine.Limit(depth=14)); e.quit()
    return i['score'].pov(b.turn).score(mate_score=10000), i['pv'][0].uci()
res=[]
for t,h,n,r in rows:
    s,m=search(r['fen'],{'CRE_NNUE_FILE':NET})
    res.append((t,s,m,r))
ov=[s-t for t,s,m,r in res]
print(f"NNUE depth-14 search: median {st.median(s for t,s,m,r in res):+.0f}  median overrate {st.median(ov):+.0f}  overrate>=100: {sum(o>=100 for o in ov)}/{len(res)}  neg: {sum(1 for t,s,m,r in res if s<0)}/{len(res)}")
print('NNUE move in teacher top3:',sum(1 for t,s,m,r in res if m in [x['move'] for x in r['teacher_multipv']]),'/',len(res),' (HCE was',sum(r['ours_move_in_teacher_top'] for r in recs),')')
print('HCE depth14: median',st.median(r['ours_search_cp'] for r in recs))
