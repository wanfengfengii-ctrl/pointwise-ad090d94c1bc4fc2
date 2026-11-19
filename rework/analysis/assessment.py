from dataclasses import dataclass

from rework.report.ledger import ReportLedger
from rework.report.publication import publish_report
from rework.report.snapshot import ReportSnapshot
from rework.routing.catalog import RoutingCatalog
from rework.routing.intake import get_received_evidence
from rework.routing.plans import FrozenRoute, read_frozen_route
from rework.routing.port_checks import PortRef, require_selected_entry, selected_ports
from rework.station.evidence import StationEvidence

from .composition import compose_route
from .moments import QualificationStatistics, calculate_moments


@dataclass(frozen=True)
class Assessment:
    route: FrozenRoute
    pieces: tuple[StationEvidence, ...]
    start: PortRef
    statistics: QualificationStatistics


def publish_assessment(
    catalog: RoutingCatalog, ledger: ReportLedger, route_id: int, start: PortRef
) -> ReportSnapshot:
    route = read_frozen_route(catalog, route_id)
    pieces = tuple(get_received_evidence(catalog, identity) for identity in route.pieces)
    require_selected_entry(selected_ports(pieces), start)
    graph = compose_route(route, pieces)
    statistics = calculate_moments(graph, start)
    return publish_report(ledger, Assessment(route, pieces, start, statistics))
