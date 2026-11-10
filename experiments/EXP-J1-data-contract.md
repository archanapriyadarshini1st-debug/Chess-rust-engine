# EXP-J1 — Teacher-data quality contract

**Owner:** Agent J, workspace session through `pepp-castt`  
**Scope:** New data-audit tooling and tests only. No engine source, trainer, network, or search ownership changes.  
**Status:** Tooling tested; awaiting code review and separate trainer integration. **No Elo gain claimed.**

## Hypothesis

A fail-closed data contract can distinguish structurally valid packed records from training-eligible, reproducible teacher data. It can also quarantine conflicting labels and prevent exact game-group overlap between train, validation, and test splits.

## Reproduction

```sh
python -m pip install chess==1.11.2
python -m unittest discover -s tests -p 'test_audit_dataset.py' -v
python tools/nnue/audit_dataset.py data/teacher-42595442579.bin --out audit-output --structure-only
```

## Executed evidence

- **12 synthetic contract tests passed** locally with Python 3.11.2 and python-chess 1.11.2.
- Tests cover feature/STM round trips, negative scores, king counts, raw back-rank-pawn corruption, truncated records, exact duplicates, conflicting-label quarantine, deterministic/disjoint partitions, teacher-policy rejection, per-label time/depth/WDL/PV checks, invalid split fractions, and history reconstruction.
- The first test run found an overfull-split predicate bug and two invalid/unordered synthetic fixtures. These were corrected before the passing run; the fixtures are not engine-strength evidence.
- Audited the actual public `teacher-data` artifact `data/teacher-42595442579.bin` from `archanapriyadarshini1st-debug/Chess-rust-engine`:
  - Size: **9,763,992 bytes**
  - SHA-256: `31adff34664b5b37abc495cfca0c10862ca822e4a3b1a91e9f7738f9a6e5a476`
  - Records: **348,714**
  - Unique feature/STM positions: **348,714**
  - Exact duplicates: **0**
  - Conflicting positions: **0**
  - Structurally invalid records: **0**
  - Mode: **structure-only**
  - Training eligibility under the proposed strict contract: **false**, because per-record provenance and game-group identity are not present in this legacy artifact.

Source: https://github.com/archanapriyadarshini1st-debug/Chess-rust-engine/blob/teacher-data/data/teacher-42595442579.bin

## Interpretation and limits

This real shard is structurally clean. The random-split duplicate concern is a reproducible risk in the trainer's code path, **not an observation of duplicates in this particular shard**. Do not generalize this sample to every dataset or claim an evaluation improvement from it.

The auditor does not train a model, generate Stockfish labels, establish Elo, or verify a remote checksum against a binary it does not possess. Strict mode validates supplied provenance and sidecar consistency. A collector must still attest the actual binary hash/version and search settings. Game-group splitting controls game leakage, not semantic similarity across games.

## Next reviewable steps

1. Review the auditor and its fail-closed conditions.
2. Agree on a provenance/game-group sidecar without silently changing the compact record format.
3. In a separate coordinated PR, wire the trainer to consume only `train.bin` and its manifest, preserve held-out splits, and test cross-split overlap.
4. Keep HCE as fallback. Any network or evaluator change requires the team's correctness and candidate-vs-stable match gates; validation loss is not playing strength.
