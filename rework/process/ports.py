from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessPorts:
    workstations: tuple[str, ...]
    entries: tuple[tuple[str, str], ...]
    exits: tuple[str, ...]


def _valid_name(name: object) -> bool:
    return isinstance(name, str) and bool(name) and name == name.strip()


def _check_names(names: tuple[str, ...], description: str) -> None:
    if not isinstance(names, tuple) or any(not _valid_name(name) for name in names):
        raise ValueError(f'invalid {description} names')
    if len(set(names)) != len(names):
        raise ValueError(f'duplicate {description} names')


def validate_process_ports(ports: ProcessPorts) -> None:
    if not isinstance(ports, ProcessPorts):
        raise ValueError('process ports required')
    _check_names(ports.workstations, 'workstation')
    _check_names(ports.exits, 'exit')
    if not ports.workstations or set(ports.workstations).intersection(ports.exits):
        raise ValueError('declare workstations distinct from exits')
    if not isinstance(ports.entries, tuple) or not ports.entries:
        raise ValueError('at least one entry is required')
    for entry in ports.entries:
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise ValueError('entry must identify its landing workstation')
        name, landing = entry
        if not _valid_name(name) or landing not in ports.workstations:
            raise ValueError('invalid entry or unknown landing workstation')
    _check_names(tuple(name for name, _ in ports.entries), 'entry')


def validate_rule_coverage(ports: ProcessPorts, sources) -> None:
    missing = sorted(set(ports.workstations).difference(sources))
    if missing:
        raise ValueError(f'workstations without observations: {", ".join(missing)}')
