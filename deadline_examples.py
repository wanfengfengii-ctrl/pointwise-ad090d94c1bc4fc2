"""Observation fixtures and their V1 and deadline results."""
from contextlib import closing
from fractions import Fraction as F
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from rework.analysis.assessment import publish_assessment
from rework.analysis.deadline_assessment import publish_deadline_assessment
from rework.process.revision_store import RevisionStore
from rework.process.revisions import freeze_process
from rework.report.ledger import ReportLedger, read_deadline_report
from rework.routing.assignments import RouteAssignment, TerminalDisposition
from rework.routing.catalog import RoutingCatalog
from rework.routing.deadline_intake import receive_deadline_evidence
from rework.routing.plans import freeze_route
from rework.station.deadline_codec import decode_deadline_evidence
from rework.station.deadline_issue import issue_deadline_evidence
from rework.station.issue import StationEvidenceStore, issue_evidence
from tests.support import alpha_batch, batch, beta_batch, port, receive_piece, two_station_route, values


def same_moment_batches():
    return tuple(
        batch("Alpha", [("bench", "send", minute) for minute in minutes])
        for minutes in ((1, 3), (0, 2, 2, 2, 2, 2, 2, 4))
    )


def zero_return_batches():
    alpha = batch("Alpha", (("bench", "bench", 0), ("bench", "send", 0)),
                  entries=(("start", "bench"), ("alternate", "bench")))
    beta = batch("Beta", (
        ("bench", "qualified", 0), ("bench", "qualified", 0),
        ("bench", "return", 0), ("bench", "loop", 0), ("loop", "loop", 0),
    ), exits=("qualified", "return", "discard"), workstations=("bench", "loop"),
        entries=(("start", "bench"), ("trapped", "loop")))
    return alpha, beta


def issue_v1(connection, sample):
    revisions = RevisionStore(connection)
    issued = StationEvidenceStore(connection)
    revisions.initialize()
    issued.initialize()
    revision = freeze_process(revisions, revisions.save_draft(sample).draft_id)
    return issue_evidence(revisions, issued, revision.revision_id)


def issue_v1_and_companion(path, sample, coverage):
    """Station open: bind a frozen revision into a V1 piece and one companion."""
    with closing(sqlite3.connect(path)) as connection:
        revisions = RevisionStore(connection)
        issued = StationEvidenceStore(connection)
        revisions.initialize()
        issued.initialize()
        revision = freeze_process(revisions, revisions.save_draft(sample).draft_id)
        piece = issue_evidence(revisions, issued, revision.revision_id)
        companion_payload = issue_deadline_evidence(
            revisions, issued, piece.identity.evidence_id, coverage)
        return piece, decode_deadline_evidence(companion_payload), companion_payload


def require_equal(label, actual, expected):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, found {actual!r}")
    print(f"{label}: {actual}")


def run_v1(connect):
    with closing(connect("center")) as center:
        catalog = RoutingCatalog(center)
        ledger = ReportLedger(center)
        catalog.initialize()
        ledger.initialize()

        def bring(name, sample):
            with closing(connect(name)) as source:
                piece = issue_v1(source, sample)
            return receive_piece(catalog, piece)

        for name, sample in zip(("same-a", "same-b"), same_moment_batches()):
            piece = bring(name, sample)
            row, = piece.rows
            require_equal(name + " V1 exit evidence",
                          (row.probability, row.first, row.second), (F(1), F(2), F(5)))
            route = freeze_route(catalog, (piece.identity.evidence_id,), (
                RouteAssignment(port(piece, "send"), TerminalDisposition.PASS),
            ))
            report = publish_assessment(catalog, ledger, route.route_id, port(piece))
            require_equal(name + " V1 report", values(report), (F(1), F(2), F(1)))

        cases = (
            ("positive", (alpha_batch(), beta_batch()), (F(2, 3), F(10, 3), F(4, 9))),
            ("zero", zero_return_batches(), (F(2, 3), F(0), F(0))),
        )
        for name, (alpha_sample, beta_sample), expected in cases:
            alpha = bring(name + "-alpha", alpha_sample)
            beta = bring(name + "-beta", beta_sample)
            route = two_station_route(catalog, alpha, beta, returning=True)
            report = publish_assessment(catalog, ledger, route.route_id, port(alpha))
            require_equal(name + " V1 offline report", values(report), expected)
            if name == "zero":
                trapped = publish_assessment(catalog, ledger, route.route_id, port(beta, "trapped"))
                require_equal("trapped V1 offline report", values(trapped), (F(0), None, None))


