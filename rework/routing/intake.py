from rework.station.codec import decode_evidence, encode_evidence
from rework.station.evidence import EvidenceIdentity, StationEvidence

from .catalog import RoutingCatalog


def receive_evidence(catalog: RoutingCatalog, payload: bytes) -> StationEvidence:
    piece = decode_evidence(payload)
    catalog.put_evidence(piece.identity.evidence_id, encode_evidence(piece))
    return piece


def get_received_evidence(
    catalog: RoutingCatalog, reference: str | EvidenceIdentity
) -> StationEvidence:
    evidence_id = reference.evidence_id if isinstance(reference, EvidenceIdentity) else reference
    if not isinstance(evidence_id, str) or not evidence_id:
        raise ValueError('fixed evidence number required')
    piece = decode_evidence(catalog.load_evidence(evidence_id))
    if piece.identity.evidence_id != evidence_id:
        raise ValueError('received evidence number mismatch')
    if isinstance(reference, EvidenceIdentity) and piece.identity != reference:
        raise ValueError('received evidence revision or station mismatch')
    return piece
