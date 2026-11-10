"""Synthetic contract tests only; no generated fixture is a teacher-strength claim."""
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path
import chess

MODULE = Path(__file__).resolve().parents[1] / 'tools' / 'nnue' / 'audit_dataset.py'
spec = importlib.util.spec_from_file_location('audit_dataset', MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
START = chess.STARTING_FEN
ENDGAME = '8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1'
ITALIAN = 'r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3'


def pack(fen=START, score=15, wdl=1):
    board = chess.Board(fen)
    occ, nibbles = 0, []
    for square, piece in sorted(board.piece_map().items()):
        occ |= 1 << square
        nibbles.append((0 if piece.color else 6) + piece.piece_type - 1)
    nibbles += [0] * (32 - len(nibbles))
    packed = bytes(nibbles[i] | (nibbles[i + 1] << 4) for i in range(0, 32, 2))
    return audit.RECORD.pack(occ, packed, 0 if board.turn else 1, score, wdl)


def valid_manifest():
    return {'teacher': {'name': 'Stockfish 19', 'tag': 'sf_19', 'binary_sha256': '0' * 64, 'uci_limit_strength': False}, 'search': {'budget': 'time', 'movetime_ms': 2000, 'min_completed_depth': 16, 'multipv': 3}, 'score_pov': 'side_to_move', 'labels_file': 'labels.jsonl', 'source': 'unit-test fixture, not training data'}


class AuditTests(unittest.TestCase):
    def test_round_trip_preserves_features_and_stm(self):
        for fen in (START, ENDGAME, ITALIAN):
            original = chess.Board(fen)
            result = audit.decode(pack(fen))
            self.assertEqual(original.board_fen(), result['board'].board_fen())
            self.assertEqual(original.turn, result['board'].turn)
            self.assertEqual(result['key'], pack(fen)[:25])

    def test_score_and_piece_encoding(self):
        self.assertEqual(audit.decode(pack(score=-1234))['score'], -1234)
        self.assertEqual(audit.decode(pack(ITALIAN))['board'].piece_at(chess.C4).symbol(), 'B')

    def test_rejects_missing_king(self):
        raw = bytearray(pack('4k3/8/8/8/8/8/4P3/4K3 w - - 0 1'))
        # Remove the white king from occupancy, leaving its nibble as padding.
        occ = struct.unpack_from('<Q', raw)[0] & ~(1 << chess.E1)
        struct.pack_into('<Q', raw, 0, occ)
        with self.assertRaisesRegex(ValueError, 'king'):
            audit.decode(bytes(raw))

    def test_rejects_back_rank_pawn(self):
        raw = bytearray(pack('4k3/8/8/8/8/8/8/4K3 w - - 0 1'))
        # The chess library sanitizes back-rank pawns from FEN, so corrupt the
        # raw occupancy directly. The first piece nibble is a white pawn.
        occ = struct.unpack_from('<Q', raw)[0] | (1 << chess.A1)
        struct.pack_into('<Q', raw, 0, occ)
        with self.assertRaisesRegex(ValueError, 'Pawn'):
            audit.decode(bytes(raw))

    def test_rejects_truncated_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'broken.bin'
            path.write_bytes(pack() + b'abc')
            with self.assertRaisesRegex(ValueError, 'Truncated'):
                list(audit.records(path))

    def test_conflicting_duplicates_are_all_quarantined(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.bin'
            source.write_bytes(pack(score=20) + pack(score=-20) + pack(score=20) + pack(ENDGAME))
            report = audit.audit(source, root / 'out', structure_only=True)
            self.assertEqual(report['conflicting_positions'], 1)
            self.assertEqual(report['duplicate_records'], 2)
            self.assertEqual(report['unique_positions'], 1)
            self.assertFalse(report['training_eligible'])
            self.assertEqual(report['mode'], 'structure-only')
            self.assertEqual(len((root / 'out' / 'rejected.jsonl').read_text().splitlines()), 3)

    def test_exact_duplicate_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.bin'
            source.write_bytes(pack() + pack())
            report = audit.audit(source, root / 'out', structure_only=True)
            self.assertEqual(report['unique_positions'], 1)
            self.assertEqual(report['duplicate_records'], 1)
            self.assertFalse(report['training_eligible'])

    def test_split_is_deterministic_and_disjoint(self):
        assignments = [{split: set() for split in audit.SPLITS} for _ in range(2)]
        for index in range(2000):
            key = f'game-{index}'.encode()
            values = [audit.split_for_group(key, 42, .1, .1) for _ in range(2)]
            self.assertEqual(values[0], values[1])
            for result, split in zip(assignments, values):
                result[split].add(key)
        for result in assignments:
            self.assertTrue(all(result.values()))
            self.assertEqual(len(set.union(*result.values())), 2000)
            self.assertEqual(sum(map(len, result.values())), 2000)
        self.assertTrue(any(audit.split_for_group(f'game-{i}'.encode(), 42, .1, .1) != audit.split_for_group(f'game-{i}'.encode(), 43, .1, .1) for i in range(100)))

    def test_teacher_policy_fails_closed(self):
        self.assertEqual(audit.validate_manifest(valid_manifest())['min_depth'], 16)
        for path, value in [(('teacher', 'uci_limit_strength'), True), (('search', 'movetime_ms'), 120), (('search', 'min_completed_depth'), 4), (('teacher', 'binary_sha256'), 'unknown')]:
            manifest = valid_manifest()
            manifest[path[0]][path[1]] = value
            with self.assertRaises(ValueError):
                audit.validate_manifest(manifest)
        manifest = valid_manifest()
        manifest['score_pov'] = 'white'
        with self.assertRaises(ValueError):
            audit.validate_manifest(manifest)

    def test_per_label_budget_result_and_pv_checks(self):
        candidates = [{'move': move, 'score_cp': 15, 'depth': 16, 'pv': [move]} for move in ('e2e4', 'd2d4', 'g1f3')]
        label = {'fen': START, 'initial_fen': START, 'history': [], 'game_id': 'synthetic-contract-fixture', 'score_pov': 'side_to_move', 'score_cp': 15, 'best_move': 'e2e4', 'depth': 16, 'nodes': 500000, 'time_ms': 2000, 'wdl': 0.5, 'candidates': candidates}
        policy = audit.validate_manifest(valid_manifest())
        target = audit.decode(pack(score=15))
        audit.validate_label(label, target, policy)
        for field, value in [('time_ms', 120), ('depth', 8), ('wdl', 1), ('best_move', 'a2a4')]:
            with self.assertRaises(ValueError):
                audit.validate_label({**label, field: value}, target, policy)
        candidates[0] = {**candidates[0], 'pv': ['e2e5']}
        with self.assertRaises(ValueError):
            audit.validate_label(label, target, policy)

    def test_invalid_split_fractions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.bin'
            source.write_bytes(pack())
            with self.assertRaises(ValueError):
                audit.audit(source, root / 'out', validation=.8, test=.4)

    def test_history_reconstruction(self):
        board = chess.Board()
        history = []
        for uci in ('e2e4', 'e7e5', 'g1f3', 'b8c6', 'f1c4'):
            history.append(uci)
            board.push_uci(uci)
        label = {'fen': board.fen(), 'initial_fen': START, 'history': history, 'game_id': 'fixture-game-1'}
        result = audit.replay_history(label, audit.decode(pack(board.fen())))
        self.assertTrue(result.has_kingside_castling_rights(chess.WHITE))
        label['history'] = ['e2e5']
        with self.assertRaises(ValueError):
            audit.replay_history(label, audit.decode(pack(board.fen())))


if __name__ == '__main__':
    unittest.main()
