from collections import Counter
from dataclasses import dataclass
from fractions import Fraction

from .observations import ObservationBatch, validate_observations


@dataclass(frozen=True)
class WeightedTransition:
    source: str
    target: str
    minutes: int
    count: int
    probability: Fraction


def build_frequencies(batch: ObservationBatch) -> tuple[WeightedTransition, ...]:
    validate_observations(batch)
    totals = Counter(row.source for row in batch.observations)
    counts = Counter((row.source, row.target, row.minutes) for row in batch.observations)
    return tuple(
        WeightedTransition(source, target, minutes, count, Fraction(count, totals[source]))
        for (source, target, minutes), count in sorted(counts.items())
    )
