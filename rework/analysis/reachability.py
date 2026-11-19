from collections import defaultdict, deque

from rework.routing.assignments import TerminalDisposition
from rework.routing.port_checks import PortRef

from .composition import AssessmentGraph


def reachable_states(graph: AssessmentGraph, start: PortRef) -> set[PortRef]:
    if start not in graph.outgoing:
        raise ValueError('start is not an entry in this assessment')
    reachable = {start}
    queue = deque([start])
    while queue:
        for edge in graph.outgoing[queue.popleft()]:
            target = edge.target
            if isinstance(target, PortRef) and target not in reachable:
                reachable.add(target)
                queue.append(target)
    return reachable


def states_reaching_pass(graph: AssessmentGraph, reachable: set[PortRef]) -> set[PortRef]:
    incoming = defaultdict(set)
    live = set()
    for state in reachable:
        for edge in graph.outgoing[state]:
            if edge.target is TerminalDisposition.PASS:
                live.add(state)
            elif isinstance(edge.target, PortRef):
                incoming[edge.target].add(state)
    queue = deque(live)
    while queue:
        for predecessor in incoming[queue.popleft()]:
            if predecessor not in live:
                live.add(predecessor)
                queue.append(predecessor)
    return live
