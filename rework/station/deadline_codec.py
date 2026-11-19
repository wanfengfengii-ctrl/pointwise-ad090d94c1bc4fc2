import json
from fractions import Fraction

from .deadline_evidence import DeadlineEvidence, DeadlineMass
from .evidence import EvidenceIdentity

DEADLINE_EVIDENCE_KIND = 'deadline-evidence'
DEADLINE_EVIDENCE_VERSION = 1

_ENVELOPE_KEYS = {
    'kind', 'version', 'companion_id', 'parent', 'parent_sha256',
    'entries', 'exits', 'coverage', 'data',
}


def _distinct_members(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON field: {key}')
        result[key] = value
    return result


def _canonical_fraction(text: object) -> Fraction:
    if not isinstance(text, str):
        raise ValueError('deadline mass must be a canonical fraction string')
    try:
        value = Fraction(text)
    except (ValueError, ZeroDivisionError, OverflowError) as error:
        raise ValueError('deadline mass must be a rational fraction string') from error
    if str(value) != text:
        raise ValueError('deadline mass must be a canonical reduced fraction string')
    return value


def _valid_label(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _valid_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in '0123456789abcdef' for char in value))


def validate_deadline_evidence(evidence: DeadlineEvidence) -> None:
    if not isinstance(evidence, DeadlineEvidence) or not isinstance(evidence.parent, EvidenceIdentity):
        raise ValueError('deadline companion evidence required')
    if not _valid_label(evidence.companion_id):
        raise ValueError('invalid companion number')
    if not _valid_sha256(evidence.parent_sha256):
        raise ValueError('invalid parent fingerprint')
    if type(evidence.coverage) is not int or evidence.coverage < 0:
        raise ValueError('coverage requires a nonnegative integer number of minutes')
    if not isinstance(evidence.entries, tuple) or not evidence.entries:
        raise ValueError('deadline evidence requires public entries')
    if not isinstance(evidence.exits, tuple) or not isinstance(evidence.data, tuple):
        raise ValueError('deadline evidence requires port arrays and a tuple of mass records')
    for ports in (evidence.entries, evidence.exits):
        if any(not _valid_label(name) for name in ports) or len(set(ports)) != len(ports):
            raise ValueError('invalid or duplicated deadline evidence port')
    seen = set()
    totals = {entry: Fraction(0) for entry in evidence.entries}
    for record in evidence.data:
        if not isinstance(record, DeadlineMass):
            raise ValueError('deadline mass record required')
        if record.entry not in totals or record.exit not in evidence.exits:
            raise ValueError('deadline record references an undeclared public port')
        key = (record.entry, record.exit)
        if key in seen:
            raise ValueError('duplicated deadline mass record')
        seen.add(key)
        record_total = Fraction(0)
        minutes = set()
        for minute, mass in record.mass:
            if type(minute) is not int or not 0 <= minute <= evidence.coverage:
                raise ValueError('deadline minute outside the coverage range')
            if minute in minutes:
                raise ValueError('duplicated deadline minute')
            minutes.add(minute)
            if not isinstance(mass, Fraction) or not 0 < mass <= 1:
                raise ValueError('deadline mass must be a positive fraction at most one')
            record_total += mass
        totals[record.entry] += record_total
    if any(total > 1 for total in totals.values()):
        raise ValueError('deadline exit mass exceeds one for an entry')


def encode_deadline_evidence(evidence: DeadlineEvidence) -> bytes:
    validate_deadline_evidence(evidence)
    identity = evidence.parent
    data = {}
    for record in sorted(evidence.data, key=lambda item: (item.entry, item.exit)):
        data.setdefault(record.entry, {})[record.exit] = [
            [minute, str(mass)] for minute, mass in sorted(record.mass)
        ]
    envelope = {
        'kind': DEADLINE_EVIDENCE_KIND,
        'version': DEADLINE_EVIDENCE_VERSION,
        'companion_id': evidence.companion_id,
        'parent': {
            'evidence_id': identity.evidence_id,
            'station': identity.station,
            'revision_id': identity.revision_id,
        },
        'parent_sha256': evidence.parent_sha256,
        'entries': sorted(evidence.entries),
        'exits': sorted(evidence.exits),
        'coverage': evidence.coverage,
        'data': data,
    }
    return json.dumps(envelope, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':')).encode('utf-8')


def _decode_parent(data: dict) -> EvidenceIdentity:
    parent = data['parent']
    if not isinstance(parent, dict) or set(parent) != {'evidence_id', 'station', 'revision_id'}:
        raise ValueError('invalid deadline parent identity')
    return EvidenceIdentity(parent['evidence_id'], parent['station'], parent['revision_id'])


def decode_deadline_evidence(payload: bytes) -> DeadlineEvidence:
    if not isinstance(payload, bytes):
        raise ValueError('deadline evidence must be UTF-8 bytes')
    try:
        envelope = json.loads(payload.decode('utf-8'), object_pairs_hook=_distinct_members)
        if not isinstance(envelope, dict) or set(envelope) != _ENVELOPE_KEYS:
            raise ValueError('invalid deadline evidence envelope')
        if envelope['kind'] != DEADLINE_EVIDENCE_KIND:
            raise ValueError('unsupported deadline evidence kind')
        if type(envelope['version']) is not int or envelope['version'] != DEADLINE_EVIDENCE_VERSION:
            raise ValueError('unsupported deadline evidence version')
        companion_id = envelope['companion_id']
        if not _valid_label(companion_id):
            raise ValueError('invalid companion number')
        parent = _decode_parent(envelope)
        if not _valid_sha256(envelope['parent_sha256']):
            raise ValueError('invalid parent fingerprint')
        entries_raw = envelope['entries']
        exits_raw = envelope['exits']
        if not isinstance(entries_raw, list) or not isinstance(exits_raw, list):
            raise ValueError('deadline ports must be arrays of names')
        entries, exits = tuple(entries_raw), tuple(exits_raw)
        coverage = envelope['coverage']
        data_raw = envelope['data']
        if not isinstance(data_raw, dict):
            raise ValueError('deadline data must be a JSON object')
        records = []
        for entry, exit_map in data_raw.items():
            if entry not in entries or not isinstance(exit_map, dict):
                raise ValueError('deadline data references an undeclared entry')
            for exit_name, pairs in exit_map.items():
                if exit_name not in exits or not isinstance(pairs, list):
                    raise ValueError('deadline data references an undeclared exit')
                mass = []
                for pair in pairs:
                    if not isinstance(pair, list) or len(pair) != 2:
                        raise ValueError('deadline minute mass pair required')
                    minute, fraction_text = pair
                    mass.append((minute, _canonical_fraction(fraction_text)))
                records.append(DeadlineMass(entry, exit_name, tuple(mass)))
        evidence = DeadlineEvidence(
            companion_id, parent, envelope['parent_sha256'], entries, exits,
            coverage, tuple(records),
        )
        validate_deadline_evidence(evidence)
        return DeadlineEvidence(
            evidence.companion_id, evidence.parent, evidence.parent_sha256,
            tuple(sorted(evidence.entries)), tuple(sorted(evidence.exits)),
            evidence.coverage,
            tuple(sorted(evidence.data, key=lambda item: (item.entry, item.exit))),
        )
    except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError) as error:
        raise ValueError('invalid deadline companion evidence') from error
