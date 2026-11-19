from dataclasses import dataclass
from fractions import Fraction

from rework.process.frequencies import WeightedTransition
from rework.process.ports import ProcessPorts, validate_process_ports


@dataclass(frozen=True)
class StationTransition:
    target: str
    external: bool
    minutes: int
    probability: Fraction


@dataclass(frozen=True)
class StationGraph:
    entries: tuple[tuple[str, str], ...]
    exits: tuple[str, ...]
    outgoing: dict[str, tuple[StationTransition, ...]]


def build_station_graph(ports: ProcessPorts, rules: tuple[WeightedTransition, ...]) -> StationGraph:
    validate_process_ports(ports)
    outgoing: dict[str, list[StationTransition]] = {name: [] for name in ports.workstations}
    exits = set(ports.exits)
    for rule in rules:
        external = rule.target in exits
        if rule.source not in outgoing or (not external and rule.target not in outgoing):
            raise ValueError('frozen rule references an undeclared workstation or exit')
        if (type(rule.minutes) is not int or rule.minutes < 0
                or not isinstance(rule.probability, Fraction) or rule.probability <= 0):
            raise ValueError('invalid frozen transition')
        outgoing[rule.source].append(
            StationTransition(rule.target, external, rule.minutes, rule.probability)
        )
    for source, edges in outgoing.items():
        if sum(edge.probability for edge in edges) != 1:
            raise ValueError(f'frozen transition weights must sum to one at {source}')
    return StationGraph(tuple(sorted(ports.entries)), tuple(sorted(exits)), {
        source: tuple(edges) for source, edges in outgoing.items()
    })
