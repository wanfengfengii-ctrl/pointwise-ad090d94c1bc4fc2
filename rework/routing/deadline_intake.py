from hashlib import sha256

from rework.station.codec import encode_evidence
from rework.station.deadline_codec import decode_deadline_evidence, encode_deadline_evidence
from rework.station.deadline_evidence import DeadlineEvidence

from .catalog import RoutingCatalog
from .intake import get_received_evidence


def receive_deadline_evidence(catalog: RoutingCatalog, payload: bytes) -> str:
    companion = decode_deadline_evidence(payload)
    # The V1 parent has to be admitted before any companion can join it.
    parent = get_received_evidence(catalog, companion.parent.evidence_id)
    if parent.identity != companion.parent:
        raise ValueError('deadline companion parent identity mismatch')
    if companion.parent_sha256 != sha256(encode_evidence(parent)).hexdigest():
        raise ValueError('deadline companion parent fingerprint mismatch')
    if companion.entries != parent.entries or companion.exits != parent.exits:
        raise ValueError('deadline companion public ports do not match its parent')
    catalog.put_deadline_evidence(companion.companion_id, encode_deadline_evidence(companion))
    return companion.companion_id


def get_received_deadline_evidence(catalog: RoutingCatalog, companion_id: str) -> DeadlineEvidence:
    if not isinstance(companion_id, str) or not companion_id:
        raise ValueError('companion number required')
    return decode_deadline_evidence(catalog.load_deadline_evidence(companion_id))
