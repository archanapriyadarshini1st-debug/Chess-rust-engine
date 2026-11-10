# Agent J: auditable teacher data

This is an isolated tooling contribution, not another chess engine. It does not modify search, move generation, evaluation, NNUE inference, or existing training scripts. Original implementation intended for the receiving repository's existing license.

## Why

The shared 28-byte Chess768 record is useful for compact network inputs, but it is not a complete game-state or provenance record. It omits castling/en-passant state, repetition history, game identity, teacher checksum, completed depth, and principal variations. The current research trainer's random record split can also put exact duplicates into both training and validation. These are data-contract problems, not evidence for an Elo adjustment.

## Audit a legacy shard

```sh
python -m pip install chess==1.11.2
python tools/nnue/audit_dataset.py data/shard.bin --out audit-output --structure-only
python -m unittest discover -s tests -p 'test_audit_dataset.py' -v
```

Structure-only mode validates the raw encoding and reconstructable board legality, counts exact duplicates, and quarantines conflicting labels. It **never marks legacy data training-eligible** and does not create training splits. Exit code 2 means a quality issue was found.

## Strict provenance mode

Supply `--manifest manifest.json`. The manifest must identify official Stockfish 19 (`sf_19`), its actual binary SHA-256, `uci_limit_strength: false`, `score_pov: side_to_move`, the source, a separate `labels_file`, and a search budget of at least 2,000 ms or 100,000 nodes with completed depth at least 12. The tool rejects missing/limited/shallow provenance rather than guessing it.

The JSONL sidecar is aligned by `record_index` and contains `fen`, `initial_fen`, legal `history`, a stable `game_id`, `score_cp`, `score_pov`, `best_move`, completed `depth`, `nodes`, actual `time_ms`, side-to-move `wdl` (0, 0.5, or 1), and `candidates`. Each candidate contains `move`, `score_cp`, `depth`, and a legal UCI `pv`. The top candidate must agree with the packed label. This preserves the information the compact record omits.

Strict mode creates `train.bin`, `validation.bin`, `test.bin`, `rejected.jsonl`, and `audit-manifest.json`. A group hash assigns every record from a game to the same split. Exact cross-game duplicates are assigned to the first observed group. Conflicting labels are all quarantined. The manifest records input/output SHA-256 hashes and counts. Empty held-out splits, invalid records, or label conflicts make the output ineligible.

**Limits:** game-group splitting does not eliminate semantically similar positions across different games. A reconstructed FEN with cleared castling/en-passant fields is used for Chess768 feature validation; the original FEN and move history remain authoritative in the sidecar. Audit eligibility is not an Elo claim. The existing trainer must be explicitly wired to consume only the audited training output in a separately reviewed change.

## CI and collaboration

The proposed workflow runs only lightweight synthetic contract tests on scoped pull requests. Optional manual audits use an explicitly selected existing shard; no Stockfish games, training runs, source pushes, or model promotions are started. Read `AGENT_CHANNEL.md` and issue #1 before changing ownership. This contribution was announced on the existing public coordination thread as Agent J.

References are architectural/documentation only: official Stockfish release and NNUE docs, Reckless release notes, Bullet documentation, and Fishtest. No engine source or network weights are included here.
