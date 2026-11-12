# EXP-GP2: reject unusable `position` input instead of searching it

- **Experiment ID:** EXP-GP2
- **Responsible agent:** Agent GP (owner's Composio connection)
- **Baseline:** `main` 73d0379, `bench 10` = 553783
- **Hypothesis:** `Position::from_fen` accepts boards with no king, two kings, pawns on the back rank,
  or the side *not* to move already in check. Such a position reaches search/movegen, where king
  squares are invalid (index out of range in the attack tables, reported by Agent NS at
  `attacks.rs:397`) or the engine plays an impossible move. In a real game that is a forfeit.
- **Change:** `Position::sanitize()` (called at the end of `from_fen`, before the hash is built):
  rejects missing/extra kings, >8 pawns, >16 pieces, back-rank pawns, side-not-to-move in check;
  silently drops castling rights without king+rook on their home squares; drops an en-passant
  square that is not empty / on the right rank / with the victim pawn behind it.
  The UCI `position` command already ignores a FEN that `from_fen` rejects, so the previous
  position is kept. No search or eval code is touched.
- **Expected benefit:** no panic or illegal move on malformed GUI input. **No Elo claim.**
- **Possible regressions:** a legal position wrongly rejected (checked: whole perft suite, which
  loads 6 CPW positions through `from_fen`, is unchanged); a tablebase/Chess960 style FEN with
  non-standard castling letters is not supported by `from_fen` today either.
- **Evidence**
  - `tests/illegal_positions.rs`: 3 tests. They **fail on main 73d0379** (`rejects_unusable_positions`,
    `repairs_stale_castling_and_bogus_ep`) and **pass with the change**.
  - `cargo test --release`: all green. `bench 10` = **553783** nodes, identical to main (the
    start position and bench positions are untouched, so the tree is identical).
  - UCI check, old binary: `position fen 4k3/8/8/8/8/8/8/4RK2 w - - 0 1` + `go depth 6` returns
    `bestmove e1a1` (searches an impossible position); `position fen 8/8/8/8/8/8/8/4K3 w ...` (no black king)
    returns `e1d1`. New binary ignores both positions.
- **Decision:** keep (correctness fix, node-identical on bench). Needs a reviewer who is not the author.
