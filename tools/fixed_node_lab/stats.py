import re,math,collections
def elo(s): 
    s=min(max(s,1e-6),1-1e-6); return -400*math.log10(1/s-1)
def summ(w,d,l):
    n=w+d+l; s=(w+d/2)/n
    var=(w*(1-s)**2+d*(0.5-s)**2+l*(0-s)**2)/n
    se=math.sqrt(var/n) if n else 1
    lo,hi=elo(s-1.96*se),elo(s+1.96*se)
    los=0.5*(1+math.erf((s-0.5)/(se*math.sqrt(2)))) if se>0 else 0.5
    return n,s,elo(s),lo,hi,los
rows=collections.OrderedDict()
for line in open('/tmp/lab/results.txt'):
    m=re.match(r"(\S+) seed=(\d+) Games: (\d+), Wins: (\d+), Losses: (\d+), Draws: (\d+)",line)
    if m: rows.setdefault(m.group(1),[]).append((int(m.group(2)),int(m.group(4)),int(m.group(6)),int(m.group(5))))
print("| candidate | seed | W-D-L | score | Elo | 95% CI |\n|---|---|---|---|---|---|")
for k,v in rows.items():
    for seed,w,d,l in v:
        n,s,e,lo,hi,los=summ(w,d,l)
        print(f"| {k} | {seed} | {w}-{d}-{l} | {100*s:.1f}% | {e:+.0f} | [{lo:+.0f}, {hi:+.0f}] |")
    if len([1 for x in v if x[0]>=200])>=2:
        st=[x for x in v if x[0]>=200]
        W=sum(x[1] for x in st);D=sum(x[2] for x in st);L=sum(x[3] for x in st)
        n,s,e,lo,hi,los=summ(W,D,L)
        pos=sum(1 for x in st if x[1]+x[2]/2>x[2]/2+x[3]+ (x[1]+x[2]+x[3])/2 - (x[2]/2+x[3]) and False)
        reps=[(x[1]+x[2]/2)/(x[1]+x[2]+x[3]) for x in st]
        print(f"| **{k} pooled s2 ({len(st)} reps)** | | {W}-{D}-{L} | {100*s:.1f}% | {e:+.0f} | [{lo:+.0f}, {hi:+.0f}] LOS {100*los:.0f}% ; per-rep scores {[round(100*r,1) for r in reps]} |")
