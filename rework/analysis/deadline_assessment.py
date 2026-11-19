from uuid import uuid4

from rework.analysis.deadline_budget import build_budget_graph, deadline_probability
from rework.report.deadline_snapshot import DeadlineReportSnapshot
from rework.report.ledger import ReportLedger, append_deadline
from rework.routing.assignments import validate_assignments
from rework.routing.catalog import RoutingCatalog
from rework.routing.deadline_intake import get_received_deadline_evidence
from rework.routing.intake import get_received_evidence
from rework.routing.plans import read_frozen_route
from rework.routing.port_checks import PortRef, require_selected_entry, selected_ports
from rework.station.deadline_evidence import DeadlineEvidence


def _select_companions(
    route, companion_ids, limit: int, catalog: RoutingCatalog,
) -> tuple[dict[str, DeadlineEvidence], dict[str, str]]:
    if isinstance(companion_ids, (str, bytes)):
        raise ValueError('supply an iterable of companion numbers')
    numbers = tuple(companion_ids)
    if len(numbers) != len(route.pieces):
        raise ValueError('each fixed piece requires exactly one deadline companion')
    if any(not isinstance(number, str) or not number for number in numbers):
        raise ValueError('invalid companion number')
    if len(set(numbers)) != len(numbers):
        raise ValueError('deadline companion selected more than once')
    expected = {identity.evidence_id: identity for identity in route.pieces}
    companions: dict[str, DeadlineEvidence] = {}
    chosen: dict[str, str] = {}
    for number in numbers:
        companion = get_received_deadline_evidence(catalog, number)
        identity = companion.parent
        if identity.evidence_id not in expected or identity != expected[identity.evidence_id]:
            raise ValueError('deadline companion parent does not match the frozen route')
        if identity.evidence_id in companions:
            raise ValueError('two companions selected for one fixed piece')
        if companion.coverage < limit:
            raise ValueError('deadline companion coverage is below the minute limit')
        companions[identity.evidence_id] = companion
        chosen[identity.evidence_id] = number
    if set(companions) != set(expected):
        raise ValueError('the frozen route has pieces without a deadline companion')
    return companions, chosen


def publish_deadline_assessment(
    catalog: RoutingCatalog, ledger: ReportLedger, route_id: int,
    start: PortRef, limit: int, companion_ids,
) -> DeadlineReportSnapshot:
    if type(limit) is not int or limit < 0:
        raise ValueError('limit requires a nonnegative integer number of minutes')
    if not isinstance(start, PortRef):
        raise ValueError('start must be a selected public entry')
    route = read_frozen_route(catalog, route_id)
    pieces = tuple(get_received_evidence(catalog, identity) for identity in route.pieces)
    require_selected_entry(selected_ports(pieces), start)
    companions, chosen = _select_companions(route, companion_ids, limit, catalog)
    ports = selected_ports(pieces)
    wiring = {
        assignment.exit: assignment.target
        for assignment in validate_assignments(ports, route.assignments)
    }
    graph = build_budget_graph(wiring, companions)
    probability = deadline_probability(graph, start, limit)
    ordered_numbers = tuple(chosen[identity.evidence_id] for identity in route.pieces)
    snapshot = DeadlineReportSnapshot(
        f'deadline-report-{uuid4().hex}', route.route_id, start, limit,
        route.pieces, ordered_numbers, probability,
    )
    return append_deadline(ledger, snapshot)
