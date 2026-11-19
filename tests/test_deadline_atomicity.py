import sqlite3

from rework.analysis.deadline_assessment import publish_deadline_assessment
from rework.process.revisions import freeze_process
from rework.report.ledger import read_deadline_report
from rework.routing.deadline_intake import receive_deadline_evidence
from rework.station.deadline_codec import decode_deadline_evidence
from rework.station.deadline_issue import issue_deadline_evidence
from rework.station.issue import issue_evidence

from tests.support import ProjectCase, alpha_batch, beta_batch, port, receive_piece, two_station_route


class TestDeadlineAtomicity(ProjectCase):
    def _admit(self, catalog, piece, payload):
        receive_piece(catalog, piece)
        return receive_deadline_evidence(catalog, payload)

    def test_station_issue_commit_failure_leaves_no_row(self):
        with self.station('alpha') as (db, revisions, issued):
            revision = freeze_process(revisions, revisions.save_draft(alpha_batch()).draft_id)
            piece = issue_evidence(revisions, issued, revision.revision_id)
            db.execute('''
                CREATE TRIGGER block_deadline AFTER INSERT ON issued_deadline_evidence
                BEGIN
                    INSERT INTO no_such_table VALUES (1);
                END;
            ''')
            with self.assertRaises(sqlite3.OperationalError):
                issue_deadline_evidence(revisions, issued, piece.identity.evidence_id, 2)
            self.assertFalse(db.in_transaction)
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM issued_deadline_evidence').fetchone()[0], 0)
            db.execute('DROP TRIGGER block_deadline')
            # Retrying after the failure succeeds with no partial row left behind.
            payload = issue_deadline_evidence(revisions, issued, piece.identity.evidence_id, 2)
            self.assertEqual(decode_deadline_evidence(payload).coverage, 2)
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM issued_deadline_evidence').fetchone()[0], 1)

    def test_intake_commit_failure_leaves_no_row(self):
        with self.center() as (db, catalog, _):
            issued_piece, _, companion_payload = self.issue_with_companion(
                'alpha', alpha_batch(), coverage=2)
            receive_piece(catalog, issued_piece)
            db.execute('''
                CREATE TRIGGER block_companion AFTER INSERT ON received_deadline_evidence
                BEGIN
                    INSERT INTO no_such_table VALUES (1);
                END;
            ''')
            with self.assertRaises(sqlite3.OperationalError):
                receive_deadline_evidence(catalog, companion_payload)
            self.assertFalse(db.in_transaction)
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM received_deadline_evidence').fetchone()[0], 0)
            db.execute('DROP TRIGGER block_companion')
            companion_id = receive_deadline_evidence(catalog, companion_payload)
            self.assertTrue(companion_id)
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM received_deadline_evidence').fetchone()[0], 1)

    def test_publish_commit_failure_is_retryable(self):
        alpha_piece, _, alpha_comp = self.issue_with_companion('alpha', alpha_batch(), 4)
        beta_piece, _, beta_comp = self.issue_with_companion('beta', beta_batch(), 4)
        with self.center() as (db, catalog, ledger):
            alpha_id = self._admit(catalog, alpha_piece, alpha_comp)
            beta_id = self._admit(catalog, beta_piece, beta_comp)
            route = two_station_route(catalog, alpha_piece, beta_piece, returning=True)
            db.execute('PRAGMA foreign_keys = ON')
            db.executescript('''
                CREATE TABLE approval_gate (report_id TEXT PRIMARY KEY);
                CREATE TABLE deferred_approval (
                    report_id TEXT NOT NULL REFERENCES approval_gate(report_id)
                    DEFERRABLE INITIALLY DEFERRED
                );
                CREATE TRIGGER require_deadline_approval
                AFTER INSERT ON published_deadline_reports
                BEGIN
                    INSERT INTO deferred_approval VALUES (NEW.report_id);
                END;
            ''')
            with self.assertRaises(sqlite3.IntegrityError):
                publish_deadline_assessment(
                    catalog, ledger, route.route_id, port(alpha_piece),
                    4, (alpha_id, beta_id))
            self.assertFalse(db.in_transaction)
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM published_deadline_reports').fetchone()[0], 0)
            db.execute('DROP TRIGGER require_deadline_approval')
            report = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(alpha_piece),
                4, (alpha_id, beta_id))
            self.assertEqual(read_deadline_report(ledger, report.report_id), report)
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM published_deadline_reports').fetchone()[0], 1)

    def test_failed_validation_inserts_nothing(self):
        alpha_piece, _, alpha_comp = self.issue_with_companion('alpha', alpha_batch(), 4)
        beta_piece, _, beta_comp = self.issue_with_companion('beta', beta_batch(), 4)
        with self.center() as (db, catalog, ledger):
            alpha_id = self._admit(catalog, alpha_piece, alpha_comp)
            beta_id = self._admit(catalog, beta_piece, beta_comp)
            route = two_station_route(catalog, alpha_piece, beta_piece, returning=True)
            for bad_limit in (-1, True):
                with self.assertRaises(ValueError):
                    publish_deadline_assessment(
                        catalog, ledger, route.route_id, port(alpha_piece),
                        bad_limit, (alpha_id, beta_id))
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM published_deadline_reports').fetchone()[0], 0)
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM deadline_report_receipts').fetchone()[0], 0)
            with self.assertRaises(KeyError):
                read_deadline_report(ledger, 'deadline-report-unknown')
