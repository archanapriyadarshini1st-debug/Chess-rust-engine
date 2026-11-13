#!/bin/bash
# EXP-MS1 h2h: same binary, same net; arm A = NnueGuard G/SPAN, arm B = guard off.
cd /tmp/m1
run(){ # label net gA spanA gB games seed
  export CRE_NNUE_FILE=$2
  /tmp/fastchess \
   -engine cmd=/tmp/cre_ms name=A option.Hash=64 option.Threads=1 option.NnueGuard=$3 option.NnueGuardSpan=$4 \
   -engine cmd=/tmp/cre_ms name=B option.Hash=64 option.Threads=1 option.NnueGuard=$5 \
   -each tc=10+0.1 -rounds $(( $6 / 2 )) -games 2 -repeat -concurrency 3 \
   -openings file=openings_book.epd format=epd order=random -srand $7 \
   -draw movenumber=40 movecount=8 score=20 -resign movecount=3 score=600 -maxmoves 400 \
   -pgnout file=ms1_$1.pgn -recover > ms1_$1.log 2>&1 </dev/null
  echo "$1 $(grep -E '^Score of' ms1_$1.log | tail -1)" >> ms1_results.txt
}
: > ms1_results.txt
run ft_r1 /tmp/nets/ft.nnue 150 300 0 40 101
run lb2_r1 /tmp/nets/lb2.nnue 150 300 0 40 201
run lb2_r2 /tmp/nets/lb2.nnue 150 300 0 40 202
run lb2_r3 /tmp/nets/lb2.nnue 150 300 0 40 203
run lb2_r4 /tmp/nets/lb2.nnue 150 300 0 40 204
run lb2_r5 /tmp/nets/lb2.nnue 150 300 0 40 205
run lb2_AA /tmp/nets/lb2.nnue 0 300 0 40 299
echo DONE >> ms1_results.txt
