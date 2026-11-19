from dataclasses import dataclass
from fractions import Fraction

from rework.routing.assignments import TerminalDisposition
from rework.routing.port_checks import PortRef

from .composition import AssessmentGraph
from .linear_systems import solve_exact_system
from .reachability import reachable_states, states_reaching_pass


@dataclass(frozen=True)
class QualificationStatistics:
    probability: Fraction
    mean: Fraction | None
    variance: Fraction | None


def calculate_moments(graph: AssessmentGraph, start: PortRef) -> QualificationStatistics:
    reachable = reachable_states(graph, start)
    live = states_reaching_pass(graph, reachable)
    if start not in live:
        return QualificationStatistics(Fraction(0), None, None)

    states = sorted(live)
    index = {state: i for i, state in enumerate(states)}
    matrix = [[Fraction(i == j) for j in range(len(states))] for i in range(len(states))]
    direct = [Fraction(0) for _ in states]
    for i, state in enumerate(states):
        for edge in graph.outgoing[state]:
            if edge.target is TerminalDisposition.PASS:
                direct[i] += edge.probability
            elif edge.target in index:
                matrix[i][index[edge.target]] -= edge.probability

    probabilities = solve_exact_system(matrix, direct)
    next_probability = {state: probabilities[i] for state, i in index.items()}
    next_probability[TerminalDisposition.PASS] = Fraction(1)
    zero = Fraction(0)
    # These are moments weighted by the probability of eventual qualification.
    first_rhs = [sum((edge.first * next_probability.get(edge.target, zero)
                      for edge in graph.outgoing[state]), zero) for state in states]
    first = solve_exact_system(matrix, first_rhs)
    next_first = {state: first[i] for state, i in index.items()}
    second_rhs = [sum((
        edge.second * next_probability.get(edge.target, zero)
        + 2 * edge.first * next_first.get(edge.target, zero)
        for edge in graph.outgoing[state]
    ), zero) for state in states]
    second = solve_exact_system(matrix, second_rhs)

    start_index = index[start]
    probability = probabilities[start_index]
    mean = first[start_index] / probability
    variance = second[start_index] / probability - mean ** 2
    return QualificationStatistics(probability, mean, variance)