def run_deadline(root):
    with closing(sqlite3.connect(root / "center")) as center:
        catalog = RoutingCatalog(center)
        ledger = ReportLedger(center)
        catalog.initialize()
        ledger.initialize()

        def bring(path, sample, coverage):
            # The station database is opened only to issue, then closed; only the
            # public V1 and companion bytes travel to the center.
            piece, _, payload = issue_v1_and_companion(path, sample, coverage)
            receive_piece(catalog, piece)
            companion_id = receive_deadline_evidence(catalog, payload)
            return piece, companion_id

        # Same-moment batches: direct pass with a one-minute deadline.
        for name, sample, expected in (
            ("deadline-a", same_moment_batches()[0], F(1, 2)),
            ("deadline-b", same_moment_batches()[1], F(1, 8)),
        ):
            piece, companion_id = bring(root / (name + ".db"), sample, 1)
            route = freeze_route(catalog, (piece.identity.evidence_id,), (
                RouteAssignment(port(piece, "send"), TerminalDisposition.PASS),
            ))
            report = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(piece), 1, (companion_id,))
            require_equal(name + " deadline probability", report.probability, expected)

        # Two-station returning route: probabilities at limits 2, 3 and 4.
        alpha_piece, alpha_id = bring(root / "deadline-alpha.db", alpha_batch(), 4)
        beta_piece, beta_id = bring(root / "deadline-beta.db", beta_batch(), 4)
        route = two_station_route(catalog, alpha_piece, beta_piece, returning=True)
        curve = {}
        for limit in (2, 3, 4):
            report = publish_deadline_assessment(
                catalog, ledger, route.route_id, port(alpha_piece),
                limit, (alpha_id, beta_id))
            curve[limit] = report.probability
        require_equal("returning deadline curve",
                      tuple(curve.values()), (F(0), F(1, 2), F(5, 8)))
        report_id = report.report_id

        # Zero-minute returns at a zero-minute deadline.
        zero_alpha, zero_beta = zero_return_batches()
        z_alpha, z_alpha_id = bring(root / "deadline-zero-alpha.db", zero_alpha, 0)
        z_beta, z_beta_id = bring(root / "deadline-zero-beta.db", zero_beta, 0)
        zero_route = two_station_route(catalog, z_alpha, z_beta, returning=True)
        zero_results = tuple(
            publish_deadline_assessment(
                catalog, ledger, zero_route.route_id, start, 0,
                (z_alpha_id, z_beta_id)).probability
            for start in (port(z_alpha, "start"), port(z_alpha, "alternate"),
                          port(z_beta, "trapped"))
        )
        require_equal("zero-minute deadline entries",
                      zero_results, (F(2, 3), F(2, 3), F(0)))

    # Reopen the center and collect the saved curve report by its original number.
    with closing(sqlite3.connect(root / "center")) as center:
        ledger = ReportLedger(center)
        ledger.initialize()
        reloaded = read_deadline_report(ledger, report_id)
        require_equal("reopened deadline report",
                      (reloaded.limit, reloaded.probability), (4, F(5, 8)))


def main():
    with TemporaryDirectory() as directory:
        root = Path(directory)

        def connect(name):
            return sqlite3.connect(root / name)

        run_v1(connect)
        run_deadline(root)


if __name__ == "__main__":
    main()
