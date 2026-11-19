import json

from rework.routing.assignments import RouteAssignment, TerminalDisposition
from rework.routing.intake import get_received_evidence, receive_evidence
from rework.routing.plans import freeze_route, read_frozen_route
from rework.routing.port_checks import PortRef
from rework.station.codec import encode_evidence

from tests.support import ProjectCase, alpha_batch, batch, port, receive_piece


class TestRouting(ProjectCase):
    def test_unknown_port(self):
        alpha = self.issue('alpha', alpha_batch())
        with self.center() as (db, catalog, _):
            receive_piece(catalog, alpha)
            invalid = RouteAssignment(port(alpha, 'send'), port(alpha, 'missing'))
            with self.assertRaisesRegex(ValueError, 'outside the selected'):
                freeze_route(catalog, [alpha.identity.evidence_id], [invalid])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM frozen_routes').fetchone()[0], 0)

    def test_same_name_wrong_piece(self):
        old = self.issue('alpha', alpha_batch())
        new = self.issue('alpha', batch('Alpha', [('bench', 'send', 4)]))
        with self.center() as (db, catalog, _):
            receive_piece(catalog, old)
            receive_piece(catalog, new)
            self.assertEqual(old.entries, new.entries)
            with self.assertRaises(ValueError):
                freeze_route(catalog, [old.identity.evidence_id], [RouteAssignment(port(old, 'send'), port(new))])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM frozen_routes').fetchone()[0], 0)
            route = freeze_route(catalog, [old.identity.evidence_id], [RouteAssignment(port(old, 'send'), port(old))])
            self.assertEqual(read_frozen_route(catalog, route.route_id), route)
            self.assertEqual(route.pieces, (old.identity,))

    def test_invalid_assignment(self):
        alpha = self.issue('alpha', alpha_batch())
        assignment = RouteAssignment(port(alpha, 'send'), TerminalDisposition.PASS)
        with self.center() as (db, catalog, _):
            receive_piece(catalog, alpha)
            for wiring in ([], [assignment, assignment], [RouteAssignment(assignment.exit, 'pass')],
                           [RouteAssignment(PortRef(alpha.identity.evidence_id, 'start'), TerminalDisposition.PASS)]):
                with self.subTest(wiring=wiring), self.assertRaises(ValueError):
                    freeze_route(catalog, [alpha.identity.evidence_id], wiring)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM frozen_routes').fetchone()[0], 0)
            route = freeze_route(catalog, [alpha.identity.evidence_id], [assignment])
            self.assertEqual(route.assignments, (assignment,))

    def test_repeat_intake(self):
        piece = self.issue('alpha', alpha_batch())
        payload = encode_evidence(piece)
        with self.center() as (db, catalog, _):
            self.assertEqual(receive_evidence(catalog, payload), piece)
            self.assertEqual(receive_evidence(catalog, json.dumps(json.loads(payload), indent=2).encode()), piece)
            changed = json.loads(payload)
            changed['rows'][0][-2:] = ['2', '4']
            with self.assertRaisesRegex(ValueError, 'different content'):
                receive_evidence(catalog, json.dumps(changed).encode())
            with self.assertRaises(ValueError):
                receive_evidence(catalog, b'{')
            changed['version'] = True
            with self.assertRaises(ValueError):
                receive_evidence(catalog, json.dumps(changed).encode())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM received_evidence').fetchone()[0], 1)
            self.assertEqual(get_received_evidence(catalog, piece.identity), piece)
