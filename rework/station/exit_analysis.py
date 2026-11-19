from collections import defaultdict, deque
from fractions import Fraction

from rework.analysis.linear_systems import solve_exact_system

from .evidence import ExitMoments
from .transitions import StationGraph


def _predecessors(graph: StationGraph) -> dict[str, set[str]]:
    incoming: dict[str, set[str]] = defaultdict(set)
    for source, edges in graph.outgoing.items():
        for edge in edges:
            incoming[edge.target].add(source)
    return incoming


def _live_states(exit_name: str, incoming: dict[str, set[str]]) -> list[str]:
    states = set(incoming.get(exit_name, ()))
    queue = deque(states)
    while queue:
        for parent in incoming.get(queue.popleft(), ()):
            if parent not in states:
                states.add(parent)
                queue.append(parent)
    return sorted(states)


def _exit_moments(graph: StationGraph, exit_name: str, states: list[str]):
    index = {state: i for i, state in enumerate(states)}
    matrix = [[Fraction(i == j) for j in range(len(states))] for i in range(len(states))]
    direct = [Fraction(0) for _ in states]
    for i, state in enumerate(states):
        for edge in graph.outgoing[state]:
            if edge.external:
                if edge.target == exit_name:
                    direct[i] += edge.probability
            elif edge.target in index:
                matrix[i][index[edge.target]] -= edge.probability

    probability = solve_exact_system(matrix, direct)

    def after_probability(edge):
        if edge.external:
            return Fraction(edge.target == exit_name)
        if edge.target in index:
            return probability[index[edge.target]]
        return Fraction(0)

    first_rhs = [sum(
        (edge.probability * edge.minutes * after_probability(edge) for edge in graph.outgoing[state]),
        Fraction(0),
    ) for state in states]
    first = solve_exact_system(matrix, first_rhs)
    second_rhs = []
    for state in states:
        total = Fraction(0)
        for edge in graph.outgoing[state]:
            following_first = first[index[edge.target]] if not edge.external and edge.target in index else Fraction(0)
            total += edge.probability * (
                edge.minutes ** 2 * after_probability(edge) + 2 * edge.minutes * following_first
            )
        second_rhs.append(total)
    second = solve_exact_system(matrix, second_rhs)
    return {state: (probability[i], first[i], second[i]) for state, i in index.items()}


def analyze_station_exits(graph: StationGraph) -> tuple[ExitMoments, ...]:
    incoming = _predecessors(graph)
    rows = []
    for exit_name in graph.exits:
        states = _live_states(exit_name, incoming)
        # Paths entering a state without access to this exit contribute zero to this outlet.
        moments = _exit_moments(graph, exit_name, states)
        for entry, landing in graph.entries:
            if landing in moments:
                rows.append(ExitMoments(entry, exit_name, *moments[landing]))
    return tuple(sorted(rows, key=lambda row: (row.entry, row.exit)))
