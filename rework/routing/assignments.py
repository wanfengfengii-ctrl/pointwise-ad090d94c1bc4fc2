from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from .port_checks import PortRef, SelectedPorts, require_selected_entry, require_selected_exit


class TerminalDisposition(Enum):
    PASS = 'pass'
    SCRAP = 'scrap'


@dataclass(frozen=True)
class RouteAssignment:
    exit: PortRef
    target: PortRef | TerminalDisposition


def validate_assignments(
    ports: SelectedPorts, assignments: Iterable[RouteAssignment]
) -> tuple[RouteAssignment, ...]:
    by_exit = {}
    for assignment in assignments:
        if not isinstance(assignment, RouteAssignment):
            raise ValueError('route assignment required')
        require_selected_exit(ports, assignment.exit)
        if assignment.exit in by_exit:
            raise ValueError(f'duplicate exit assignment: {assignment.exit!r}')
        if isinstance(assignment.target, PortRef):
            require_selected_entry(ports, assignment.target)
        elif not isinstance(assignment.target, TerminalDisposition):
            raise ValueError('target must be a selected entry, pass or scrap')
        by_exit[assignment.exit] = assignment
    missing = ports.exits.difference(by_exit)
    if missing:
        raise ValueError(f'missing exit assignments: {sorted(missing)!r}')
    return tuple(by_exit[exit_ref] for exit_ref in sorted(by_exit))
