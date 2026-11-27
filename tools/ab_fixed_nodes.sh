#!/bin/bash
# env: FASTCHESS=path/to/fastchess BOOK=path/to/openings_book.epd (defaults: fastchess on PATH, tools/openings_book.epd)
# usage: ab.sh TEST_BIN BASE_BIN SEED ROUNDS NODES [test_opts...]  -> prints "W L D" from TEST's point of view
T=$1; B=$2; SEED=$3; R=$4; N=$5; shift 5
OPTS=""; for o in "$@"; do OPTS="$OPTS option.$o"; done
"${FASTCHESS:-fastchess}" -engine cmd=$T name=test option.Hash=16 option.Threads=1 $OPTS -engine cmd=$B name=base option.Hash=16 option.Threads=1 \
 -each tc=inf nodes=$N -rounds $R -games 2 -repeat -concurrency 4 -openings file="${BOOK:-tools/openings_book.epd}" format=epd order=random -srand $SEED \
 -draw movenumber=40 movecount=8 score=10 -resign movecount=4 score=800 twosided=true -maxmoves 300 -recover > out_$SEED.log 2>&1
python3 - "$SEED" <<'PY'
import re,sys,math
t=open(f"out_{sys.argv[1]}.log").read()
h=re.findall(r"Results of (\S+) vs (\S+)",t); g=re.findall(r"Games:\s*(\d+),\s*Wins:\s*(\d+),\s*Losses:\s*(\d+),\s*Draws:\s*(\d+)",t)
if not h or not g: print("PARSE FAIL"); sys.exit()
w,l,d=int(g[-1][1]),int(g[-1][2]),int(g[-1][3])
if h[-1][0]!="test": w,l=l,w
n=w+l+d; s=(w+0.5*d)/n
var=(w*(1-s)**2+l*(0-s)**2+d*(0.5-s)**2)/n
se=math.sqrt(var/n)
elo=lambda p: -400*math.log10(1/p-1) if 0<p<1 else float('nan')
print(f"seed {sys.argv[1]} W{w} L{l} D{d} n={n} score={s*100:.2f}% elo={elo(s):+.1f} +-{(elo(s+1.96*se)-elo(s-1.96*se))/2:.1f}")
PY
