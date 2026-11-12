"""Endgame conversion downside check (EXP-EC1).

usage: python tools/endgame_conversion.py <engine-exe> <hce|net> <seconds-per-move> [net-file]

Plays the engine against itself from random legal won endgames (KQK, KRK, KBBK,
KBNK; white to move, not in check) and counts how many end in checkmate within
200 plies.  Requires `pip install chess`.  Fixed seed (7): identical start
positions for every arm.  Small n -> preliminary only.
"""
import chess,chess.engine,sys,random,os
exe=sys.argv[1]; net=sys.argv[2]=="net"; mt=float(sys.argv[3])
env=dict(os.environ); 
if net: env["CRE_NNUE_FILE"]=sys.argv[4] if len(sys.argv)>4 else os.environ.get("CRE_NNUE_FILE","")
else: env.pop("CRE_NNUE_FILE",None)
def sqc(s): return (chess.square_file(s)+chess.square_rank(s))%2
def rand_pos(white_pieces):
    while True:
        b=chess.Board(None); sq=random.sample(range(64),2+len(white_pieces))
        b.set_piece_at(sq[0],chess.Piece(chess.KING,chess.WHITE)); b.set_piece_at(sq[1],chess.Piece(chess.KING,chess.BLACK))
        for s,p in zip(sq[2:],white_pieces): b.set_piece_at(s,chess.Piece(p,chess.WHITE))
        b.turn=chess.WHITE
        if b.is_valid() and not b.is_check() and not b.is_game_over():
            if white_pieces.count(chess.BISHOP)==2:
                bs=[s for s in sq[2:] if b.piece_type_at(s)==chess.BISHOP]
                if sqc(bs[0])==sqc(bs[1]): continue
            return b
tests={"KQK":[chess.QUEEN],"KRK":[chess.ROOK],"KBBK":[chess.BISHOP,chess.BISHOP],"KBNK":[chess.BISHOP,chess.KNIGHT]}
eng=chess.engine.SimpleEngine.popen_uci(exe,env=env)
random.seed(7)
for name,pcs in tests.items():
    n=10; mates=0; pl=[]
    for i in range(n):
        b=rand_pos(pcs); plies=0
        while not b.is_game_over(claim_draw=True) and plies<200:
            r=eng.play(b,chess.engine.Limit(time=mt)); b.push(r.move); plies+=1
        if b.is_checkmate(): mates+=1; pl.append(plies)
    print(f"{name}: mated {mates}/{n} within 100 moves; mean plies {sum(pl)/max(1,len(pl)):.0f}",flush=True)
eng.quit()
