import json,statistics as st,math,random
R=json.load(open('/tmp/run/control.json')); n=len(R)
clip=lambda x:max(-600,min(600,x))
T=[clip(r['teacher']) for r in R]
def corr(a,b):
    ma,mb=st.mean(a),st.mean(b); 
    return sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))
def stats(key,idx=None):
    E=[clip(r[key]) for r in R]
    sub=[i for i in range(n) if abs(T[i])>=100]
    sign=sum(1 for i in sub if (E[i]>0)==(T[i]>0))/len(sub)
    return corr(E,T),st.mean(E)-st.mean(T),sign,len(sub)
random.seed(1)
def boot(key,B=2000):
    d=[]
    for _ in range(B):
        idx=[random.randrange(n) for _ in range(n)]
        E=[clip(R[i][key]) for i in idx]; Tt=[T[i] for i in idx]
        d.append(corr(E,Tt))
    d.sort(); return d[int(.025*B)],d[int(.975*B)]
print('n positions',n,' teacher median %+d'%st.median(T),' |teacher|>=100:',sum(abs(t)>=100 for t in T))
for k in ('hce','nnue'):
    c,bias,sign,m=stats(k); lo,hi=boot(k)
    print(f"{k:5s} corr {c:.3f} [{lo:.3f},{hi:.3f}]  mean bias vs teacher {bias:+.0f}cp  sign acc on |teacher|>=100: {sign:.1%} (n={m})  median {st.median(clip(r[k]) for r in R):+.0f}")
# paired bootstrap: corr(nnue)-corr(hce)
d=[]
for _ in range(2000):
    idx=[random.randrange(n) for _ in range(n)]
    Tt=[T[i] for i in idx]
    d.append(corr([clip(R[i]['nnue']) for i in idx],Tt)-corr([clip(R[i]['hce']) for i in idx],Tt))
d.sort(); print('paired corr diff nnue-hce: %.3f [%.3f,%.3f]'%(st.mean(d),d[50],d[1950]))
# split by pgn replicate for consistency
for g in (0,1):
    S=[r for r in R if r['pgn']==g]; Tt=[clip(r['teacher']) for r in S]
    print('replicate',g,'n',len(S),'corr hce %.3f nnue %.3f'%(corr([clip(r['hce']) for r in S],Tt),corr([clip(r['nnue']) for r in S],Tt)))
