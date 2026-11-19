"""Cross-engine and structural properties of deadline assessments."""
from fractions import Fraction as F

from rework.analysis.assessment import publish_assessment
from rework.analysis.deadline_assessment import publish_deadline_assessment
from rework.routing.assignments import RouteAssignment, TerminalDisposition
from rework.routing.deadline_intake import receive_deadline_evidence
from rework.routing.plans import freeze_route

from deadline_examples import zero_return_batches
from tests.support import (
    ProjectCase, alpha_batch, batch, beta_batch, port, receive_piece, two_station_route,
)


class TestDeadlineProperties(ProjectCase):
    def test_monotone_curve_matches_analytic_geometric_curve(self):
        alpha_piece, _, alpha_comp = self.issue_with_companion('alpha', alpha_batch(), 12)
        beta_piece, _, beta_comp = self.issue_with_companion('beta', beta_batch(), 12)
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, alpha_piece)
            receive_piece(catalog, beta_piece)
            alpha_id = receive_deadline_evidence(catalog, alpha_comp)
            beta_id = receive_deadline_evidence(catalog, beta_comp)
            route = two_station_route(catalog, alpha_piece, beta_piece, returning=True)

            def analytic(limit):
                # First qualification takes three minutes.  Each return adds one
                # further minute (Alpha's leg; Beta's return edge is zero-minute),
                # so the k-th return path passes at 3 + k with weight (1/2)(1/4)^k.
                return sum(F(1, 2) * F(1, 4) ** k
                           for k in range(0, 100) if 3 + k <= limit)

            curve = []
            for limit in range(0, 13):
                report = publish_deadline_assessment(
                    catalog, ledger, route.route_id, port(alpha_piece),
                    limit, (alpha_id, beta_id))
                curve.append(report.probability)
                self.assertEqual(report.probability, analytic(limit))
            # The cumulative curve is non-decreasing and stays below the V1 limit.
            for earlier, later in zip(curve, curve[1:]):
                self.assertLessEqual(earlier, later)
            v1 = publish_assessment(catalog, ledger, route.route_id, port(alpha_piece))
            self.assertEqual(v1.probability, F(2, 3))
            self.assertLess(curve[-1], v1.probability)

    def test_zero_deadline_agrees_with_zero_minute_v1_edges(self):
        zero_alpha, zero_beta = zero_return_batches()
        alpha_piece, _, alpha_comp = self.issue_with_companion('alpha', zero_alpha, 6)
        beta_piece, _, beta_comp = self.issue_with_companion('beta', zero_beta, 6)
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, alpha_piece)
            receive_piece(catalog, beta_piece)
            alpha_id = receive_deadline_evidence(catalog, alpha_comp)
            beta_id = receive_deadline_evidence(catalog, beta_comp)
            route = two_station_route(catalog, alpha_piece, beta_piece, returning=True)
            start = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(alpha_piece, 'start'),
                0, (alpha_id, beta_id)).probability
            self.assertEqual(start, F(2, 3))
            # Every minute is zero, so a larger finite limit yields the same value.
            later = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(alpha_piece, 'start'),
                6, (alpha_id, beta_id))
            self.assertEqual(later.probability, F(2, 3))

    def test_scrap_and_timeout_mass_never_qualifies(self):
        # Half the mass scraps immediately; the surviving half needs one minute.
        sample = batch('Beta', (
            ('bench', 'qualified', 1), ('bench', 'discard', 0),
        ), exits=('qualified', 'discard'))
        piece, _, payload = self.issue_with_companion('beta', sample, 2)
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, piece)
            companion_id = receive_deadline_evidence(catalog, payload)
            route = freeze_route(catalog, (piece.identity.evidence_id,), (
                RouteAssignment(port(piece, 'qualified'), TerminalDisposition.PASS),
                RouteAssignment(port(piece, 'discard'), TerminalDisposition.SCRAP),
            ))
            zero = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(piece), 0, (companion_id,))
            one = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(piece), 1, (companion_id,))
            self.assertEqual(zero.probability, F(0))
            self.assertEqual(one.probability, F(1, 2))

    def test_companion_never_exceeds_total_probability_one(self):
        # A long returning route; every reported curve value stays within [0, 1].
        alpha_piece, _, alpha_comp = self.issue_with_companion('alpha', alpha_batch(), 10)
        beta_piece, _, beta_comp = self.issue_with_companion('beta', beta_batch(), 10)
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, alpha_piece)
            receive_piece(catalog, beta_piece)
            alpha_id = receive_deadline_evidence(catalog, alpha_comp)
            beta_id = receive_deadline_evidence(catalog, beta_comp)
            route = two_station_route(catalog, alpha_piece, beta_piece, returning=True)
            for limit in range(0, 11):
                probability = publish_deadline_assessment(
                    catalog, ledger, route.route_id, port(alpha_piece),
                    limit, (alpha_id, beta_id)).probability
                self.assertTrue(F(0) <= probability <= F(1))
