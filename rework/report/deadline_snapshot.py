import json
from dataclasses import dataclass
from fractions import Fraction

from rework.routing.port_checks import PortRef
from rework.station.evidence import EvidenceIdentity


@dataclass(frozen=True)
class DeadlineReportSnapshot:
    report_id: str
    route_id: int
    start: PortRef
    limit: int
    pieces: tuple[EvidenceIdentity, ...]
    companion_ids: tuple[str, ...]
    probability: Fraction


def _validate(snapshot: DeadlineReportSnapshot) -> None:
    if not isinstance(snapshot.report_id, str) or not snapshot.report_id:
        raise ValueError('invalid deadline report number')
    if type(snapshot.route_id) is not int or snapshot.route_id <= 0:
        raise ValueError('invalid deadline report route number')
    if not isinstance(snapshot.start, PortRef):
        raise ValueError('invalid deadline report start entry')
    if type(snapshot.limit) is not int or snapshot.limit < 0:
        raise ValueError('invalid deadline minute limit')
    if not isinstance(snapshot.pieces, tuple) or not snapshot.pieces:
        raise ValueError('deadline report requires fixed piece identities')
    if not isinstance(snapshot.companion_ids, tuple) or not snapshot.companion_ids:
        raise ValueError('deadline report requires companion numbers')
    if any(not isinstance(number, str) or not number for number in snapshot.companion_ids):
        raise ValueError('invalid deadline companion number')
    if len(snapshot.pieces) != len(snapshot.companion_ids):
        raise ValueError('deadline report pieces and companions do not align')
    if any(not isinstance(piece, EvidenceIdentity) for piece in snapshot.pieces):
        raise ValueError('deadline report requires fixed piece identities')
    ids = {piece.evidence_id for piece in snapshot.pieces}
    if len(ids) != len(snapshot.pieces) or snapshot.start.evidence_id not in ids:
        raise ValueError('deadline report pieces and start do not agree')
    if not isinstance(snapshot.probability, Fraction) or not 0 <= snapshot.probability <= 1:
        raise ValueError('invalid deadline qualification probability')


def encode_deadline_snapshot(snapshot: DeadlineReportSnapshot) -> str:
    _validate(snapshot)
    return json.dumps({
        'report_id': snapshot.report_id,
        'route_id': snapshot.route_id,
        'start': [snapshot.start.evidence_id, snapshot.start.port],
        'limit': snapshot.limit,
        'pieces': [
            {'evidence_id': piece.evidence_id, 'station': piece.station,
             'revision_id': piece.revision_id}
            for piece in snapshot.pieces
        ],
        'companion_ids': list(snapshot.companion_ids),
        'probability': str(snapshot.probability),
    }, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def decode_deadline_snapshot(payload: str) -> DeadlineReportSnapshot:
    try:
        data = json.loads(payload)
        snapshot = DeadlineReportSnapshot(
            data['report_id'], data['route_id'], PortRef(*data['start']),
            data['limit'],
            tuple(EvidenceIdentity(**piece) for piece in data['pieces']),
            tuple(data['companion_ids']),
            Fraction(data['probability']),
        )
        _validate(snapshot)
        if str(snapshot.probability) != data['probability']:
            raise ValueError('deadline probability must be canonical')
        return snapshot
    except (TypeError, KeyError, ValueError, ZeroDivisionError, OverflowError) as error:
        raise ValueError('invalid stored deadline report snapshot') from error
