from fractions import Fraction as F

from rework.process.frequencies import build_frequencies
from rework.process.revisions import freeze_process, read_frozen_revision

from tests.support import ProjectCase, batch


class TestProcess(ProjectCase):
    def test_frequencies(self):
        source = batch('Alpha', (
            ('bench', 'send', 1), ('bench', 'other', 5), ('bench', 'send', 1),
        ), exits=('send', 'other'))
        with self.station('alpha') as (_, revisions, _):
            draft = revisions.save_draft(source)
            preview = build_frequencies(draft.batch)
            revision = freeze_process(revisions, draft.draft_id)
            self.assertEqual(preview, revision.rules)
            self.assertEqual([(r.target, r.minutes, r.count, r.probability) for r in revision.rules], [
                ('other', 5, 1, F(1, 3)), ('send', 1, 2, F(2, 3)),
            ])
            self.assertEqual(revision.batch.observations, source.observations)
            self.assertEqual(read_frozen_revision(revisions, revision.revision_id), revision)
            self.assertEqual(revisions.load_draft(draft.draft_id).frozen_revision_id, revision.revision_id)

    def test_negative_duration(self):
        good = batch('Alpha', [('bench', 'send', 1)])
        invalid = batch('Alpha', [('bench', 'send', 3), ('bench', 'send', -1)])
        with self.station('alpha') as (db, revisions, _):
            old = freeze_process(revisions, revisions.save_draft(good).draft_id)
            draft = revisions.save_draft(good)
            with self.assertRaisesRegex(ValueError, 'nonnegative integer minutes'):
                freeze_process(revisions, draft.draft_id, reviewed_batch=invalid)
            with self.assertRaises(ValueError):
                revisions.save_draft(invalid)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM process_drafts').fetchone()[0], 2)
        with self.station('alpha') as (db, revisions, _):
            self.assertEqual(db.execute('SELECT COUNT(*) FROM process_revisions').fetchone()[0], 1)
            self.assertEqual(revisions.load_draft(draft.draft_id), draft)
            self.assertEqual(read_frozen_revision(revisions, old.revision_id), old)

    def test_atomic_batch(self):
        good = batch('Alpha', [('bench', 'send', 1)])
        invalid_batches = (
            batch('Alpha', [('bench', 'send', 2), ('elsewhere', 'send', 3)]),
            batch('Alpha', [('bench', 'send', 2), ('bench', 'unknown', 3)]),
            batch('Alpha', [('bench', 'send', 2)], workstations=('bench', 'spare')),
            batch('Alpha', [('bench', 'send', True)]),
        )
        with self.station('alpha') as (db, revisions, _):
            draft = revisions.save_draft(good)
            for invalid in invalid_batches:
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    freeze_process(revisions, draft.draft_id, reviewed_batch=invalid)
            self.assertEqual(revisions.load_draft(draft.draft_id), draft)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM process_revisions').fetchone()[0], 0)
            completed = batch('Alpha', [('bench', 'spare', 2), ('spare', 'send', 3)],
                              workstations=('bench', 'spare'))
            revision = freeze_process(revisions, draft.draft_id, reviewed_batch=completed)
            self.assertEqual(revision.batch, completed)
            self.assertEqual(revisions.load_draft(draft.draft_id).batch, completed)
            with self.assertRaises(ValueError):
                revisions.save_draft(good, draft_id=draft.draft_id)
            with self.assertRaises(ValueError):
                freeze_process(revisions, draft.draft_id)
