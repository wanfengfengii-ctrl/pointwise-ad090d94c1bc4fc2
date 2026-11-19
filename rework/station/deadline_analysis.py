"""Exact accumulated-minute exit mass for one frozen station revision.

The analysis runs on the private in-station graph while the station database
is open.  Only public entries and public exits leave the station: each entry
maps to an exit and a sparse table of exact accumulated-minute probability
mass for ``0 ... coverage``.  Mass that never reaches a public exit stays
missing and is simply not reported.

For every minute ``t``, the mass newly arriving at workstations at that minute
is closed under the workstation's zero-minute internal transitions with one
exact linear solve.  Zero-minute public departures are then emitted at ``t``;
positive-minute transitions either leave through a public exit at ``t + m`` or
are scheduled to arrive at another workstation at ``t + m``.
"""
from collections import defaultdict
from fractions import Fraction

from rework.analysis.linear_systems import solve_exact_system

from .transitions import StationGraph

# entry -> exit -> minute -> exact mass
EntryMass = dict[str, dict[str, dict[int, Fraction]]]


def _zero_flow_setup(graph: StationGraph):
    """Zero-minute internal edges and the workstations that can still leak."""
    zero_internal: dict[str, list[tuple[str, Fraction]]] = defaultdict(list)
    leaks: set[str] = set()
    for source, edges in graph.outgoing.items():
        for edge in edges:
            if edge.minutes == 0:
                if edge.external:
                    # A zero-minute public departure escapes the station directly.
                    leaks.add(source)
                else:
                    zero_internal[source].append((edge.target, edge.probability))
            else:
                # Any positive-minute edge eventually breaks the zero-time flow.
                leaks.add(source)
    return zero_internal, leaks


def _zero_live_workstations(zero_internal, leaks: set[str]) -> list[str]:
    # A workstation is live when following its zero-minute internal edges can
    # reach a workstation that leaves the zero-time flow.
    predecessors: dict[str, list[str]] = defaultdict(list)
    for source, targets in zero_internal.items():
        for target, _ in targets:
            predecessors[target].append(source)
    live = set(leaks)
    queue = list(live)
    while queue:
        reached = queue.pop()
        for predecessor in predecessors.get(reached, ()):
            if predecessor not in live:
                live.add(predecessor)
                queue.append(predecessor)
    return sorted(live)


def analyze_deadline_mass(graph: StationGraph, coverage: int) -> EntryMass:
    if type(coverage) is not int or coverage < 0:
        raise ValueError('coverage requires a nonnegative integer number of minutes')
    zero_internal, leaks = _zero_flow_setup(graph)
    live = _zero_live_workstations(zero_internal, leaks)
    index = {name: i for i, name in enumerate(live)}
    size = len(live)
    # visits(t) = pending(t) + sum_s visits(s) * P(s -> t) over zero-minute
    # internal edges, so the balance matrix is (I - Q0 transposed).
    matrix = [[Fraction(i == j) for j in range(size)] for i in range(size)]
    for source, targets in zero_internal.items():
        if source not in index:
            continue
        for target, probability in targets:
            if target in index:
                matrix[index[target]][index[source]] -= probability

    result: EntryMass = {}
    for entry, landing in graph.entries:
        record: dict[str, dict[int, Fraction]] = defaultdict(lambda: defaultdict(Fraction))
        # Minute -> workstation -> mass arriving *newly* at that workstation
        # at that minute through positive-minute transitions.
        arrivals: dict[int, dict[str, Fraction]] = defaultdict(lambda: defaultdict(Fraction))
        if landing in index:
            arrivals[0][landing] = Fraction(1)
        for minute in range(coverage + 1):
            pending = arrivals.get(minute)
            if not pending:
                continue
            rhs = [pending.get(name, Fraction(0)) for name in live]
            visits = solve_exact_system(matrix, rhs) if size else ()
            for workstation, amount in zip(live, visits):
                if amount == 0:
                    continue
                for edge in graph.outgoing[workstation]:
                    share = amount * edge.probability
                    if share == 0:
                        continue
                    if edge.minutes == 0:
                        if edge.external:
                            # Zero-minute closure emits at the current minute.
                            record[edge.target][minute] += share
                        # Zero-minute internal moves are already in the solve.
                        continue
                    arrival = minute + edge.minutes
                    if arrival > coverage:
                        continue
                    if edge.external:
                        record[edge.target][arrival] += share
                    else:
                        arrivals[arrival][edge.target] += share
        result[entry] = {
            exit_name: dict(sorted(exit_record.items()))
            for exit_name, exit_record in sorted(record.items())
        }
    return result
