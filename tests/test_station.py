import json
from fractions import Fraction as F

from rework.process.revisions import freeze_process
from rework.station.codec import decode_evidence, encode_evidence
from rework.station.issue import issue_evidence, read_station_evidence

from tests.support import ProjectCase, batch


class TestStation(ProjectCase):
    def test_draft_not_issued(self):
        with self.station('alpha') as (db, revisions, issued):
            draft = revisions.save_draft(batch('Alpha', [('bench', 'send', 1)]))
            for identifier in (draft.draft_id, 'unknown-revision'):
                with self.subTest(identifier=identifier), self.assertRaises(KeyError):
                    issue_evidence(revisions, issued, identifier)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM issued_evidence').fetchone()[0], 0)
            revision = freeze_process(revisions, draft.draft_id)
            piece = issue_evidence(revisions, issued, revision.revision_id)
            self.assertEqual(piece.identity.revision_id, revision.revision_id)
            self.assertEqual(read_station_evidence(issued, piece.identity.evidence_id), piece)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM issued_evidence').fetchone()[0], 1)

    def test_issued_snapshot(self):
        source = batch('Alpha', (
            ('bench', 'send', 1), ('bench', 'send', 1), ('bench', 'other', 5),
        ), exits=('send', 'other'))
        piece = self.issue('alpha', source)
        with self.station('alpha') as (_, _, issued):
            original = read_station_evidence(issued, piece.identity.evidence_id)
        payload = encode_evidence(original)
        self.assertEqual(decode_evidence(payload), piece)
        envelope = json.loads(payload)
        self.assertEqual(envelope['version'], 1)
        self.assertEqual(envelope['entries'], ['start'])
        self.assertEqual(envelope['rows'], [
            ['start', 'other', '1/3', '5/3', '25/3'],
            ['start', 'send', '2/3', '2/3', '2/3'],
        ])
        self.assertNotIn(b'bench', payload)
        self.assertNotIn(b'observations', payload)

    def test_private_retries_with_positive_minutes(self):
        source = batch('Alpha', (
            ('bench', 'loop', 0), ('loop', 'loop', 1), ('loop', 'loop', 1),
            ('loop', 'send', 2), ('loop', 'discard', 0),
        ), exits=('send', 'discard'), workstations=('bench', 'loop'))
        piece = self.issue('alpha', source)
        self.assertEqual({row.exit: (row.probability, row.first, row.second) for row in piece.rows}, {
            'send': (F(1, 2), F(3, 2), F(11, 2)),
            'discard': (F(1, 2), F(1, 2), F(3, 2)),
        })
