from __future__ import annotations

import json
import sqlite3
from fractions import Fraction
from typing import TYPE_CHECKING
from uuid import uuid4

from .frequencies import WeightedTransition
from .observations import Observation, ObservationBatch, validate_observations
from .ports import ProcessPorts

if TYPE_CHECKING:
    from .revisions import DraftRevision, FrozenRevision


def _encode_batch(batch: ObservationBatch) -> str:
    return json.dumps({
        'station': batch.station,
        'workstations': batch.ports.workstations,
        'entries': batch.ports.entries,
        'exits': batch.ports.exits,
        'observations': [(o.source, o.target, o.minutes) for o in batch.observations],
    }, ensure_ascii=False, separators=(',', ':'))


def _decode_batch(payload: str) -> ObservationBatch:
    data = json.loads(payload)
    ports = ProcessPorts(tuple(data['workstations']), tuple(map(tuple, data['entries'])), tuple(data['exits']))
    batch = ObservationBatch(data['station'], ports, tuple(Observation(*row) for row in data['observations']))
    validate_observations(batch)
    return batch


def _encode_rules(rules: tuple[WeightedTransition, ...]) -> str:
    return json.dumps([
        (r.source, r.target, r.minutes, r.count, str(r.probability)) for r in rules
    ], ensure_ascii=False, separators=(',', ':'))


def _decode_rules(payload: str) -> tuple[WeightedTransition, ...]:
    return tuple(
        WeightedTransition(source, target, minutes, count, Fraction(weight))
        for source, target, minutes, count, weight in json.loads(payload)
    )


class RevisionStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        with self.connection:
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS process_drafts (
                    draft_id TEXT PRIMARY KEY, station TEXT NOT NULL,
                    batch TEXT NOT NULL, corrected_from TEXT, frozen_revision_id TEXT
                )
            ''')
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS process_revisions (
                    revision_id TEXT PRIMARY KEY, draft_id TEXT NOT NULL UNIQUE,
                    batch TEXT NOT NULL, rules TEXT NOT NULL, corrected_from TEXT
                )
            ''')

    def save_draft(
        self, batch: ObservationBatch, *, draft_id: str | None = None,
        corrected_from: str | None = None,
    ) -> DraftRevision:
        from .revisions import DraftRevision

        validate_observations(batch)
        if draft_id is None:
            if corrected_from is not None:
                origin = self.load_frozen(corrected_from)
                if origin.batch.station != batch.station:
                    raise ValueError('correction belongs to another station')
            new_id = f'draft-{uuid4().hex}'
            with self.connection:
                self.connection.execute(
                    'INSERT INTO process_drafts VALUES (?, ?, ?, ?, NULL)',
                    (new_id, batch.station, _encode_batch(batch), corrected_from),
                )
            return DraftRevision(new_id, batch, corrected_from)

        if corrected_from is not None:
            raise ValueError('the correction origin is fixed when the draft is created')
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            current = self.load_draft(draft_id)
            if current.frozen_revision_id is not None or current.batch.station != batch.station:
                raise ValueError('cannot edit this draft with the supplied batch')
            self.connection.execute(
                'UPDATE process_drafts SET batch = ? WHERE draft_id = ?',
                (_encode_batch(batch), draft_id),
            )
        return DraftRevision(draft_id, batch, current.corrected_from)

    def load_draft(self, draft_id: str) -> DraftRevision:
        from .revisions import DraftRevision

        row = self.connection.execute(
            'SELECT batch, corrected_from, frozen_revision_id FROM process_drafts WHERE draft_id = ?',
            (draft_id,),
        ).fetchone()
        if row is None:
            raise KeyError(draft_id)
        payload, corrected_from, frozen_revision_id = row
        return DraftRevision(draft_id, _decode_batch(payload), corrected_from, frozen_revision_id)

    def commit_freeze(self, draft: DraftRevision, revision: FrozenRevision) -> None:
        if (revision.draft_id != draft.draft_id or revision.corrected_from != draft.corrected_from
                or revision.batch.station != draft.batch.station):
            raise ValueError('frozen revision does not match its draft')
        payload = _encode_batch(revision.batch)
        rules = _encode_rules(revision.rules)
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            updated = self.connection.execute('''
                UPDATE process_drafts SET batch = ?, frozen_revision_id = ?
                WHERE draft_id = ? AND frozen_revision_id IS NULL AND batch = ?
                  AND corrected_from IS ?
            ''', (payload, revision.revision_id, draft.draft_id, _encode_batch(draft.batch), draft.corrected_from))
            if updated.rowcount != 1:
                raise ValueError('draft changed before freeze')
            self.connection.execute('INSERT INTO process_revisions VALUES (?, ?, ?, ?, ?)', (
                revision.revision_id, revision.draft_id, payload, rules, revision.corrected_from,
            ))

    def load_frozen(self, revision_id: str) -> FrozenRevision:
        from .revisions import FrozenRevision

        row = self.connection.execute('''
            SELECT draft_id, batch, rules, corrected_from
            FROM process_revisions WHERE revision_id = ?
        ''', (revision_id,)).fetchone()
        if row is None:
            raise KeyError(revision_id)
        draft_id, batch, rules, corrected_from = row
        return FrozenRevision(revision_id, draft_id, _decode_batch(batch), _decode_rules(rules), corrected_from)
