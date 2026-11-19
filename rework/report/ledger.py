import sqlite3
from fractions import Fraction
from uuid import uuid4

from .deadline_snapshot import DeadlineReportSnapshot, decode_deadline_snapshot, encode_deadline_snapshot
from .provenance import ReportProvenance
from .snapshot import ReportSnapshot, decode_snapshot, encode_snapshot


class ReportLedger:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        with self.connection:
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS published_reports (
                    report_id TEXT PRIMARY KEY, snapshot TEXT NOT NULL
                )
            ''')
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS report_receipts (
                    receipt_id INTEGER PRIMARY KEY,
                    report_id TEXT NOT NULL REFERENCES published_reports(report_id)
                )
            ''')
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS published_deadline_reports (
                    report_id TEXT PRIMARY KEY, snapshot TEXT NOT NULL
                )
            ''')
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS deadline_report_receipts (
                    receipt_id INTEGER PRIMARY KEY,
                    report_id TEXT NOT NULL REFERENCES published_deadline_reports(report_id)
                )
            ''')

    def append(
        self, provenance: ReportProvenance, probability: Fraction,
        mean: Fraction | None, variance: Fraction | None,
    ) -> ReportSnapshot:
        snapshot = ReportSnapshot(f'report-{uuid4().hex}', provenance, probability, mean, variance)
        payload = encode_snapshot(snapshot)
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            self.connection.execute('INSERT INTO published_reports VALUES (?, ?)', (snapshot.report_id, payload))
        return snapshot


def read_report(ledger: ReportLedger, report_id: str) -> ReportSnapshot:
    if not isinstance(report_id, str) or not report_id:
        raise ValueError('invalid report number')
    connection = ledger.connection
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        row = connection.execute('SELECT snapshot FROM published_reports WHERE report_id = ?', (report_id,)).fetchone()
        if row is None:
            raise KeyError(report_id)
        snapshot = decode_snapshot(row[0])
        if snapshot.report_id != report_id:
            raise ValueError('stored report number mismatch')
        connection.execute('INSERT INTO report_receipts(report_id) VALUES (?)', (report_id,))
    return snapshot


def append_deadline(ledger: ReportLedger, snapshot: DeadlineReportSnapshot) -> DeadlineReportSnapshot:
    payload = encode_deadline_snapshot(snapshot)
    ledger.connection.execute('BEGIN IMMEDIATE')
    with ledger.connection:
        ledger.connection.execute(
            'INSERT INTO published_deadline_reports VALUES (?, ?)',
            (snapshot.report_id, payload),
        )
    return snapshot


def read_deadline_report(ledger: ReportLedger, report_id: str) -> DeadlineReportSnapshot:
    if not isinstance(report_id, str) or not report_id:
        raise ValueError('invalid deadline report number')
    connection = ledger.connection
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        row = connection.execute(
            'SELECT snapshot FROM published_deadline_reports WHERE report_id = ?', (report_id,),
        ).fetchone()
        if row is None:
            raise KeyError(report_id)
        snapshot = decode_deadline_snapshot(row[0])
        if snapshot.report_id != report_id:
            raise ValueError('stored deadline report number mismatch')
        connection.execute('INSERT INTO deadline_report_receipts(report_id) VALUES (?)', (report_id,))
    return snapshot
