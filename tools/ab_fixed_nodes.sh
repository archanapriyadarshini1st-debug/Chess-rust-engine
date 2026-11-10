#!/bin/bash
# usage: ab.sh TESTBIN BASEBIN ROUNDS NODES [elo0 elo1]  -> fixed-node SPRT/A-B, 2 games/round (colours swapped)
T=$1; B=$2; R=${3:-250}; N=${4:-25000}; E0=${5:--5}; E1=${6:-5}
OUT=/tmp/out_$(basename $T)_vs_$(basename $B); mkdir -p $OUT
/tmp/fastchess \
 -engine cmd=$T name=test option.Hash=16 option.Threads=1 \
 -engine cmd=$B name=base option.Hash=16 option.Threads=1 \
 -each nodes=$N \
 -rounds $R -games 2 -repeat -concurrency 4 -srand 7 \
 -openings file=/tmp/cre/tools/openings_book.epd format=epd order=random \
 -sprt elo0=$E0 elo1=$E1 alpha=0.05 beta=0.05 model=logistic \
 -draw movenumber=40 movecount=8 score=10 -resign movecount=4 score=800 twosided=true -maxmoves 300 \
 -ratinginterval 100 -pgnout file=$OUT/g.pgn 2>&1 | grep -E "Elo:|LLR|Games:|SPRT|Finished|rror" | tail -6
