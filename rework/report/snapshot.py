import json
from dataclasses import dataclass
from fractions import Fraction

from rework.routing.port_checks import PortRef
from rework.station.evidence import EvidenceIdentity

from .provenance import ReportProvenance, validate_provenance


@dataclass(frozen=True)
class ReportSnapshot:
    report_id: str
    provenance: ReportProvenance
    probability: Fraction
    mean: Fraction | None
    variance: Fraction | None
    mean_unit: str = 'minute'
    variance_unit: str = 'minute_squared'


def _validate(snapshot: ReportSnapshot) -> None:
    validate_provenance(snapshot.provenance)
    if not isinstance(snapshot.report_id, str) or not snapshot.report_id:
        raise ValueError('invalid report number')
    if (snapshot.mean_unit, snapshot.variance_unit) != ('minute', 'minute_squared'):
        raise ValueError('invalid report units')
    if not isinstance(snapshot.probability, Fraction) or not 0 <= snapshot.probability <= 1:
        raise ValueError('invalid qualification probability')
    if snapshot.probability == 0:
        if snapshot.mean is not None or snapshot.variance is not None:
            raise ValueError('zero qualification requires empty duration statistics')
    elif any(not isinstance(value, Fraction) or value < 0 for value in (snapshot.mean, snapshot.variance)):
        raise ValueError('positive qualification requires nonnegative exact duration statistics')
    elif snapshot.mean == 0 and snapshot.variance != 0:
        raise ValueError('zero mean with nonzero variance')


def encode_snapshot(snapshot: ReportSnapshot) -> str:
    _validate(snapshot)
    provenance = snapshot.provenance
    return json.dumps({
        'report_id': snapshot.report_id,
        'probability': str(snapshot.probability),
        'mean': None if snapshot.mean is None else str(snapshot.mean),
        'variance': None if snapshot.variance is None else str(snapshot.variance),
        'mean_unit': snapshot.mean_unit,
        'variance_unit': snapshot.variance_unit,
        'provenance': {
            'route_id': provenance.route_id,
            'start': [provenance.start.evidence_id, provenance.start.port],
            'pieces': [
                {'evidence_id': p.evidence_id, 'station': p.station, 'revision_id': p.revision_id}
                for p in provenance.pieces
            ],
        },
    }, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _decode_number(value: str | None) -> Fraction | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('snapshot number must be encoded as a string')
    result = Fraction(value)
    if str(result) != value:
        raise ValueError('snapshot number must be canonical')
    return result


def decode_snapshot(payload: str) -> ReportSnapshot:
    try:
        data = json.loads(payload)
        origin = data['provenance']
        provenance = ReportProvenance(
            origin['route_id'], PortRef(*origin['start']),
            tuple(EvidenceIdentity(**piece) for piece in origin['pieces']),
        )
        snapshot = ReportSnapshot(
            data['report_id'], provenance, _decode_number(data['probability']),
            _decode_number(data['mean']), _decode_number(data['variance']),
            data['mean_unit'], data['variance_unit'],
        )
        _validate(snapshot)
        return snapshot
    except (TypeError, KeyError, ValueError, ZeroDivisionError) as error:
        raise ValueError('invalid stored report snapshot') from error
