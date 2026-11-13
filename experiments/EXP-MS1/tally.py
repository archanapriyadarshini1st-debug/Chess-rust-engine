import re,sys,math,glob
def tally(f):
    t=open(f).read(); w=l=d=0
    for g in t.split('[Event')[1:]:
        wn=re.search(r'\[White "(\w)"',g).group(1); r=re.search(r'\[Result "([^"]+)"',g).group(1)
        if r=='1/2-1/2': d+=1
        elif (r=='1-0')==(wn=='A'): w+=1
        elif r in('1-0','0-1'): l+=1
    return w,l,d
def elo(w,l,d):
    n=w+l+d; s=(w+d/2)/n
    if s<=0 or s>=1: return float('nan'),float('nan')
    e=-400*math.log10(1/s-1)
    var=(w*(1-s)**2+l*s**2+d*(0.5-s)**2)/n
    se=math.sqrt(var/n); lo=s-1.96*se; hi=s+1.96*se
    f=lambda x:-400*math.log10(1/x-1) if 0<x<1 else float('nan')
    return e,(f(hi)-f(lo))/2
tot=[0,0,0]
for f in sorted(glob.glob('/tmp/m1/ms1_*.pgn')):
    w,l,d=tally(f); n=w+l+d
    if n==0: continue
    e,ci=elo(w,l,d); print(f.split('/')[-1],f"A-B W-L-D {w}-{l}-{d} n={n} score={(w+d/2)/n:.1%} Elo={e:+.0f}+-{ci:.0f}")
    if 'lb2_r' in f: tot=[tot[0]+w,tot[1]+l,tot[2]+d]
n=sum(tot)
if n:
    e,ci=elo(*tot); print(f"POOLED lb2_r* W-L-D {tot[0]}-{tot[1]}-{tot[2]} n={n} score={(tot[0]+tot[2]/2)/n:.1%} Elo={e:+.0f}+-{ci:.0f}")
