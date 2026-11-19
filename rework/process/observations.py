from dataclasses import dataclass

from .ports import ProcessPorts, validate_process_ports


@dataclass(frozen=True)
class Observation:
    source: str
    target: str
    minutes: int


@dataclass(frozen=True)
class ObservationBatch:
    station: str
    ports: ProcessPorts
    observations: tuple[Observation, ...]


def validate_observations(batch: ObservationBatch) -> None:
    if not isinstance(batch, ObservationBatch):
        raise ValueError('observation batch required')
    if not isinstance(batch.station, str) or not batch.station or batch.station != batch.station.strip():
        raise ValueError('invalid station name')
    validate_process_ports(batch.ports)
    if not isinstance(batch.observations, tuple):
        raise ValueError('observations must be a tuple of occurrences')
    sources = batch.ports.workstations
    targets = sources + batch.ports.exits
    for index, row in enumerate(batch.observations, 1):
        if not isinstance(row, Observation):
            raise ValueError(f'observation {index} has invalid fields')
        if row.source not in sources or row.target not in targets:
            raise ValueError(f'observation {index} references an unknown workstation or exit')
        if type(row.minutes) is not int or row.minutes < 0:
            raise ValueError(f'observation {index} requires nonnegative integer minutes')
