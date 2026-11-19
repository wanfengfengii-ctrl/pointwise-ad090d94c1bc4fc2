import json
from fractions import Fraction

from .evidence import EvidenceIdentity, ExitMoments, StationEvidence, validate_evidence

V1_EVIDENCE_VERSION = 1


def _distinct_members(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON field: {key}')
        result[key] = value
    return result


def _fraction(text: str) -> Fraction:
    if not isinstance(text, str):
        raise ValueError('fraction must be a string')
    value = Fraction(text)
    if str(value) != text:
        raise ValueError('fraction must be canonical')
    return value


def encode_evidence(piece: StationEvidence) -> bytes:
    validate_evidence(piece)
    identity = piece.identity
    rows = sorted(piece.rows, key=lambda row: (row.entry, row.exit))
    data = {
        'version': V1_EVIDENCE_VERSION,
        'identity': {
            'evidence_id': identity.evidence_id, 'station': identity.station,
            'revision_id': identity.revision_id,
        },
        'entries': sorted(piece.entries),
        'exits': sorted(piece.exits),
        'rows': [(r.entry, r.exit, str(r.probability), str(r.first), str(r.second)) for r in rows],
    }
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def decode_evidence(payload: bytes) -> StationEvidence:
    if not isinstance(payload, bytes):
        raise ValueError('evidence must be UTF-8 bytes')
    try:
        data = json.loads(payload.decode('utf-8'), object_pairs_hook=_distinct_members)
        if not isinstance(data, dict) or set(data) != {'version', 'identity', 'entries', 'exits', 'rows'}:
            raise ValueError('invalid evidence envelope')
        if type(data['version']) is not int or data['version'] != V1_EVIDENCE_VERSION:
            raise ValueError('unsupported evidence version')
        identity = data['identity']
        if not isinstance(identity, dict) or set(identity) != {'evidence_id', 'station', 'revision_id'}:
            raise ValueError('invalid evidence identity fields')
        if any(not isinstance(data[key], list) for key in ('entries', 'exits', 'rows')):
            raise ValueError('invalid evidence arrays')
        rows = []
        for fields in data['rows']:
            if not isinstance(fields, list) or len(fields) != 5:
                raise ValueError('invalid evidence row fields')
            entry, exit_name, probability, first, second = fields
            rows.append(ExitMoments(entry, exit_name, _fraction(probability), _fraction(first), _fraction(second)))
        piece = StationEvidence(EvidenceIdentity(**identity), tuple(data['entries']), tuple(data['exits']), tuple(rows))
        validate_evidence(piece)
        return StationEvidence(
            piece.identity, tuple(sorted(piece.entries)), tuple(sorted(piece.exits)),
            tuple(sorted(piece.rows, key=lambda row: (row.entry, row.exit))),
        )
    except (ValueError, TypeError, ZeroDivisionError, OverflowError) as error:
        raise ValueError('invalid V1 station evidence') from error
