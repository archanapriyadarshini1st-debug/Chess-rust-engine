#!/bin/bash
# usage: run.sh NAME TESTBIN "TESTOPTS" ROUNDS SEED   (BASE = /tmp/bins/main)
FC=$(cat /tmp/fcpath)
NAME=$1; BIN=$2; OPTS=$3; ROUNDS=$4; SEED=$5
$FC -engine cmd=$BIN name=test option.Hash=16 option.Threads=1 $OPTS \
    -engine cmd=/tmp/bins/main name=base option.Hash=16 option.Threads=1 \
    -each tc=inf nodes=25000 -rounds $ROUNDS -games 2 -repeat -concurrency 3 \
    -openings file=/tmp/book.epd format=epd order=random -srand $SEED \
    -draw movenumber=40 movecount=8 score=10 -resign movecount=4 score=800 twosided=true \
    -maxmoves 300 -pgnout file=/tmp/lab/out/$NAME.s$SEED.pgn 2>&1 \
  | grep -E "^Games:|Illegal|illegal|disconnect|stall|crash|loses on time" > /tmp/lab/out/$NAME.s$SEED.log
echo "$NAME seed=$SEED $(grep '^Games:' /tmp/lab/out/$NAME.s$SEED.log | tail -1)" >> /tmp/lab/results.txt
