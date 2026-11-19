import sqlite3
from hashlib import sha256
from uuid import uuid4

from rework.process.revision_store import RevisionStore
from rework.process.revisions import read_frozen_revision

from .codec import decode_evidence, encode_evidence
from .evidence import EvidenceIdentity, StationEvidence
from .exit_analysis import analyze_station_exits
from .transitions import build_station_graph


class StationEvidenceStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        with self.connection:
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS issued_evidence (
                    evidence_id TEXT PRIMARY KEY, payload BLOB NOT NULL, digest TEXT NOT NULL
                )
            ''')

    def _insert(self, piece: StationEvidence) -> None:
        payload = encode_evidence(piece)
        with self.connection:
            self.connection.execute('INSERT INTO issued_evidence VALUES (?, ?, ?)', (
                piece.identity.evidence_id, payload, sha256(payload).hexdigest(),
            ))


def issue_evidence(
    revisions: RevisionStore, issued: StationEvidenceStore, revision_id: str
) -> StationEvidence:
    revision = read_frozen_revision(revisions, revision_id)
    graph = build_station_graph(revision.batch.ports, revision.rules)
    piece = StationEvidence(
        EvidenceIdentity(f'piece-{uuid4().hex}', revision.batch.station, revision.revision_id),
        tuple(name for name, _ in graph.entries), graph.exits, analyze_station_exits(graph),
    )
    issued._insert(piece)
    return piece


def read_station_evidence(issued: StationEvidenceStore, evidence_id: str) -> StationEvidence:
    row = issued.connection.execute(
        'SELECT payload, digest FROM issued_evidence WHERE evidence_id = ?', (evidence_id,),
    ).fetchone()
    if row is None:
        raise KeyError(evidence_id)
    payload, digest = row
    if not isinstance(payload, bytes) or sha256(payload).hexdigest() != digest:
        raise ValueError('issued evidence content has changed')
    piece = decode_evidence(payload)
    if piece.identity.evidence_id != evidence_id:
        raise ValueError('issued evidence identity mismatch')
    return piece
