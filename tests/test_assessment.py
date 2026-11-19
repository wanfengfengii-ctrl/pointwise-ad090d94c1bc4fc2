import json
from fractions import Fraction as F

from rework.analysis.assessment import publish_assessment
from rework.report.ledger import read_report
from rework.routing.assignments import RouteAssignment, TerminalDisposition
from rework.routing.plans import freeze_route
from rework.station.codec import encode_evidence

from tests.support import (
    ProjectCase, alpha_batch, batch, port, receive_foreign, receive_piece,
    two_station_route, values, wire_values,
)


class TestAssessment(ProjectCase):
    def test_linear_route(self):
        alpha = self.issue('alpha', alpha_batch())
        beta = self.issue('beta', batch('Beta', [('bench', 'qualified', 2)], exits=('qualified',)))
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, alpha)
            receive_piece(catalog, beta)
            route = two_station_route(catalog, alpha, beta)
            snapshot = publish_assessment(catalog, ledger, route.route_id, port(alpha))
            self.assertEqual(values(snapshot), (F(1), F(3), F(0)))
            self.assertTrue(all(isinstance(value, F) for value in values(snapshot)))
            self.assertEqual(snapshot.provenance.start, port(alpha))
            self.assertEqual(set(snapshot.provenance.pieces), {alpha.identity, beta.identity})
            self.assertEqual(read_report(ledger, snapshot.report_id), snapshot)

    def test_duration_variance(self):
        alpha = self.issue('alpha', alpha_batch())
        beta = self.issue('beta', batch('Beta', (
            ('bench', 'qualified', 0), ('bench', 'qualified', 0),
            ('bench', 'qualified', 0), ('bench', 'qualified', 4),
        ), exits=('qualified',)))
        selector = self.issue('selector', batch('Selector', (
            ('bench', 'send', 0), ('bench', 'loop', 0),
        ), exits=('send', 'loop')))
        with self.center() as (_, catalog, ledger):
            for piece in (alpha, beta, selector):
                receive_piece(catalog, piece)
            route = two_station_route(catalog, alpha, beta)
            snapshot = publish_assessment(catalog, ledger, route.route_id, port(alpha))
            self.assertEqual(values(snapshot), (F(1), F(2), F(3)))
            routed = freeze_route(catalog, [*([p.evidence_id for p in route.pieces]), selector.identity.evidence_id], (
                *route.assignments,
                RouteAssignment(port(selector, 'send'), port(alpha)),
                RouteAssignment(port(selector, 'loop'), port(selector)),
            ))
            # A departure to the selector's loop can later leave it, so all pieces still qualify.
            retried = publish_assessment(catalog, ledger, routed.route_id, port(selector))
            self.assertEqual(values(retried), (F(1), F(2), F(3)))
            closed = self.issue('trap', batch('Trap', [('bench', 'send', 2)]))
            receive_piece(catalog, closed)
            joint = freeze_route(catalog, [p.identity.evidence_id for p in (alpha, beta, selector, closed)], (
                *route.assignments,
                RouteAssignment(port(selector, 'send'), port(alpha)),
                RouteAssignment(port(selector, 'loop'), port(closed)),
                RouteAssignment(port(closed, 'send'), port(closed)),
            ))
            partial = publish_assessment(catalog, ledger, joint.route_id, port(selector))
            self.assertEqual(values(partial), (F(1, 2), F(2), F(3)))

    def test_return_and_scrap(self):
        alpha, beta = self.returning_pieces()
        expected = (F(2, 3), F(10, 3), F(4, 9))
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, alpha)
            receive_piece(catalog, beta)
            route = two_station_route(catalog, alpha, beta, returning=True)
            actual = publish_assessment(catalog, ledger, route.route_id, port(alpha))
            self.assertEqual(values(actual), expected, 'REWORK_REPORT_MISMATCH')
            readback = read_report(ledger, actual.report_id)
            self.assertEqual(readback, actual)
            self.assertEqual(set(readback.provenance.pieces), {alpha.identity, beta.identity})
            scenario = {
                'case_id': 'return_assessment',
                'input': {'alpha_external_minutes': 1, 'beta_observations': [
                    ['qualified', 2], ['qualified', 2], ['return', 0], ['discard', 0],
                ], 'return_target': 'Alpha/start'},
                'expected': wire_values(expected),
                'actual': wire_values(values(actual)),
                'downstream_expected': {'stored_statistics': wire_values(expected), 'selected_revisions_match': True},
                'downstream_actual': {'stored_statistics': wire_values(values(readback)),
                                      'selected_revisions_match': set(readback.provenance.pieces) == {alpha.identity, beta.identity}},
                'code_paths': ['rework/station/exit_analysis.py', 'rework/analysis/composition.py',
                               'rework/analysis/moments.py', 'rework/report/ledger.py'],
                'oracle': 'Success probability is (1/2)/(1-1/4). Successful time is 3 plus the geometric return count with ratio 1/4.',
            }
            print('POINTWISE_SCENARIO ' + json.dumps(scenario, sort_keys=True))

    def test_equal_marginals(self):
        alpha, beta = self.returning_pieces()
        _, swapped = self.returning_pieces(pass_minutes=0, other_minutes=2)
        self.assertEqual({row.exit: row.probability for row in beta.rows},
                         {row.exit: row.probability for row in swapped.rows})
        self.assertEqual((sum(row.first for row in beta.rows), sum(row.second for row in beta.rows)),
                         (sum(row.first for row in swapped.rows), sum(row.second for row in swapped.rows)))
        self.assertNotEqual(beta.rows, swapped.rows)
        with self.center() as (_, catalog, ledger):
            for piece in (alpha, beta, swapped):
                receive_piece(catalog, piece)
            observed = []
            for alternative in (beta, swapped):
                route = two_station_route(catalog, alpha, alternative, returning=True)
                observed.append(values(publish_assessment(catalog, ledger, route.route_id, port(alpha))))
            self.assertEqual(observed, [(F(2, 3), F(10, 3), F(4, 9)), (F(2, 3), F(2), F(4))])

    def test_valid_evidence_return(self):
        with self.center() as (_, catalog, ledger):
            alpha = receive_foreign(catalog, 'external-a', 'Alpha', ['send'], [
                ['start', 'send', '1', '1', '1'],
            ])
            beta = receive_foreign(catalog, 'external-b', 'Beta', ['qualified', 'return', 'discard'], [
                ['start', 'qualified', '1/2', '1', '2'],
                ['start', 'return', '1/4', '0', '0'],
                ['start', 'discard', '1/4', '0', '0'],
            ])
            route = two_station_route(catalog, alpha, beta, returning=True)
            snapshot = publish_assessment(catalog, ledger, route.route_id, port(alpha))
            self.assertEqual(values(snapshot), (F(2, 3), F(10, 3), F(4, 9)))

    def test_public_revisit(self):
        alpha, beta = self.returning_pieces(revisit=True)
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, alpha)
            receive_piece(catalog, beta)
            route = two_station_route(catalog, alpha, beta, returning=True)
            snapshot = publish_assessment(catalog, ledger, route.route_id, port(alpha))
            self.assertEqual(values(snapshot), (F(2, 3), F(10, 3), F(4, 9)))

    def test_closed_rework(self):
        closed = self.issue('alpha', batch('Alpha', [('bench', 'bench', 2)]))
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, closed)
            route = freeze_route(catalog, [closed.identity.evidence_id], [
                RouteAssignment(port(closed, 'send'), TerminalDisposition.PASS),
            ])
            snapshot = publish_assessment(catalog, ledger, route.route_id, port(closed))
            self.assertEqual(values(snapshot), (F(0), None, None))
            self.assertEqual(read_report(ledger, snapshot.report_id), snapshot)

    def test_partial_closed_class(self):
        alpha = self.issue('alpha', batch('Alpha', (
            ('bench', 'loop', 0), ('bench', 'send', 4), ('loop', 'loop', 1),
        ), workstations=('bench', 'loop'), entries=(('start', 'bench'), ('trapped', 'loop'))))
        with self.center() as (_, catalog, ledger):
            receive_piece(catalog, alpha)
            route = freeze_route(catalog, [alpha.identity.evidence_id], [
                RouteAssignment(port(alpha, 'send'), TerminalDisposition.PASS),
            ])
            snapshot = publish_assessment(catalog, ledger, route.route_id, port(alpha))
            self.assertEqual(values(snapshot), (F(1, 2), F(4), F(0)))
            trapped = publish_assessment(catalog, ledger, route.route_id, port(alpha, 'trapped'))
            self.assertEqual(values(trapped), (F(0), None, None))

    def test_invalid_input(self):
        alpha, beta = self.returning_pieces()
        with self.center() as (db, catalog, ledger):
            receive_piece(catalog, alpha)
            receive_piece(catalog, beta)
            route = two_station_route(catalog, alpha, beta, returning=True)
            with self.assertRaises(ValueError):
                publish_assessment(catalog, ledger, route.route_id, port(alpha, 'send'))
            with db:
                db.execute('DELETE FROM received_evidence WHERE evidence_id = ?', (beta.identity.evidence_id,))
            with self.assertRaises(KeyError):
                publish_assessment(catalog, ledger, route.route_id, port(alpha))
            receive_piece(catalog, beta)
            changed = json.loads(encode_evidence(beta))
            changed['rows'][0][-2:] = ['1/4', '1/4']
            with db:
                db.execute('UPDATE received_evidence SET payload = ? WHERE evidence_id = ?', (
                    json.dumps(changed).encode(), beta.identity.evidence_id,
                ))
            with self.assertRaisesRegex(ValueError, 'content has changed'):
                publish_assessment(catalog, ledger, route.route_id, port(alpha))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM published_reports').fetchone()[0], 0)
