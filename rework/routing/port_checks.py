from collections.abc import Iterable
from dataclasses import dataclass

from rework.station.evidence import StationEvidence


@dataclass(frozen=True, order=True)
class PortRef:
    evidence_id: str
    port: str

    def __post_init__(self) -> None:
        for label in (self.evidence_id, self.port):
            if not isinstance(label, str) or not label or label != label.strip():
                raise ValueError('port must name a fixed evidence number and port')


@dataclass(frozen=True)
class SelectedPorts:
    entries: frozenset[PortRef]
    exits: frozenset[PortRef]


def selected_ports(pieces: Iterable[StationEvidence]) -> SelectedPorts:
    entries = set()
    exits = set()
    identities = set()
    for piece in pieces:
        number = piece.identity.evidence_id
        if number in identities:
            raise ValueError('fixed evidence selected more than once')
        identities.add(number)
        entries.update(PortRef(number, name) for name in piece.entries)
        exits.update(PortRef(number, name) for name in piece.exits)
    return SelectedPorts(frozenset(entries), frozenset(exits))


def require_selected_entry(ports: SelectedPorts, reference: PortRef) -> None:
    if not isinstance(reference, PortRef) or reference not in ports.entries:
        raise ValueError(f'entry is outside the selected fixed evidence: {reference!r}')


def require_selected_exit(ports: SelectedPorts, reference: PortRef) -> None:
    if not isinstance(reference, PortRef) or reference not in ports.exits:
        raise ValueError(f'exit is outside the selected fixed evidence: {reference!r}')
