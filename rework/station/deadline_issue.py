from hashlib import sha256
from uuid import uuid4

from rework.process.revision_store import RevisionStore
from rework.process.revisions import read_frozen_revision

from .codec import encode_evidence
from .deadline_analysis import analyze_deadline_mass
from .deadline_codec import encode_deadline_evidence
from .deadline_evidence import DeadlineEvidence, DeadlineMass
from .evidence import StationEvidence
from .issue import StationEvidenceStore, read_station_evidence
from .transitions import build_station_graph


def _companion(
    piece: StationEvidence, coverage: int, revisions: RevisionStore
) -> DeadlineEvidence:
    revision = read_frozen_revision(revisions, piece.identity.revision_id)
    graph = build_station_graph(revision.batch.ports, revision.rules)
    if tuple(name for name, _ in graph.entries) != piece.entries or graph.exits != piece.exits:
        raise ValueError('issued V1 piece does not match its bound revision')
    mass = analyze_deadline_mass(graph, coverage)
    records = []
    for entry in piece.entries:
        for exit_name in piece.exits:
            minutes = mass.get(entry, {}).get(exit_name)
            if minutes:
                records.append(DeadlineMass(
                    entry, exit_name, tuple(sorted(minutes.items())),
                ))
    return DeadlineEvidence(
        f'deadline-{uuid4().hex}', piece.identity,
        sha256(encode_evidence(piece)).hexdigest(),
        piece.entries, piece.exits, coverage, tuple(records),
    )


def issue_deadline_evidence(
    revisions: RevisionStore, issued: StationEvidenceStore,
    evidence_id: str, coverage: int,
) -> bytes:
    if not isinstance(evidence_id, str) or not evidence_id:
        raise ValueError('fixed evidence number required')
    if type(coverage) is not int or coverage < 0:
        raise ValueError('coverage requires a nonnegative integer number of minutes')
    piece = read_station_evidence(issued, evidence_id)
    companion = _companion(piece, coverage, revisions)
    payload = encode_deadline_evidence(companion)
    issued.connection.execute('BEGIN IMMEDIATE')
    with issued.connection:
        issued.connection.execute(
            'INSERT INTO issued_deadline_evidence VALUES (?, ?, ?)',
            (companion.companion_id, payload, sha256(payload).hexdigest()),
        )
    return payload
