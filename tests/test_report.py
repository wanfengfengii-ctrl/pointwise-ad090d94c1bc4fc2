import json
import sqlite3
from fractions import Fraction as F

from rework.analysis.assessment import publish_assessment
from rework.process.revisions import freeze_process, open_correction, read_frozen_revision
from rework.report.export import export_report
from rework.report.ledger import read_report
from rework.routing.intake import get_received_evidence
from rework.routing.plans import read_frozen_route
from rework.station.issue import issue_evidence, read_station_evidence

from tests.support import ProjectCase, alpha_batch, batch, beta_batch, port, receive_piece, two_station_route, values


class TestReport(ProjectCase):
    def test_commit_failure(self):
        alpha, beta = self.returning_pieces()
        with self.center() as (db, catalog, ledger):
            receive_piece(catalog, alpha)
            receive_piece(catalog, beta)
            route = two_station_route(catalog, alpha, beta, returning=True)
            original = publish_assessment(catalog, ledger, route.route_id, port(alpha))
            db.execute('PRAGMA foreign_keys = ON')
            db.executescript('''
                CREATE TABLE approval_gate (report_id TEXT PRIMARY KEY);
                CREATE TABLE deferred_approval (
                    report_id TEXT NOT NULL REFERENCES approval_gate(report_id)
                    DEFERRABLE INITIALLY DEFERRED
                );
                CREATE TRIGGER require_approval AFTER INSERT ON published_reports
                BEGIN
                    INSERT INTO deferred_approval VALUES (NEW.report_id);
                END;
            ''')
            trace = []
            db.set_trace_callback(trace.append)
            try:
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY'):
                    publish_assessment(catalog, ledger, route.route_id, port(alpha))
            finally:
                db.set_trace_callback(None)
            self.assertTrue(any(statement.startswith('INSERT INTO published_reports') for statement in trace))
            self.assertIn('COMMIT', trace)
            self.assertFalse(db.in_transaction)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM deferred_approval').fetchone()[0], 0)
            with self.center() as (reader, _, other_ledger):
                self.assertEqual([row[0] for row in reader.execute('SELECT report_id FROM published_reports')],
                                 [original.report_id])
                self.assertEqual(read_report(other_ledger, original.report_id), original)
            self.assertEqual(read_report(ledger, original.report_id), original)
        with self.center() as (db, _, ledger):
            self.assertEqual(db.execute('SELECT COUNT(*) FROM published_reports').fetchone()[0], 1)
            self.assertEqual(read_report(ledger, original.report_id), original)

    def test_frozen_report(self):
        alpha, beta = self.returning_pieces()
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, alpha)
            receive_piece(catalog, beta)
            yesterday_route = two_station_route(catalog, alpha, beta, returning=True)
            yesterday = publish_assessment(catalog, ledger, yesterday_route.route_id, port(alpha))
            old_bytes = export_report(read_report(ledger, yesterday.report_id))
        with self.station('beta') as (_, revisions, issued):
            original_revision = read_frozen_revision(revisions, beta.identity.revision_id)
            with self.assertRaises(ValueError):
                open_correction(revisions, original_revision.revision_id, alpha_batch())
            correction = open_correction(revisions, original_revision.revision_id, beta_batch(5))
            self.assertEqual(correction.corrected_from, original_revision.revision_id)
            next_revision = freeze_process(revisions, correction.draft_id)
            replacement = issue_evidence(revisions, issued, next_revision.revision_id)
            self.assertNotEqual(replacement.identity.evidence_id, beta.identity.evidence_id)
            self.assertNotEqual(next_revision.revision_id, original_revision.revision_id)
            self.assertEqual(read_frozen_revision(revisions, original_revision.revision_id), original_revision)
            self.assertEqual(read_station_evidence(issued, beta.identity.evidence_id), beta)
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, replacement)
            today_route = two_station_route(catalog, alpha, replacement, returning=True)
            today = publish_assessment(catalog, ledger, today_route.route_id, port(alpha))
        with self.center() as (db, catalog, ledger):
            old = read_report(ledger, yesterday.report_id)
            new = read_report(ledger, today.report_id)
            self.assertEqual(values(old), (F(2, 3), F(10, 3), F(4, 9)))
            self.assertEqual(values(new), (F(2, 3), F(19, 3), F(4, 9)))
            self.assertEqual(old, yesterday)
            self.assertEqual(new, today)
            self.assertEqual(old.provenance.start, new.provenance.start)
            self.assertNotEqual(old.report_id, new.report_id)
            self.assertEqual(old.provenance.route_id, yesterday_route.route_id)
            self.assertEqual(new.provenance.route_id, today_route.route_id)
            self.assertEqual(set(old.provenance.pieces), {alpha.identity, beta.identity})
            self.assertEqual(set(new.provenance.pieces), {alpha.identity, replacement.identity})
            self.assertEqual(export_report(old), old_bytes)
            self.assertEqual((old.mean_unit, old.variance_unit), ('minute', 'minute_squared'))
            self.assertEqual(json.loads(export_report(new))['mean'], '19/3')
            self.assertEqual(get_received_evidence(catalog, beta.identity), beta)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM report_receipts').fetchone()[0], 3)

    def test_unknown_report(self):
        with self.center() as (db, _, ledger):
            with self.assertRaises(KeyError):
                read_report(ledger, 'unknown-report')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM report_receipts').fetchone()[0], 0)

    def test_repeated_init(self):
        alpha, beta = self.returning_pieces()
        with self.station('alpha') as (_, revisions, _):
            draft = revisions.save_draft(alpha_batch())
            updated = revisions.save_draft(batch('Alpha', [('bench', 'send', 7)]), draft_id=draft.draft_id)
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, alpha)
            receive_piece(catalog, beta)
            route = two_station_route(catalog, alpha, beta, returning=True)
            report = publish_assessment(catalog, ledger, route.route_id, port(alpha))
            self.assertEqual(read_report(ledger, report.report_id), report)
        with self.station('alpha') as (db, revisions, issued):
            for _ in range(2):
                revisions.initialize()
                issued.initialize()
            self.assertEqual(revisions.load_draft(updated.draft_id), updated)
            self.assertEqual(read_frozen_revision(revisions, alpha.identity.revision_id).batch, alpha_batch())
            self.assertEqual(read_station_evidence(issued, alpha.identity.evidence_id), alpha)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM process_drafts').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM process_revisions').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM issued_evidence').fetchone()[0], 1)
        with self.center() as (db, catalog, ledger):
            for _ in range(2):
                catalog.initialize()
                ledger.initialize()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM received_evidence').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM frozen_routes').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM published_reports').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM report_receipts').fetchone()[0], 1)
            self.assertEqual(get_received_evidence(catalog, alpha.identity), alpha)
            self.assertEqual(read_frozen_route(catalog, route.route_id), route)
            self.assertEqual(read_report(ledger, report.report_id), report)
