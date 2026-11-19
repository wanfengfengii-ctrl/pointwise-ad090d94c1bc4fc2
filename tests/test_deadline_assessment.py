from fractions import Fraction as F

from rework.analysis.deadline_assessment import publish_deadline_assessment
from rework.report.ledger import read_deadline_report
from rework.routing.assignments import RouteAssignment, TerminalDisposition
from rework.routing.deadline_intake import receive_deadline_evidence
from rework.routing.plans import freeze_route
from rework.station.deadline_codec import decode_deadline_evidence

from deadline_examples import same_moment_batches, zero_return_batches
from tests.support import (
    ProjectCase, alpha_batch, batch, beta_batch, port, receive_piece, two_station_route,
)


def companion_for(case, name, sample, coverage):
    piece, _, payload = case.issue_with_companion(name, sample, coverage=coverage)
    return piece, payload


class TestDeadlineAssessment(ProjectCase):
    def _route_with_companions(self, alpha_sample, beta_sample, coverage=4):
        alpha, alpha_payload = companion_for(self, 'alpha', alpha_sample, coverage)
        beta, beta_payload = companion_for(self, 'beta', beta_sample, coverage)
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, alpha)
            receive_piece(catalog, beta)
            alpha_id = receive_deadline_evidence(catalog, alpha_payload)
            beta_id = receive_deadline_evidence(catalog, beta_payload)
            route = two_station_route(catalog, alpha, beta, returning=True)
        # Companion numbers are returned in the frozen route's piece order.
        numbers = {alpha.identity.evidence_id: alpha_id, beta.identity.evidence_id: beta_id}
        ordered = tuple(numbers[identity.evidence_id] for identity in route.pieces)
        return route, (alpha, beta), ordered

    def test_same_moment_batches_direct_pass(self):
        expected = {'a': F(1, 2), 'b': F(1, 8)}
        for name, sample in zip(('a', 'b'), same_moment_batches()):
            piece, payload = companion_for(self, name, sample, coverage=1)
            with self.center() as (_, catalog, ledger):
                receive_piece(catalog, piece)
                companion_id = receive_deadline_evidence(catalog, payload)
                route = freeze_route(catalog, (piece.identity.evidence_id,), (
                    RouteAssignment(port(piece, 'send'), TerminalDisposition.PASS),
                ))
                report = publish_deadline_assessment(
                    catalog, ledger, route.route_id, port(piece), 1, (companion_id,))
                self.assertEqual(report.probability, expected[name])
                self.assertEqual(report.limit, 1)
                self.assertEqual(report.companion_ids, (companion_id,))
                self.assertEqual(report.pieces, (piece.identity,))

    def test_returning_route_deadline_curve(self):
        route, pieces, companion_ids = self._route_with_companions(
            alpha_batch(), beta_batch(), coverage=4)
        with self.center() as (_, catalog, ledger):
            actual = {}
            for limit in (0, 1, 2, 3, 4):
                report = publish_deadline_assessment(
                    catalog, ledger, route.route_id, port(pieces[0]),
                    limit, companion_ids)
                actual[limit] = report.probability
            self.assertEqual(actual, {
                0: F(0), 1: F(0), 2: F(0), 3: F(1, 2), 4: F(5, 8),
            })
            self.assertTrue(all(isinstance(value, F) for value in actual.values()))

    def test_zero_return_entries_and_trapped_start(self):
        alpha_sample, beta_sample = zero_return_batches()
        route, pieces, companion_ids = self._route_with_companions(
            alpha_sample, beta_sample, coverage=0)
        with self.center() as (_, catalog, ledger):
            start = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(pieces[0], 'start'),
                0, companion_ids)
            alternate = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(pieces[0], 'alternate'),
                0, companion_ids)
            trapped = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(pieces[1], 'trapped'),
                0, companion_ids)
            self.assertEqual(start.probability, F(2, 3))
            self.assertEqual(alternate.probability, F(2, 3))
            self.assertEqual(trapped.probability, F(0))
            # Zero qualifying mass is still issued and stored.
            self.assertEqual(read_deadline_report(ledger, trapped.report_id), trapped)

    def test_inclusive_limit_counts_exact_arrival(self):
        # One piece whose only path takes exactly two minutes.
        deterministic = batch(
            'Beta', [('bench', 'qualified', 2)], exits=('qualified',))
        piece, payload = companion_for(self, 'beta', deterministic, coverage=2)
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, piece)
            companion_id = receive_deadline_evidence(catalog, payload)
            route = freeze_route(catalog, (piece.identity.evidence_id,), (
                RouteAssignment(port(piece, 'qualified'), TerminalDisposition.PASS),
            ))
            one = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(piece), 1, (companion_id,))
            two = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(piece), 2, (companion_id,))
            self.assertEqual(one.probability, F(0))
            self.assertEqual(two.probability, F(1))

    def test_missing_entry_mass_still_publishes(self):
        # An entry that can never leave has no companion records but is valid.
        sample = batch('Alpha', (
            ('bench', 'loop', 0), ('bench', 'send', 4), ('loop', 'loop', 0),
        ), workstations=('bench', 'loop'),
            entries=(('start', 'bench'), ('trapped', 'loop')))
        piece, payload = companion_for(self, 'alpha', sample, coverage=2)
        companion = decode_deadline_evidence(payload)
        self.assertFalse(any(record.entry == 'trapped' for record in companion.data))
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, piece)
            companion_id = receive_deadline_evidence(catalog, payload)
            route = freeze_route(catalog, (piece.identity.evidence_id,), (
                RouteAssignment(port(piece, 'send'), TerminalDisposition.PASS),
            ))
            trapped = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(piece, 'trapped'),
                2, (companion_id,))
            start = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(piece, 'start'),
                2, (companion_id,))
            self.assertEqual(trapped.probability, F(0))
            self.assertEqual(start.probability, F(0))

    def test_companion_selection_validation(self):
        route, pieces, companion_ids = self._route_with_companions(
            alpha_batch(), beta_batch(), coverage=4)
        alpha_id, beta_id = companion_ids
        with self.center() as (db, catalog, ledger):
            for bad_ids, reason in (
                ((alpha_id,), 'too few companions'),
                ((alpha_id, beta_id, alpha_id), 'duplicate companion'),
                ((), 'no companions'),
                ((alpha_id, 'deadline-missing'), 'unknown companion'),
            ):
                with self.subTest(reason=reason):
                    with self.assertRaises((ValueError, KeyError)):
                        publish_deadline_assessment(
                            catalog, ledger, route.route_id, port(pieces[0]),
                            4, bad_ids)
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM published_deadline_reports').fetchone()[0], 0)

    def test_coverage_below_limit_rejected(self):
        # A companion covering only one minute cannot support a four-minute limit.
        alpha_piece, alpha_payload = companion_for(self, 'alpha', alpha_batch(), 4)
        beta_piece, beta_payload = companion_for(self, 'beta', beta_batch(), 1)
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, alpha_piece)
            receive_piece(catalog, beta_piece)
            alpha_id = receive_deadline_evidence(catalog, alpha_payload)
            short_id = receive_deadline_evidence(catalog, beta_payload)
            route = two_station_route(catalog, alpha_piece, beta_piece, returning=True)
            with self.assertRaisesRegex(ValueError, 'coverage is below'):
                publish_deadline_assessment(
                    catalog, ledger, route.route_id, port(alpha_piece),
                    4, (alpha_id, short_id))

    def test_companion_bound_to_other_piece_rejected(self):
        route, pieces, companion_ids = self._route_with_companions(
            alpha_batch(), beta_batch(), coverage=4)
        alpha_id, _ = companion_ids
        foreign_piece, _, foreign_payload = self.issue_with_companion(
            'other', alpha_batch(), coverage=4)
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, foreign_piece)
            foreign_id = receive_deadline_evidence(catalog, foreign_payload)
            with self.assertRaisesRegex(ValueError, 'does not match the frozen route'):
                publish_deadline_assessment(
                    catalog, ledger, route.route_id, port(pieces[0]),
                    4, (alpha_id, foreign_id))

    def test_invalid_limit_and_start(self):
        route, pieces, companion_ids = self._route_with_companions(
            alpha_batch(), beta_batch(), coverage=4)
        with self.center() as (_, catalog, ledger):
            for bad_limit in (-1, True, 1.5, '4'):
                with self.subTest(bad_limit=bad_limit):
                    with self.assertRaises(ValueError):
                        publish_deadline_assessment(
                            catalog, ledger, route.route_id, port(pieces[0]),
                            bad_limit, companion_ids)
            with self.assertRaises(ValueError):
                publish_deadline_assessment(
                    catalog, ledger, route.route_id, port(pieces[0], 'send'),
                    4, companion_ids)

    def test_unknown_route_and_report_are_key_errors(self):
        route, pieces, companion_ids = self._route_with_companions(
            alpha_batch(), beta_batch(), coverage=4)
        with self.center() as (_, catalog, ledger):
            with self.assertRaises(KeyError):
                publish_deadline_assessment(
                    catalog, ledger, 999, port(pieces[0]), 4, companion_ids)
            with self.assertRaises(KeyError):
                read_deadline_report(ledger, 'deadline-report-missing')

    def test_snapshot_shape_and_reopen_read(self):
        route, pieces, companion_ids = self._route_with_companions(
            alpha_batch(), beta_batch(), coverage=4)
        with self.center() as (_, catalog, ledger):
            report = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(pieces[0]),
                4, companion_ids)
            snapshot_attrs = {
                'report_id', 'route_id', 'start', 'limit', 'pieces',
                'companion_ids', 'probability',
            }
            self.assertEqual(set(vars(report)), snapshot_attrs)
            self.assertEqual(report.route_id, route.route_id)
            self.assertEqual(report.start, port(pieces[0]))
            self.assertEqual(report.pieces, route.pieces)
            self.assertEqual(len(report.companion_ids), len(route.pieces))
        with self.center() as (db, catalog2, ledger2):
            reloaded = read_deadline_report(ledger2, report.report_id)
            self.assertEqual(reloaded, report)
            self.assertEqual(reloaded.probability, F(5, 8))
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM deadline_report_receipts').fetchone()[0], 1)

    def test_correction_then_reopen_keeps_old_values(self):
        route, pieces, companion_ids = self._route_with_companions(
            alpha_batch(), beta_batch(), coverage=4)
        with self.center() as (_, catalog, ledger):
            original = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(pieces[0]),
                4, companion_ids)
        # The source corrects Beta and issues a fresh V1 piece plus companion.
        corrected_piece, _, corrected_payload = self.issue_with_companion(
            'beta-new', beta_batch(pass_minutes=5), coverage=4)
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, corrected_piece)
            corrected_id = receive_deadline_evidence(catalog, corrected_payload)
            new_route = two_station_route(catalog, pieces[0], corrected_piece, returning=True)
            corrected_numbers = {
                pieces[0].identity.evidence_id: companion_ids[
                    tuple(route.pieces).index(pieces[0].identity)],
                corrected_piece.identity.evidence_id: corrected_id,
            }
            ordered_corrected = tuple(
                corrected_numbers[identity.evidence_id] for identity in new_route.pieces)
            corrected = publish_deadline_assessment(
                catalog, ledger, new_route.route_id, port(pieces[0]),
                4, ordered_corrected)
            old = read_deadline_report(ledger, original.report_id)
            self.assertEqual(old, original)
            self.assertEqual(old.probability, F(5, 8))
            self.assertEqual(old.companion_ids, companion_ids)
            self.assertEqual(corrected.pieces, new_route.pieces)
