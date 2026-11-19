from fractions import Fraction as F

from rework.process.frequencies import build_frequencies
from rework.process.revisions import freeze_process
from rework.station.deadline_analysis import analyze_deadline_mass
from rework.station.deadline_codec import decode_deadline_evidence, encode_deadline_evidence
from rework.station.deadline_issue import issue_deadline_evidence
from rework.station.issue import issue_evidence
from rework.station.transitions import build_station_graph

from tests.support import ProjectCase, alpha_batch, batch, beta_batch


def mass_lookup(companion, entry, exit_name, minute):
    for record in companion.data:
        if record.entry == entry and record.exit == exit_name:
            return dict(record.mass).get(minute)
    return None


class TestDeadlineStation(ProjectCase):
    def test_exact_minute_mass_single_station(self):
        sample = batch('Alpha', [('bench', 'send', minute)
                                 for minute in (0, 2, 2, 2, 2, 2, 2, 4)])
        with self.station('alpha') as (_, revisions, issued):
            revision = freeze_process(revisions, revisions.save_draft(sample).draft_id)
            piece = issue_evidence(revisions, issued, revision.revision_id)
            payload = issue_deadline_evidence(revisions, issued, piece.identity.evidence_id, 4)
            companion = decode_deadline_evidence(payload)
            self.assertEqual(companion.coverage, 4)
            self.assertEqual(companion.parent, piece.identity)
            self.assertEqual(companion.entries, piece.entries)
            self.assertEqual(companion.exits, piece.exits)
            table = {minute: mass for record in companion.data
                     for minute, mass in record.mass}
            self.assertEqual(table, {0: F(1, 8), 2: F(3, 4), 4: F(1, 8)})
            self.assertEqual(sum(table.values(), F(0)), 1)
            # Private workstations and raw observations never enter the payload.
            self.assertNotIn(b'bench', payload)
            self.assertNotIn(b'observations', payload)

    def test_internal_revisits_stay_in_station(self):
        sample = batch('Alpha', (
            ('bench', 'loop', 0), ('loop', 'loop', 1), ('loop', 'loop', 1),
            ('loop', 'send', 2), ('loop', 'discard', 0),
        ), exits=('send', 'discard'), workstations=('bench', 'loop'))
        _, companion, _ = self.issue_with_companion('alpha', sample, coverage=3)
        send = {minute: mass for record in companion.data if record.exit == 'send'
                for minute, mass in record.mass}
        discard = {minute: mass for record in companion.data if record.exit == 'discard'
                   for minute, mass in record.mass}
        # bench reaches loop at minute zero; loop needs zero or more 1-minute
        # self visits before departing, each with probability one half.
        self.assertEqual(send, {2: F(1, 4), 3: F(1, 8)})
        self.assertEqual(discard, {0: F(1, 4), 1: F(1, 8), 2: F(1, 16), 3: F(1, 32)})
        total = sum(send.values(), F(0)) + sum(discard.values(), F(0))
        # Mass departing after the coverage window stays missing.
        self.assertEqual(total, F(27, 32))

    def test_mass_above_coverage_is_dropped(self):
        sample = batch('Alpha', [('bench', 'send', minute) for minute in (1, 3)])
        piece, companion, _ = self.issue_with_companion('alpha', sample, coverage=2)
        table = {minute: mass for record in companion.data
                 for minute, mass in record.mass}
        self.assertEqual(table, {1: F(1, 2)})
        # Missing mass stays missing rather than being renormalized.
        self.assertEqual(sum(table.values(), F(0)), F(1, 2))

    def test_trapped_station_keeps_missing_mass(self):
        sample = batch('Alpha', (
            ('bench', 'loop', 0), ('bench', 'send', 4), ('loop', 'loop', 0),
        ), workstations=('bench', 'loop'), entries=(('start', 'bench'), ('trapped', 'loop')))
        _, companion, _ = self.issue_with_companion('alpha', sample, coverage=4)
        start_mass = {minute: mass for record in companion.data if record.entry == 'start'
                      for minute, mass in record.mass}
        self.assertEqual(start_mass, {4: F(1, 2)})
        self.assertFalse(any(record.entry == 'trapped' for record in companion.data))

    def test_zero_internal_cycle_is_solved_exactly(self):
        sample = batch('Alpha', (('bench', 'bench', 0), ('bench', 'send', 0)),
                       entries=(('start', 'bench'), ('alternate', 'bench')))
        graph = build_station_graph(sample.ports, build_frequencies(sample))
        mass = analyze_deadline_mass(graph, 0)
        for entry in ('start', 'alternate'):
            self.assertEqual(mass[entry], {'send': {0: F(1)}})

    def test_coverage_validation_and_reissue(self):
        piece, _, _ = self.issue_with_companion('alpha', alpha_batch(), coverage=1)
        with self.station('alpha') as (db, revisions, issued):
            for bad in (-1, True, 1.0, '2'):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    issue_deadline_evidence(revisions, issued, piece.identity.evidence_id, bad)
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM issued_deadline_evidence').fetchone()[0], 1)
            first = issue_deadline_evidence(revisions, issued, piece.identity.evidence_id, 0)
            second = issue_deadline_evidence(revisions, issued, piece.identity.evidence_id, 0)
            self.assertNotEqual(decode_deadline_evidence(first).companion_id,
                                decode_deadline_evidence(second).companion_id)
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM issued_deadline_evidence').fetchone()[0], 3)
            with self.assertRaises(KeyError):
                issue_deadline_evidence(revisions, issued, 'piece-missing', 1)
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM issued_deadline_evidence').fetchone()[0], 3)

    def test_roundtrip_keeps_canonical_shape(self):
        _, companion, payload = self.issue_with_companion(
            'beta', beta_batch(), coverage=4)
        self.assertEqual(encode_deadline_evidence(companion), payload)
        import json
        envelope = json.loads(payload)
        self.assertEqual(envelope['kind'], 'deadline-evidence')
        self.assertEqual(envelope['version'], 1)
        self.assertEqual(set(envelope), {
            'kind', 'version', 'companion_id', 'parent', 'parent_sha256',
            'entries', 'exits', 'coverage', 'data',
        })
        decoded = decode_deadline_evidence(payload)
        self.assertEqual(decoded, companion)
        # Key ordering and whitespace do not change content.
        pretty = json.dumps(json.loads(payload), indent=2).encode()
        self.assertEqual(decode_deadline_evidence(pretty), companion)

    def test_unknown_evidence_raises_keyerror(self):
        with self.station('alpha') as (_, revisions, issued):
            with self.assertRaises(KeyError):
                issue_deadline_evidence(revisions, issued, 'piece-nope', 1)
