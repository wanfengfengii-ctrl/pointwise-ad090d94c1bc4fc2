import json
import sqlite3
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from rework.process.observations import Observation, ObservationBatch
from rework.process.ports import ProcessPorts
from rework.process.revision_store import RevisionStore
from rework.process.revisions import freeze_process
from rework.report.ledger import ReportLedger
from rework.routing.assignments import RouteAssignment, TerminalDisposition
from rework.routing.catalog import RoutingCatalog
from rework.routing.intake import receive_evidence
from rework.routing.plans import freeze_route
from rework.routing.port_checks import PortRef
from rework.station.codec import encode_evidence
from rework.station.issue import StationEvidenceStore, issue_evidence


def batch(station, observations, *, exits=('send',), workstations=('bench',), entries=(('start', 'bench'),)):
    return ObservationBatch(station, ProcessPorts(workstations, entries, exits), tuple(
        Observation(*fields) for fields in observations
    ))


def alpha_batch(revisit=False):
    rows = [('bench', 'send', 1)]
    if revisit:
        rows.append(('bench', 'bench', 0))
    return batch('Alpha', rows)


def beta_batch(pass_minutes=2, other_minutes=0):
    return batch('Beta', (
        ('bench', 'qualified', pass_minutes), ('bench', 'qualified', pass_minutes),
        ('bench', 'return', other_minutes), ('bench', 'discard', other_minutes),
    ), exits=('qualified', 'return', 'discard'))


def port(piece, name='start'):
    return PortRef(piece.identity.evidence_id, name)


def values(report):
    return report.probability, report.mean, report.variance


def wire_values(result):
    return [None if number is None else str(number) for number in result]


def receive_piece(catalog, piece):
    return receive_evidence(catalog, encode_evidence(piece))


def receive_foreign(catalog, number, station, exits, rows):
    data = {
        'version': 1,
        'identity': {'evidence_id': number, 'station': station, 'revision_id': number + '-rev'},
        'entries': ['start'], 'exits': list(exits), 'rows': rows,
    }
    return receive_evidence(catalog, json.dumps(data).encode('utf-8'))


def two_station_route(catalog, alpha, beta, returning=False):
    wiring = [
        RouteAssignment(port(alpha, 'send'), port(beta)),
        RouteAssignment(port(beta, 'qualified'), TerminalDisposition.PASS),
    ]
    if returning:
        wiring.extend((
            RouteAssignment(port(beta, 'return'), port(alpha)),
            RouteAssignment(port(beta, 'discard'), TerminalDisposition.SCRAP),
        ))
    return freeze_route(catalog, (alpha.identity.evidence_id, beta.identity.evidence_id), wiring)


class ProjectCase(unittest.TestCase):
    def setUp(self):
        location = TemporaryDirectory()
        self.addCleanup(location.cleanup)
        self.root = Path(location.name)

    @contextmanager
    def station(self, name):
        with closing(sqlite3.connect(self.root / (name + '.sqlite'))) as connection:
            revisions = RevisionStore(connection)
            issued = StationEvidenceStore(connection)
            revisions.initialize()
            issued.initialize()
            yield connection, revisions, issued

    @contextmanager
    def center(self):
        with closing(sqlite3.connect(self.root / 'center.sqlite')) as connection:
            catalog = RoutingCatalog(connection)
            ledger = ReportLedger(connection)
            catalog.initialize()
            ledger.initialize()
            yield connection, catalog, ledger

    def issue(self, name, observation_batch):
        with self.station(name) as (_, revisions, issued):
            draft = revisions.save_draft(observation_batch)
            revision = freeze_process(revisions, draft.draft_id)
            return issue_evidence(revisions, issued, revision.revision_id)

    def returning_pieces(self, *, revisit=False, pass_minutes=2, other_minutes=0):
        return (
            self.issue('alpha', alpha_batch(revisit)),
            self.issue('beta', beta_batch(pass_minutes, other_minutes)),
        )
