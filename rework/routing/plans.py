import json
from collections.abc import Iterable
from dataclasses import dataclass

from rework.station.evidence import EvidenceIdentity

from .assignments import RouteAssignment, TerminalDisposition, validate_assignments
from .catalog import RoutingCatalog
from .intake import get_received_evidence
from .port_checks import PortRef, selected_ports


@dataclass(frozen=True)
class FrozenRoute:
    route_id: int
    pieces: tuple[EvidenceIdentity, ...]
    assignments: tuple[RouteAssignment, ...]


def _encode_assignment(assignment: RouteAssignment) -> list:
    source = [assignment.exit.evidence_id, assignment.exit.port]
    target = assignment.target
    if isinstance(target, PortRef):
        return [source, ['entry', target.evidence_id, target.port]]
    return [source, ['terminal', target.value]]


def _decode_assignment(fields: list) -> RouteAssignment:
    source, target = fields
    if target[0] == 'entry':
        endpoint = PortRef(*target[1:])
    elif target[0] == 'terminal' and len(target) == 2:
        endpoint = TerminalDisposition(target[1])
    else:
        raise ValueError('invalid frozen route target')
    return RouteAssignment(PortRef(*source), endpoint)


def freeze_route(
    catalog: RoutingCatalog, evidence_ids: Iterable[str], assignments: Iterable[RouteAssignment]
) -> FrozenRoute:
    if isinstance(evidence_ids, (str, bytes)):
        raise ValueError('supply an iterable of fixed evidence numbers')
    numbers = tuple(evidence_ids)
    if not numbers or any(not isinstance(number, str) or not number for number in numbers):
        raise ValueError('select at least one fixed evidence number')
    if len(set(numbers)) != len(numbers):
        raise ValueError('duplicate fixed evidence selection')
    pieces = tuple(get_received_evidence(catalog, number) for number in sorted(numbers))
    wiring = validate_assignments(selected_ports(pieces), assignments)
    identities = tuple(piece.identity for piece in pieces)
    payload = json.dumps({
        'pieces': [(p.evidence_id, p.station, p.revision_id) for p in identities],
        'assignments': [_encode_assignment(assignment) for assignment in wiring],
    }, ensure_ascii=False, separators=(',', ':'))
    route_id = catalog.put_plan(payload)
    return FrozenRoute(route_id, identities, wiring)


def read_frozen_route(catalog: RoutingCatalog, route_id: int) -> FrozenRoute:
    payload = catalog.load_plan(route_id)
    try:
        data = json.loads(payload)
        pieces = tuple(EvidenceIdentity(*fields) for fields in data['pieces'])
        if not pieces or len({piece.evidence_id for piece in pieces}) != len(pieces):
            raise ValueError('invalid frozen route selection')
        assignments = tuple(_decode_assignment(fields) for fields in data['assignments'])
        return FrozenRoute(route_id, pieces, assignments)
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise ValueError(f'damaged frozen route {route_id}') from error
