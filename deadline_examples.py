"""Observation fixtures and their existing V1 results."""
from contextlib import closing
from fractions import Fraction as F
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from rework.analysis.assessment import publish_assessment
from rework.process.revision_store import RevisionStore
from rework.process.revisions import freeze_process
from rework.report.ledger import ReportLedger
from rework.routing.assignments import RouteAssignment, TerminalDisposition
from rework.routing.catalog import RoutingCatalog
from rework.routing.plans import freeze_route
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


def main():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        run_v1(lambda name: sqlite3.connect(root / (name + ".sqlite")))


if __name__ == "__main__":
    main()
