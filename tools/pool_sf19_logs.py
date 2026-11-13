"""Pool SF19-ladder replica logs (GitHub Actions job logs saved as log_<name>.txt).
Parses the fastchess `Games: n, Wins, Losses, Draws` lines; the 2nd match in each log is the UCI_Elo 3000 level.
Elo = logistic from pooled score, CI = trinomial normal 95%. Agent Z9 (EXP-Z9-1). No credentials in this file.
"""
import re,math
def elo(x): return -400*math.log10(1/x-1)
def st(w,d,l):
    n=w+d+l; s=(w+.5*d)/n; var=(w*(1-s)**2+d*(.5-s)**2+l*s**2)/n; se=math.sqrt(var/n)
    return n,s,elo(s),elo(max(.001,s-1.96*se)),elo(min(.999,s+1.96*se)),se
tot={}
for grp,names in [('cand',['net-r1','net-r2','net-r3','net-r4','net-r5']),('base',['base-r1','base-r2','base-r3'])]:
    W=D=L=0; per=[]
    for nm in names:
        t=open(f'log_{nm}.txt').read()
        g=re.findall(r'Games: (\d+), Wins: (\d+), Losses: (\d+), Draws: (\d+)',t)
        _,w,l,d=map(int,g[1]); per.append((w,d,l,round(100*(w+d/2)/(w+d+l),1))); W+=w;D+=d;L+=l
    n,s,e,lo,hi,se=st(W,D,L)
    print(grp,'vs UCI_Elo 3000 per-replica (W,D,L,score%)',per)
    print(f'  pooled {W}-{D}-{L} n={n} score={100*s:.1f}% Elo={e:+.0f} [{lo:+.0f},{hi:+.0f}]')
    # chi2 heterogeneity on scores
    sc=[(w+d/2)/(w+d+l) for w,d,l,_ in per]; m=sum(sc)/len(sc)
    chi=sum((x-m)**2/(0.0042) for x in sc) # approx var of 60-game score ~ 0.0042
    print('  approx chi2 df',len(sc)-1,round(chi,2))
