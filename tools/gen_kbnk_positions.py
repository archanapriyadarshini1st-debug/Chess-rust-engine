import random
random.seed(20261111)
def kattacks(sq):
    f,r=sq%8,sq//8
    return {(f+df)+(r+dr)*8 for df in(-1,0,1) for dr in(-1,0,1) if (df or dr) and 0<=f+df<8 and 0<=r+dr<8}
def nattacks(sq):
    f,r=sq%8,sq//8
    return {(f+a)+(r+b)*8 for a,b in[(1,2),(2,1),(-1,2),(-2,1),(1,-2),(2,-1),(-1,-2),(-2,-1)] if 0<=f+a<8 and 0<=r+b<8}
def battacks(sq,occ):
    f,r=sq%8,sq//8; out=set()
    for df,dr in[(1,1),(1,-1),(-1,1),(-1,-1)]:
        x,y=f+df,r+dr
        while 0<=x<8 and 0<=y<8:
            s=x+y*8; out.add(s)
            if s in occ: break
            x+=df;y+=dr
    return out
def fen(wk,b,n,bk):
    bd=['1']*64
    bd[wk]='K';bd[b]='B';bd[n]='N';bd[bk]='k'
    rows=[]
    for r in range(7,-1,-1):
        row='';c=0
        for f in range(8):
            ch=bd[f+r*8]
            if ch=='1': c+=1
            else:
                if c: row+=str(c);c=0
                row+=ch
        if c: row+=str(c)
        rows.append(row)
    return '/'.join(rows)+' w - - 0 1'
out=[]
while len(out)<50:
    wk,b,n,bk=random.sample(range(64),4)
    if bk in kattacks(wk): continue
    occ={wk,b,n,bk}
    if bk in nattacks(n) or bk in battacks(b,occ): continue
    out.append(fen(wk,b,n,bk))
open("kbnk.epd","w").write('\n'.join(out)+'\n')
print(out[:2])
