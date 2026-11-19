"""Finite-budget qualification over a frozen route.

The center only sees public entries and exits.  A visit to an entry consumes
the exact-minute mass recorded by its companion; every true station departure
follows the frozen wiring.  Cross-station returns share the same remaining
minute budget, while zero-minute moves (including zero-minute cycles through
any finite number of steps) are resolved with an exact linear system.
"""
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction

from rework.analysis.linear_systems import SingularSystemError, solve_exact_system
from rework.routing.assignments import TerminalDisposition
from rework.routing.port_checks import PortRef
from rework.station.deadline_evidence import DeadlineEvidence


@dataclass(frozen=True)
class BudgetEdge:
    minute: int
    probability: Fraction
    target: PortRef | TerminalDisposition


@dataclass(frozen=True)
class BudgetGraph:
    outgoing: dict[PortRef, tuple[BudgetEdge, ...]]
    # Zero-minute edges ending at another public entry, aggregated per target.
    zero_entries: dict[PortRef, tuple[tuple[PortRef, Fraction], ...]]
    zero_pass: frozenset[PortRef]
    states: tuple[PortRef, ...]


def build_budget_graph(
    wiring: dict[PortRef, PortRef | TerminalDisposition],
    companions: dict[str, DeadlineEvidence],
) -> BudgetGraph:
    tables: dict[PortRef, list[BudgetEdge]] = defaultdict(list)
    for companion in companions.values():
        number = companion.parent.evidence_id
        for record in companion.data:
            entry = PortRef(number, record.entry)
            exit_ref = PortRef(number, record.exit)
            target = wiring[exit_ref]
            for minute, mass in record.mass:
                tables[entry].append(BudgetEdge(minute, mass, target))
    outgoing = {entry: tuple(sorted(edges, key=lambda edge: (edge.minute, str(edge.target))))
                for entry, edges in tables.items()}
    zero_map: dict[PortRef, dict[PortRef, Fraction]] = defaultdict(lambda: defaultdict(Fraction))
    zero_pass: set[PortRef] = set()
    for entry, edges in outgoing.items():
        for edge in edges:
            if edge.minute != 0:
                continue
            if edge.target is TerminalDisposition.PASS:
                zero_pass.add(entry)
            elif isinstance(edge.target, PortRef):
                zero_map[entry][edge.target] += edge.probability
    states = tuple(sorted(outgoing))
    zero_entries = {
        entry: tuple(sorted(targets.items())) for entry, targets in zero_map.items()
    }
    return BudgetGraph(outgoing, zero_entries, frozenset(zero_pass), states)


def _bottom_sccs(states: list[PortRef], zero_entries) -> list[set[PortRef]]:
    index_counter = 0
    indices: dict[PortRef, int] = {}
    lowlink: dict[PortRef, int] = {}
    stack: list[PortRef] = []
    on_stack: set[PortRef] = set()
    components: list[set[PortRef]] = []

    def neighbors(node: PortRef):
        for target, _ in zero_entries.get(node, ()):
            if target in indices:
                yield target

    def visit(node: PortRef) -> None:
        nonlocal index_counter
        indices[node] = lowlink[node] = index_counter
        index_counter += 1
        stack.append(node)
        on_stack.add(node)
        for target in neighbors(node):
            if target not in indices:
                visit(target)
                lowlink[node] = min(lowlink[node], lowlink[target])
            elif target in on_stack:
                lowlink[node] = min(lowlink[node], indices[target])
        if lowlink[node] == indices[node]:
            component: set[PortRef] = set()
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.add(member)
                if member == node:
                    break
            components.append(component)

    for state in states:
        if state not in indices:
            visit(state)

    bottom = []
    for component in components:
        if not any(target not in component
                   for node in component for target, _ in zero_entries.get(node, ())):
            bottom.append(component)
    return bottom


def _zero_time_solve(
    graph: BudgetGraph, rhs: dict[PortRef, Fraction], states: list[PortRef]
) -> dict[PortRef, Fraction]:
    """Solve f = rhs + Q0 f, anchoring trapped zero-time closed classes at zero."""
    zero_pass = graph.zero_pass
    zero_entries = graph.zero_entries
    active = set(states)
    anchored: set[PortRef] = set()

    def row_sum(node: PortRef) -> Fraction:
        return sum((mass for target, mass in zero_entries.get(node, ())
                    if target in active), Fraction(0))

    # A bottom SCC whose zero-time rows are fully stochastic leaks neither into
    # a positive-minute move nor a terminal: its qualifying mass is exactly zero.
    while True:
        bottom = _bottom_sccs([state for state in states if state in active], zero_entries)
        closed = []
        for component in bottom:
            if zero_pass.intersection(component):
                continue
            if any(row_sum(node) < 1 for node in component):
                continue
            closed.append(component)
        if not closed:
            break
        for component in closed:
            active.difference_update(component)
            anchored.update(component)

    ordered = [state for state in states if state in active]
    index = {state: i for i, state in enumerate(ordered)}
    size = len(ordered)
    matrix = [[Fraction(i == j) for j in range(size)] for i in range(size)]
    vector = [rhs.get(state, Fraction(0)) for state in ordered]
    for i, state in enumerate(ordered):
        for target, probability in zero_entries.get(state, ()):
            if target in index:
                matrix[i][index[target]] -= probability
    if size:
        try:
            solved = solve_exact_system(matrix, vector)
        except SingularSystemError as error:
            raise ValueError('deadline zero-time system is not solvable') from error
    else:
        solved = ()
    result = {state: Fraction(0) for state in anchored}
    result.update({state: value for state, value in zip(ordered, solved)})
    return result


def deadline_probability(graph: BudgetGraph, start: PortRef, limit: int) -> Fraction:
    if start not in graph.outgoing:
        return Fraction(0)
    previous: dict[PortRef, Fraction] = {}
    for budget in range(limit + 1):
        rhs: dict[PortRef, Fraction] = {state: Fraction(0) for state in graph.states}
        for state, edges in graph.outgoing.items():
            total = Fraction(0)
            for edge in edges:
                if edge.minute > budget:
                    continue
                target = edge.target
                if target is TerminalDisposition.PASS:
                    # Zero-minute and positive-minute PASS both count when the
                    # accumulated minutes stay inside the inclusive limit.
                    total += edge.probability
                elif edge.minute == 0:
                    # Zero-minute entry moves are resolved by the linear system;
                    # zero-minute SCRAP contributes no qualifying mass.
                    continue
                elif isinstance(target, PortRef):
                    total += edge.probability * previous.get(target, Fraction(0))
                # SCRAP and mass that leaves the budget contribute nothing.
            rhs[state] = total
        previous = _zero_time_solve(graph, rhs, list(graph.states))
    return previous.get(start, Fraction(0))
