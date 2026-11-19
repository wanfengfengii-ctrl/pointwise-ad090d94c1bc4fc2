import json
import sqlite3
from contextlib import closing, contextmanager
from fractions import Fraction as F
from pathlib import Path
from tempfile import TemporaryDirectory

from rework.analysis.assessment import publish_assessment
from rework.analysis.deadline_assessment import publish_deadline_assessment
from rework.process.observations import Observation, ObservationBatch
from rework.process.ports import ProcessPorts
from rework.process.revision_store import RevisionStore
from rework.process.revisions import freeze_process, open_correction
from rework.report.export import export_report
from rework.report.ledger import ReportLedger, read_deadline_report, read_report
from rework.routing.assignments import RouteAssignment, TerminalDisposition
from rework.routing.catalog import RoutingCatalog
from rework.routing.deadline_intake import receive_deadline_evidence
from rework.routing.intake import receive_evidence
from rework.routing.plans import freeze_route
from rework.routing.port_checks import PortRef
from rework.station.codec import encode_evidence
from rework.station.deadline_issue import issue_deadline_evidence
from rework.station.issue import StationEvidenceStore, issue_evidence


def make_batch(station, exits, observations):
    ports = ProcessPorts(('workbench',), (('start', 'workbench'),), exits)
    return ObservationBatch(station, ports, tuple(Observation('workbench', exit_name, minutes)
                                                  for exit_name, minutes in observations))


def freeze_and_issue(path, batch, old_revision_id=None):
    with closing(sqlite3.connect(path)) as connection:
        revisions = RevisionStore(connection)
        issued = StationEvidenceStore(connection)
        revisions.initialize()
        issued.initialize()
        if old_revision_id is None:
            draft = revisions.save_draft(batch)
        else:
            draft = open_correction(revisions, old_revision_id, batch)
        revision = freeze_process(revisions, draft.draft_id)
        return issue_evidence(revisions, issued, revision.revision_id)


@contextmanager
def center(path):
    with closing(sqlite3.connect(path)) as connection:
        catalog = RoutingCatalog(connection)
        ledger = ReportLedger(connection)
        catalog.initialize()
        ledger.initialize()
        yield catalog, ledger


def assess(catalog, ledger, alpha, beta):
    alpha_id = alpha.identity.evidence_id
    beta_id = beta.identity.evidence_id
    for piece in (alpha, beta):
        receive_evidence(catalog, encode_evidence(piece))
    start = PortRef(alpha_id, 'start')
    route = freeze_route(catalog, (alpha_id, beta_id), (
        RouteAssignment(PortRef(alpha_id, 'send'), PortRef(beta_id, 'start')),
        RouteAssignment(PortRef(beta_id, 'qualified'), TerminalDisposition.PASS),
        RouteAssignment(PortRef(beta_id, 'return'), start),
        RouteAssignment(PortRef(beta_id, 'discard'), TerminalDisposition.SCRAP),
    ))
    return publish_assessment(catalog, ledger, route.route_id, start)


def statistics(report):
    return report.probability, report.mean, report.variance


def issue_with_deadline(path, batch, coverage, old_revision_id=None):
    """Open a station, freeze a revision, then issue V1 piece and companion."""
    with closing(sqlite3.connect(path)) as connection:
        revisions = RevisionStore(connection)
        issued = StationEvidenceStore(connection)
        revisions.initialize()
        issued.initialize()
        if old_revision_id is None:
            draft = revisions.save_draft(batch)
        else:
            draft = open_correction(revisions, old_revision_id, batch)
        revision = freeze_process(revisions, draft.draft_id)
        piece = issue_evidence(revisions, issued, revision.revision_id)
        companion = issue_deadline_evidence(
            revisions, issued, piece.identity.evidence_id, coverage)
        return piece, companion


def deadline_wiring(alpha_id, beta_id):
    start = PortRef(alpha_id, 'start')
    return start, (
        RouteAssignment(PortRef(alpha_id, 'send'), PortRef(beta_id, 'start')),
        RouteAssignment(PortRef(beta_id, 'qualified'), TerminalDisposition.PASS),
        RouteAssignment(PortRef(beta_id, 'return'), start),
        RouteAssignment(PortRef(beta_id, 'discard'), TerminalDisposition.SCRAP),
    )


