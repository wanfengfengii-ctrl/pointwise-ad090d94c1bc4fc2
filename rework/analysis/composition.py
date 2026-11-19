from dataclasses import dataclass
from fractions import Fraction

from rework.routing.assignments import TerminalDisposition, validate_assignments
from rework.routing.plans import FrozenRoute
from rework.routing.port_checks import PortRef, selected_ports
from rework.station.evidence import StationEvidence


@dataclass(frozen=True)
class AssessmentEdge:
    target: PortRef | TerminalDisposition
    probability: Fraction
    first: Fraction
    second: Fraction


@dataclass(frozen=True)
class AssessmentGraph:
    outgoing: dict[PortRef, tuple[AssessmentEdge, ...]]


def compose_route(route: FrozenRoute, pieces: tuple[StationEvidence, ...]) -> AssessmentGraph:
    if tuple(piece.identity for piece in pieces) != route.pieces:
        raise ValueError('selected evidence differs from the frozen route')
    ports = selected_ports(pieces)
    wiring = {
        assignment.exit: assignment.target
        for assignment in validate_assignments(ports, route.assignments)
    }
    outgoing: dict[PortRef, list[AssessmentEdge]] = {entry: [] for entry in sorted(ports.entries)}
    for piece in pieces:
        number = piece.identity.evidence_id
        for row in piece.rows:
            entry = PortRef(number, row.entry)
            exit_ref = PortRef(number, row.exit)
            outgoing[entry].append(AssessmentEdge(wiring[exit_ref], row.probability, row.first, row.second))
    return AssessmentGraph({entry: tuple(edges) for entry, edges in outgoing.items()})
