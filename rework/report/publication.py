from __future__ import annotations

from typing import TYPE_CHECKING

from .ledger import ReportLedger
from .provenance import build_provenance
from .snapshot import ReportSnapshot

if TYPE_CHECKING:
    from rework.analysis.assessment import Assessment


def publish_report(ledger: ReportLedger, assessment: Assessment) -> ReportSnapshot:
    provenance = build_provenance(assessment.route, assessment.pieces, assessment.start)
    statistics = assessment.statistics
    return ledger.append(provenance, statistics.probability, statistics.mean, statistics.variance)
