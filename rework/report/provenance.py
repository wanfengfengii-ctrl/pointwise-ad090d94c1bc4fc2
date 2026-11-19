from dataclasses import dataclass

from rework.routing.plans import FrozenRoute
from rework.routing.port_checks import PortRef, require_selected_entry, selected_ports
from rework.station.evidence import EvidenceIdentity, StationEvidence


@dataclass(frozen=True)
class ReportProvenance:
    route_id: int
    start: PortRef
    pieces: tuple[EvidenceIdentity, ...]


def validate_provenance(provenance: ReportProvenance) -> None:
    if not isinstance(provenance, ReportProvenance):
        raise ValueError('report provenance required')
    if type(provenance.route_id) is not int or provenance.route_id <= 0:
        raise ValueError('invalid report route number')
    if not isinstance(provenance.start, PortRef):
        raise ValueError('invalid report start entry')
    if not isinstance(provenance.pieces, tuple) or any(
        not isinstance(piece, EvidenceIdentity) for piece in provenance.pieces
    ):
        raise ValueError('report requires fixed piece identities')
    ids = {piece.evidence_id for piece in provenance.pieces}
    if len(ids) != len(provenance.pieces) or provenance.start.evidence_id not in ids:
        raise ValueError('report piece identities and start do not agree')


def build_provenance(
    route: FrozenRoute, pieces: tuple[StationEvidence, ...], start: PortRef
) -> ReportProvenance:
    identities = tuple(piece.identity for piece in pieces)
    if identities != route.pieces:
        raise ValueError('signing evidence differs from the fixed route')
    require_selected_entry(selected_ports(pieces), start)
    provenance = ReportProvenance(route.route_id, start, identities)
    validate_provenance(provenance)
    return provenance
