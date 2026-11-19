from dataclasses import dataclass
from fractions import Fraction


def _valid_label(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


@dataclass(frozen=True, order=True)
class EvidenceIdentity:
    evidence_id: str
    station: str
    revision_id: str

    def __post_init__(self) -> None:
        if not all(map(_valid_label, (self.evidence_id, self.station, self.revision_id))):
            raise ValueError('invalid fixed evidence identity')


@dataclass(frozen=True)
class ExitMoments:
    entry: str
    exit: str
    probability: Fraction
    first: Fraction
    second: Fraction


@dataclass(frozen=True)
class StationEvidence:
    identity: EvidenceIdentity
    entries: tuple[str, ...]
    exits: tuple[str, ...]
    rows: tuple[ExitMoments, ...]


def _unique_ports(names: tuple[str, ...]) -> None:
    if not isinstance(names, tuple) or any(not _valid_label(name) for name in names):
        raise ValueError('invalid evidence ports')
    if len(names) != len(set(names)):
        raise ValueError('duplicate evidence port')


def _validate_moments(row: ExitMoments) -> None:
    probability, first, second = row.probability, row.first, row.second
    if any(not isinstance(number, Fraction) for number in (probability, first, second)):
        raise ValueError('evidence requires exact fractions')
    if not 0 < probability <= 1 or first < 0 or second < 0:
        raise ValueError('evidence moments out of range')
    if first == 0 and second != 0:
        raise ValueError('positive squared minutes with zero minutes')
    mean = first / probability
    lower = mean.numerator // mean.denominator
    # For integer T, (T - lower) * (T - lower - 1) is nonnegative.
    if second < (2 * lower + 1) * first - lower * (lower + 1) * probability:
        raise ValueError('evidence moments are incompatible with integer minutes')


def validate_evidence(piece: StationEvidence) -> None:
    if not isinstance(piece, StationEvidence) or not isinstance(piece.identity, EvidenceIdentity):
        raise ValueError('fixed evidence identity required')
    _unique_ports(piece.entries)
    _unique_ports(piece.exits)
    if not piece.entries or not isinstance(piece.rows, tuple):
        raise ValueError('evidence requires public entries and a tuple of rows')
    totals = dict.fromkeys(piece.entries, Fraction(0))
    seen = set()
    for row in piece.rows:
        if not isinstance(row, ExitMoments) or row.entry not in piece.entries or row.exit not in piece.exits:
            raise ValueError('evidence row references an undeclared entry or exit')
        key = (row.entry, row.exit)
        if key in seen:
            raise ValueError('duplicate evidence row')
        seen.add(key)
        _validate_moments(row)
        totals[row.entry] += row.probability
    if any(total > 1 for total in totals.values()):
        raise ValueError('outgoing evidence mass exceeds one')
