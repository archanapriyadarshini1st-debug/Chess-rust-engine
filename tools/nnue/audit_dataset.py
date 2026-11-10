#!/usr/bin/env python3
"""Audit NextGen CRN teacher shards without changing engine search or evaluation.

Original implementation. The 28-byte input contract is shared with the team's
collector: occupancy u64, 16 packed piece-nibble bytes, stm u8, score i16,
wdl u8. Scores and WDL are side-to-move relative. The format is NOT a complete
game-state or provenance format. Legacy shards are never silently upgraded to
training-eligible data. Strict mode requires a manifest and per-record JSONL
sidecar containing game identity, history, actual search statistics and PVs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import re
import struct
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path

import chess

RECORD = struct.Struct('<Q16sBhB')
PIECES = 'PNBRQKpnbrqk'
SPLITS = ('train', 'validation', 'test')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def records(path: Path):
    with path.open('rb') as stream:
        index = 0
        while True:
            raw = stream.read(RECORD.size)
            if not raw:
                return
            if len(raw) != RECORD.size:
                raise ValueError(f'Truncated record {index}: {len(raw)} bytes, expected 28')
            yield index, raw
            index += 1


def decode(raw: bytes):
    occ, packed, stm, score, wdl = RECORD.unpack(raw)
    count = occ.bit_count()
    if not 2 <= count <= 32:
        raise ValueError(f'Invalid occupancy piece count: {count}')
    if stm not in (0, 1) or wdl not in (0, 1, 2) or not -32000 <= score <= 32000:
        raise ValueError('Invalid side, WDL, or score range')
    nibbles = [byte for pair in packed for byte in (pair & 15, pair >> 4)]
    if any(code > 11 for code in nibbles[:count]):
        raise ValueError('Invalid piece nibble')
    if nibbles[:count].count(5) != 1 or nibbles[:count].count(11) != 1:
        raise ValueError('Exactly one king of each color is required')
    squares = ['.'] * 64
    slot = 0
    for square in range(64):
        if occ & (1 << square):
            code = nibbles[slot]
            if code % 6 == 0 and (square < 8 or square >= 56):
                raise ValueError('Pawn on promotion/back rank')
            squares[square] = PIECES[code]
            slot += 1
    ranks = []
    for rank in reversed(range(8)):
        row = ''
        empty = 0
        for square in squares[rank * 8:(rank + 1) * 8]:
            if square == '.':
                empty += 1
            else:
                if empty:
                    row += str(empty)
                    empty = 0
                row += square
        ranks.append(row + (str(empty) if empty else ''))
    fen = '/'.join(ranks) + (' w' if stm == 0 else ' b') + ' - - 0 1'
    board = chess.Board(fen)
    if not board.is_valid() or board.is_checkmate() or board.is_stalemate():
        raise ValueError('Illegal or terminal board position')
    return {'key': raw[:25], 'board': board, 'fen': fen, 'score': score, 'wdl': wdl}


def validate_manifest(manifest: dict):
    teacher = manifest.get('teacher', {})
    search = manifest.get('search', {})
    if teacher.get('name') != 'Stockfish 19' or teacher.get('tag') != 'sf_19':
        raise ValueError('Teacher must be the pinned official Stockfish 19 release')
    if teacher.get('uci_limit_strength') is not False:
        raise ValueError('Teacher strength limiting must be explicitly false')
    if not re.fullmatch(r'[a-fA-F0-9]{64}', str(teacher.get('binary_sha256', ''))):
        raise ValueError('A real SHA-256 teacher-binary checksum is required')
    if manifest.get('score_pov') != 'side_to_move':
        raise ValueError('Declare and preserve side-to-move score perspective')
    budget = search.get('budget')
    if budget == 'time' and search.get('movetime_ms', 0) < 2000:
        raise ValueError('Time-based teacher labels require at least 2000 ms per move')
    if budget == 'nodes' and search.get('nodes', 0) < 100000:
        raise ValueError('Node-based teacher labels require at least 100000 nodes')
    if budget not in ('time', 'nodes'):
        raise ValueError('Declare a time or node search budget')
    if search.get('min_completed_depth', 0) < 12 or search.get('multipv', 0) < 1:
        raise ValueError('Completed depth must be >=12 and MultiPV >=1')
    if not manifest.get('labels_file') or not manifest.get('source'):
        raise ValueError('Per-record labels and dataset source are required')
    return {'min_depth': int(search['min_completed_depth']), 'multipv': int(search['multipv']), 'min_time_ms': int(search.get('movetime_ms', 0)) if budget == 'time' else 0, 'min_nodes': int(search.get('nodes', 1)) if budget == 'nodes' else 1}


def split_for_group(key: bytes, seed: int, validation: float, test: float):
    value = int.from_bytes(hashlib.sha256(str(seed).encode() + b':' + key).digest()[:8], 'big') / 2**64
    return 'validation' if value < validation else 'test' if value < validation + test else 'train'


def replay_history(label: dict, target: dict):
    initial = label.get('initial_fen', chess.STARTING_FEN)
    board = chess.Board(initial)
    history = label.get('history')
    if not isinstance(history, list) or len(history) > 2000:
        raise ValueError('A bounded move-history list is required')
    for move_text in history:
        try:
            move = chess.Move.from_uci(move_text)
            if move not in board.legal_moves:
                move = board.parse_san(move_text)
            board.push(move)
        except (ValueError, TypeError, AssertionError) as exc:
            raise ValueError(f'Invalid history move: {move_text}') from exc
    if board.board_fen() != target['board'].board_fen() or board.turn != target['board'].turn:
        raise ValueError('History does not reconstruct the packed position')
    if not isinstance(label.get('game_id'), str) or not label['game_id'].strip():
        raise ValueError('A stable game/group ID is required for leakage-resistant splitting')
    labeled_position = chess.Board(label['fen'])
    if labeled_position.board_fen() != target['board'].board_fen() or labeled_position.turn != target['board'].turn:
        raise ValueError('Sidecar FEN disagrees with the packed record')
    return labeled_position


def validate_label(label: dict, target: dict, policy: dict):
    board = replay_history(label, target)
    if label.get('score_pov') != 'side_to_move' or label.get('score_cp') != target['score']:
        raise ValueError('Sidecar score or perspective disagrees with packed label')
    if label.get('depth', 0) < policy['min_depth'] or label.get('nodes', 0) < policy['min_nodes']:
        raise ValueError('Shallow or missing completed-search node statistics')
    if label.get('time_ms', 0) < policy['min_time_ms']:
        raise ValueError('Per-label search time is below the declared teacher budget')
    if label.get('wdl') not in (0, 0.5, 1) or label['wdl'] != target['wdl'] / 2:
        raise ValueError('Sidecar game result does not match the packed WDL label')
    candidates = label.get('candidates')
    if not isinstance(candidates, list) or not candidates:
        raise ValueError('Teacher candidate evaluations are missing')
    if len(candidates) < min(policy['multipv'], board.legal_moves.count()):
        raise ValueError('Requested MultiPV candidates are missing')
    for candidate in candidates:
        if candidate.get('depth', 0) < policy['min_depth'] or not math.isfinite(candidate.get('score_cp', float('nan'))):
            raise ValueError('Invalid candidate depth or score')
        pv = candidate.get('pv')
        if not isinstance(pv, list) or not pv:
            raise ValueError('Candidate principal variation is missing')
        probe = board.copy(stack=False)
        for uci in pv[:32]:
            move = chess.Move.from_uci(uci)
            if move not in probe.legal_moves:
                raise ValueError('Illegal move in teacher principal variation')
            probe.push(move)
    if candidates[0].get('move') != label.get('best_move') or candidates[0].get('score_cp') != target['score']:
        raise ValueError('Top candidate does not match the stored teacher label')


def audit(path: Path, output: Path, manifest_path: Path | None = None, structure_only=False, seed=42, validation=0.1, test=0.1):
    if not 0 < validation < 1 or not 0 < test < 1 or validation + test >= 1:
        raise ValueError('Validation and test fractions must be positive and sum to less than one')
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text()) if manifest_path else {}
    policy = validate_manifest(manifest) if manifest_path and not structure_only else None
    if policy and Path(manifest['labels_file']).resolve() == path.resolve():
        raise ValueError('Labels sidecar must be a separate JSONL file')
    seen, conflicts, groups = {}, set(), {}
    invalid, total, duplicates = [], 0, 0
    for index, raw in records(path):
        total += 1
        try:
            decoded = decode(raw)
            key, label = decoded['key'], (decoded['score'], decoded['wdl'])
            if key in seen:
                duplicates += 1
                if seen[key] != label:
                    conflicts.add(key)
            else:
                seen[key] = label
        except ValueError as exc:
            invalid.append({'record': index, 'reason': str(exc)})
    counts = dict.fromkeys(SPLITS, 0)
    written = set()
    mode = 'strict' if policy else 'structure-only'
    handles = {name: (output / f'{name}.bin').open('wb') for name in SPLITS} if policy else {}
    rejected = (output / 'rejected.jsonl').open('w')
    label_stream = Path(manifest['labels_file']).open() if policy else None
    try:
        pairs = zip_longest(records(path), label_stream) if label_stream else ((item, None) for item in records(path))
        for item, line in pairs:
            if item is None:
                invalid.append({'record': total, 'reason': 'Extra sidecar label without a packed record'})
                continue
            index, raw = item
            try:
                decoded = decode(raw)
                if decoded['key'] in conflicts:
                    raise ValueError('Conflicting duplicate labels; all versions quarantined')
                group = decoded['key']
                if policy:
                    if not line:
                        raise ValueError('Missing per-record teacher sidecar')
                    label = json.loads(line)
                    if label.get('record_index') != index:
                        raise ValueError('Sidecar record index is not aligned')
                    validate_label(label, decoded, policy)
                    group = label['game_id'].encode()
                if decoded['key'] in written:
                    continue
                written.add(decoded['key'])
                groups[decoded['key']] = group
                if policy:
                    split = split_for_group(group, seed, validation, test)
                    handles[split].write(raw)
                    counts[split] += 1
            except (ValueError, TypeError, KeyError, AssertionError, chess.InvalidMoveError) as exc:
                invalid.append({'record': index, 'reason': str(exc)[:300]})
    finally:
        for stream in handles.values():
            stream.close()
        if label_stream:
            label_stream.close()
        for entry in invalid:
            rejected.write(json.dumps(entry) + '\n')
        rejected.close()
    eligible = bool(policy and total and not invalid and not conflicts and all(counts.values()))
    report = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(), 'mode': mode,
              'training_eligible': eligible, 'input': str(path), 'input_sha256': sha256(path),
              'records': total, 'unique_positions': len(written), 'duplicate_records': duplicates,
              'conflicting_positions': len(conflicts), 'invalid_records': len(invalid), 'split_counts': counts,
              'split_method': 'sha256(seed:game_id); first game group wins cross-game duplicates' if policy else None,
              'seed': seed, 'validation_fraction': validation, 'test_fraction': test,
              'source_manifest': manifest, 'outputs': {name: {'sha256': sha256(output / f'{name}.bin'), 'records': counts[name]} for name in SPLITS if policy},
              'caveats': ['Packed records omit castling, en passant and repetition state; the sidecar preserves history.',
                          'Game-group splitting controls exact game leakage, not semantic similarity across games.',
                          'Audit eligibility is not an Elo claim or a substitute for a promotion match.']}
    (output / 'audit-manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--out', type=Path, default=Path('audit-output'))
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--structure-only', action='store_true')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--validation', type=float, default=0.1)
    parser.add_argument('--test', type=float, default=0.1)
    args = parser.parse_args()
    try:
        report = audit(args.input, args.out, args.manifest, args.structure_only, args.seed, args.validation, args.test)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f'Dataset audit failed: {exc}\n')
    print(json.dumps({key: report[key] for key in ('mode', 'training_eligible', 'records', 'unique_positions', 'duplicate_records', 'conflicting_positions', 'invalid_records', 'split_counts')}, indent=2))
    return 0 if report['training_eligible'] or (args.structure_only and not report['invalid_records'] and not report['conflicting_positions']) else 2


if __name__ == '__main__':
    raise SystemExit(main())
