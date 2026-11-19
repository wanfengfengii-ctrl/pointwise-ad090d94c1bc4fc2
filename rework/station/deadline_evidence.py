from dataclasses import dataclass
from fractions import Fraction

from .evidence import EvidenceIdentity


@dataclass(frozen=True)
class DeadlineMass:
    entry: str
    exit: str
    mass: tuple[tuple[int, Fraction], ...]


@dataclass(frozen=True)
class DeadlineEvidence:
    companion_id: str
    parent: EvidenceIdentity
    parent_sha256: str
    entries: tuple[str, ...]
    exits: tuple[str, ...]
    coverage: int
    data: tuple[DeadlineMass, ...]
