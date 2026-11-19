from dataclasses import dataclass
from uuid import uuid4

from .frequencies import WeightedTransition, build_frequencies
from .observations import ObservationBatch, validate_observations
from .ports import validate_rule_coverage
from .revision_store import RevisionStore


@dataclass(frozen=True)
class DraftRevision:
    draft_id: str
    batch: ObservationBatch
    corrected_from: str | None = None
    frozen_revision_id: str | None = None


@dataclass(frozen=True)
class FrozenRevision:
    revision_id: str
    draft_id: str
    batch: ObservationBatch
    rules: tuple[WeightedTransition, ...]
    corrected_from: str | None = None


def freeze_process(
    store: RevisionStore, draft_id: str, *, reviewed_batch: ObservationBatch | None = None
) -> FrozenRevision:
    draft = store.load_draft(draft_id)
    if draft.frozen_revision_id is not None:
        raise ValueError('draft has already been frozen')
    batch = draft.batch if reviewed_batch is None else reviewed_batch
    rules = build_frequencies(batch)
    if batch.station != draft.batch.station:
        raise ValueError('reviewed batch belongs to another station')
    validate_rule_coverage(batch.ports, (rule.source for rule in rules))
    frozen = FrozenRevision(f'rev-{uuid4().hex}', draft.draft_id, batch, rules, draft.corrected_from)
    store.commit_freeze(draft, frozen)
    return frozen


def read_frozen_revision(store: RevisionStore, revision_id: str) -> FrozenRevision:
    return store.load_frozen(revision_id)


def open_correction(
    store: RevisionStore, revision_id: str, batch: ObservationBatch
) -> DraftRevision:
    previous = read_frozen_revision(store, revision_id)
    validate_observations(batch)
    if batch.station != previous.batch.station:
        raise ValueError('correction must belong to the original station')
    return store.save_draft(batch, corrected_from=previous.revision_id)
