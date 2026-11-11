#!/usr/bin/env bash
# Head-to-head of two nets on ONE engine binary (only CRE_NNUE_FILE differs). Used by EXP-KB1.
#   tools/gate_two_nets.sh <engine> <netA> <netB> [games=200] [tc=10+0.1] [concurrency=3] [out_dir] [srand=7]
# Prints fastchess's "Score of A vs B" line; A = netA. Colours reversed per opening pair.
set -euo pipefail
ENG=$(readlink -f "$1"); NA=$(readlink -f "$2"); NB=$(readlink -f "$3")
GAMES=${4:-200}; TC=${5:-10+0.1}; CONC=${6:-3}; OUT=${7:-gate2_out}; SEED=${8:-7}
FASTCHESS=${FASTCHESS:-fastchess}
BOOK=${BOOK:-$(dirname "$0")/openings_book.epd}
mkdir -p "$OUT"
for X in A B; do
  N=$NA; [ "$X" = B ] && N=$NB
  printf '#!/usr/bin/env bash\nexport CRE_NNUE_FILE="%s"\nexec "%s" "$@"\n' "$N" "$ENG" > "$OUT/net$X.sh"
  chmod +x "$OUT/net$X.sh"
done
"$FASTCHESS" \
  -engine name=A cmd="$OUT/netA.sh" option.UseNNUE=true option.Hash=64 \
  -engine name=B cmd="$OUT/netB.sh" option.UseNNUE=true option.Hash=64 \
  -each tc="$TC" \
  -openings file="$BOOK" format=epd order=random -srand "$SEED" \
  -rounds $((GAMES / 2)) -games 2 -repeat -concurrency "$CONC" \
  -pgnout file="$OUT/games.pgn" -recover -ratinginterval 20 2>&1 | tee "$OUT/gate.log" | tail -n 25
echo "config: engine_sha=$(sha256sum "$ENG" | cut -c1-12) A=$(sha256sum "$NA" | cut -c1-12) B=$(sha256sum "$NB" | cut -c1-12) tc=$TC games=$GAMES srand=$SEED book=$(basename "$BOOK") sha_book=$(sha256sum "$BOOK" | cut -c1-12) hash=64 threads=1" | tee "$OUT/config.txt"
