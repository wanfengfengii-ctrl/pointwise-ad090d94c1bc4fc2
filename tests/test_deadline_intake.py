import json
from hashlib import sha256

from rework.routing.deadline_intake import receive_deadline_evidence
from rework.station.codec import encode_evidence
from rework.station.deadline_codec import decode_deadline_evidence

from tests.support import ProjectCase, alpha_batch, receive_piece


class TestDeadlineIntake(ProjectCase):
    def _companion(self, name='alpha', sample=None):
        piece, companion, payload = self.issue_with_companion(
            name, sample or alpha_batch(), coverage=2)
        return piece, companion, payload

    def test_requires_parent_first(self):
        piece, companion, payload = self._companion()
        with self.center() as (db, catalog, _):
            with self.assertRaises(KeyError):
                receive_deadline_evidence(catalog, payload)
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM received_deadline_evidence').fetchone()[0], 0)
            receive_piece(catalog, piece)
            companion_id = receive_deadline_evidence(catalog, payload)
            self.assertEqual(companion_id, companion.companion_id)
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM received_deadline_evidence').fetchone()[0], 1)

    def test_same_number_same_content_returns_original(self):
        piece, companion, payload = self._companion()
        with self.center() as (_, catalog, _):
            receive_piece(catalog, piece)
            first = receive_deadline_evidence(catalog, payload)
            pretty = json.dumps(json.loads(payload), indent=2).encode()
            second = receive_deadline_evidence(catalog, pretty)
            self.assertEqual(first, second)
            stored = decode_deadline_evidence(
                catalog.load_deadline_evidence(companion.companion_id))
            self.assertEqual(stored, companion)

    def test_same_number_different_content_rejected(self):
        piece, companion, payload = self._companion()
        with self.center() as (db, catalog, _):
            receive_piece(catalog, piece)
            receive_deadline_evidence(catalog, payload)
            changed = json.loads(payload)
            changed['coverage'] = 3
            with self.assertRaisesRegex(ValueError, 'different content'):
                receive_deadline_evidence(catalog, json.dumps(changed).encode())
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM received_deadline_evidence').fetchone()[0], 1)

    def test_identity_fingerprint_and_port_checks(self):
        piece, companion, payload = self._companion()
        with self.center() as (_, catalog, _):
            receive_piece(catalog, piece)
            tampered = json.loads(payload)

            tampered['parent']['revision_id'] = 'rev-other'
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                receive_deadline_evidence(catalog, json.dumps(tampered).encode())

            tampered = json.loads(payload)
            tampered['parent_sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
                receive_deadline_evidence(catalog, json.dumps(tampered).encode())

            tampered = json.loads(payload)
            tampered['entries'] = ['start', 'surprise']
            with self.assertRaisesRegex(ValueError, 'public ports'):
                receive_deadline_evidence(catalog, json.dumps(tampered).encode())

    def test_rejects_bad_envelopes(self):
        piece, _, payload = self._companion()
        with self.center() as (db, catalog, _):
            receive_piece(catalog, piece)
            base = json.loads(payload)
            variants = []

            broken = dict(base)
            broken['kind'] = 'other'
            variants.append(broken)

            broken = dict(base)
            broken['version'] = 2
            variants.append(broken)

            broken = json.loads(json.dumps(base))
            broken['data'] = {'start': {'send': [[1, '2/1']]}}
            variants.append(broken)  # non-canonical fraction

            broken = json.loads(json.dumps(base))
            broken['data'] = {'start': {'send': [[9, '1']]}}
            variants.append(broken)  # minute above coverage

            broken = json.loads(json.dumps(base))
            broken['data'] = {'start': {'unknown': [[0, '1']]}}
            variants.append(broken)  # undeclared exit

            broken = json.loads(json.dumps(base))
            broken['data'] = {'start': {'send': [[0, '1/2']]},
                              'extra': {'send': [[0, '1/2']]}}
            variants.append(broken)  # undeclared entry

            for variant in variants:
                with self.subTest(variant=variant):
                    with self.assertRaises(ValueError):
                        receive_deadline_evidence(catalog, json.dumps(variant).encode())
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM received_deadline_evidence').fetchone()[0], 0)

    def test_duplicate_json_field_is_bad(self):
        piece, _, payload = self._companion()
        with self.center() as (_, catalog, _):
            receive_piece(catalog, piece)
            text = payload.decode()
            duplicated = text.replace('"coverage":2', '"coverage":2,"coverage":2', 1)
            with self.assertRaises(ValueError):
                receive_deadline_evidence(catalog, duplicated.encode())

    def test_mass_above_one_rejected(self):
        piece, _, payload = self._companion()
        with self.center() as (_, catalog, _):
            receive_piece(catalog, piece)
            broken = json.loads(payload)
            # Alpha leaves at minute one with mass one; add a second full record.
            broken['data'] = {'start': {'send': [[1, '1']], 'other': [[0, '1']]}}
            broken['exits'] = ['other', 'send']
            with self.assertRaises(ValueError):
                receive_deadline_evidence(catalog, json.dumps(broken).encode())

    def test_fingerprint_matches_encoded_parent(self):
        piece, companion, payload = self._companion()
        with self.center() as (_, catalog, _):
            receive_piece(catalog, piece)
            self.assertEqual(companion.parent_sha256,
                             sha256(encode_evidence(piece)).hexdigest())
            receive_deadline_evidence(catalog, payload)