def run_deadline_demo(root):
    alpha_file = root / 'deadline-alpha.sqlite'
    beta_file = root / 'deadline-beta.sqlite'
    center_file = root / 'deadline-center.sqlite'
    exits = ('qualified', 'return', 'discard')
    alpha_sample = make_batch('Alpha', ('send',), [('send', 1)])
    beta_sample = make_batch('Beta', exits, [
        ('qualified', 2), ('qualified', 2), ('return', 0), ('discard', 0),
    ])

    # Stations open only long enough to issue; then the source databases close.
    alpha, alpha_companion = issue_with_deadline(alpha_file, alpha_sample, 4)
    beta, beta_companion = issue_with_deadline(beta_file, beta_sample, 4)
    alpha_id = alpha.identity.evidence_id
    beta_id = beta.identity.evidence_id

    with center(center_file) as (catalog, ledger):
        receive_evidence(catalog, encode_evidence(alpha))
        receive_evidence(catalog, encode_evidence(beta))
        alpha_comp = receive_deadline_evidence(catalog, alpha_companion)
        beta_comp = receive_deadline_evidence(catalog, beta_companion)
        start, assignments = deadline_wiring(alpha_id, beta_id)
        route = freeze_route(catalog, (alpha_id, beta_id), assignments)
        curve = {}
        for limit in (2, 3, 4):
            report = publish_deadline_assessment(
                catalog, ledger, route.route_id, start, limit,
                (alpha_comp, beta_comp))
            curve[limit] = str(report.probability)
        report_id = report.report_id
        print('DEADLINE_OFFLINE_CURVE ' + json.dumps(curve, sort_keys=True))

    # Next day: the Beta source corrects its pass minutes and reissues.
    corrected, corrected_companion = issue_with_deadline(
        beta_file, make_batch('Beta', exits, [
            ('qualified', 5), ('qualified', 5), ('return', 0), ('discard', 0),
        ]), 4, old_revision_id=beta.identity.revision_id)
    corrected_id = corrected.identity.evidence_id
    with center(center_file) as (catalog, ledger):
        receive_evidence(catalog, encode_evidence(corrected))
        corrected_comp = receive_deadline_evidence(catalog, corrected_companion)
        start, assignments = deadline_wiring(alpha_id, corrected_id)
        new_route = freeze_route(catalog, (alpha_id, corrected_id), assignments)
        corrected_report = publish_deadline_assessment(
            catalog, ledger, new_route.route_id, start, 4,
            (alpha_comp, corrected_comp))

    # Reopen the center and collect yesterday's report by its original number.
    with center(center_file) as (_, ledger):
        old = read_deadline_report(ledger, report_id)
        scenario = {
            'case_id': 'deadline_review.offline_issue_reopen_claim',
            'curve_limits_2_3_4': curve,
            'old_report': {'report_id': old.report_id, 'limit': old.limit,
                           'probability': str(old.probability),
                           'companion_ids': list(old.companion_ids)},
            'corrected_report': {'limit': corrected_report.limit,
                                 'probability': str(corrected_report.probability),
                                 'companion_ids': list(corrected_report.companion_ids)},
            'old_value_preserved': str(old.probability) == '5/8',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(scenario, sort_keys=True))


def main():
    with TemporaryDirectory() as work:
        root = Path(work)
        alpha_file = root / 'alpha.sqlite'
        beta_file = root / 'beta.sqlite'
        center_file = root / 'center.sqlite'
        exits = ('qualified', 'return', 'discard')
        alpha = freeze_and_issue(alpha_file, make_batch('Alpha', ('send',), [('send', 1)]))
        beta = freeze_and_issue(beta_file, make_batch('Beta', exits, [
            ('qualified', 2), ('qualified', 2), ('return', 0), ('discard', 0),
        ]))
        with center(center_file) as (catalog, ledger):
            original = assess(catalog, ledger, alpha, beta)
            saved_bytes = export_report(read_report(ledger, original.report_id))
        replacement = freeze_and_issue(beta_file, make_batch('Beta', exits, [
            ('qualified', 5), ('qualified', 5), ('return', 0), ('discard', 0),
        ]), old_revision_id=beta.identity.revision_id)
        with center(center_file) as (catalog, ledger):
            corrected = assess(catalog, ledger, alpha, replacement)
        with center(center_file) as (_, ledger):
            old = read_report(ledger, original.report_id)
            new = read_report(ledger, corrected.report_id)
            expected_old = (F(2, 3), F(10, 3), F(4, 9))
            expected_new = (F(2, 3), F(19, 3), F(4, 9))
            old_unchanged = export_report(old) == saved_bytes and old == original
            new_origin = set(new.provenance.pieces) == {alpha.identity, replacement.identity}
            if statistics(old) != expected_old or statistics(new) != expected_new:
                raise AssertionError('REWORK_REPORT_MISMATCH')
            if not old_unchanged or not new_origin or new.provenance.start != old.provenance.start:
                raise AssertionError('report history or fixed provenance disagrees')
            print(export_report(old).decode('utf-8'), end='')
            print(export_report(new).decode('utf-8'), end='')
            print('POINTWISE_SCENARIO ' + json.dumps({
                'case_id': 'historical_review.same_entry_new_report',
                'input': {'old_beta_pass_minutes': 2, 'new_beta_pass_minutes': 5,
                          'alpha_external_minutes': 1, 'beta_return_probability': '1/4'},
                'expected': {'old': list(map(str, expected_old)), 'new': list(map(str, expected_new))},
                'actual': {'old': list(map(str, statistics(old))), 'new': list(map(str, statistics(new)))},
                'downstream_expected': {'old_export_unchanged': True, 'new_origin_matches': True},
                'downstream_actual': {'old_export_unchanged': old_unchanged, 'new_origin_matches': new_origin},
                'code_paths': ['rework/process/revisions.py', 'rework/station/issue.py',
                               'rework/analysis/assessment.py', 'rework/report/ledger.py', 'rework/report/export.py'],
                'oracle': 'The correction adds three minutes to each successful path, preserving probability and variance.',
            }, sort_keys=True))

        # Deadline flow: sources issue companions and close; the center signs
        # offline and still answers by the original number after a correction.
        run_deadline_demo(root)


if __name__ == '__main__':
    main()
