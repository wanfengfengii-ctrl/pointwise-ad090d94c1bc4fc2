import sqlite3
from hashlib import sha256


class RoutingCatalog:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        with self.connection:
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS received_evidence (
                    evidence_id TEXT PRIMARY KEY, payload BLOB NOT NULL, digest TEXT NOT NULL
                )
            ''')
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS received_deadline_evidence (
                    companion_id TEXT PRIMARY KEY, payload BLOB NOT NULL, digest TEXT NOT NULL
                )
            ''')
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS frozen_routes (
                    route_id INTEGER PRIMARY KEY, payload TEXT NOT NULL
                )
            ''')

    def put_evidence(self, evidence_id: str, payload: bytes) -> None:
        digest = sha256(payload).hexdigest()
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            self.connection.execute('''
                INSERT INTO received_evidence VALUES (?, ?, ?)
                ON CONFLICT(evidence_id) DO NOTHING
            ''', (evidence_id, payload, digest))
            if self.load_evidence(evidence_id) != payload:
                raise ValueError('fixed evidence number already has different content')

    def load_evidence(self, evidence_id: str) -> bytes:
        row = self.connection.execute(
            'SELECT payload, digest FROM received_evidence WHERE evidence_id = ?', (evidence_id,),
        ).fetchone()
        if row is None:
            raise KeyError(evidence_id)
        payload, digest = row
        if not isinstance(payload, bytes) or sha256(payload).hexdigest() != digest:
            raise ValueError('received evidence content has changed')
        return payload

    def put_deadline_evidence(self, companion_id: str, payload: bytes) -> None:
        digest = sha256(payload).hexdigest()
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            self.connection.execute('''
                INSERT INTO received_deadline_evidence VALUES (?, ?, ?)
                ON CONFLICT(companion_id) DO NOTHING
            ''', (companion_id, payload, digest))
            if self.load_deadline_evidence(companion_id) != payload:
                raise ValueError('fixed companion number already has different content')

    def load_deadline_evidence(self, companion_id: str) -> bytes:
        row = self.connection.execute(
            'SELECT payload, digest FROM received_deadline_evidence WHERE companion_id = ?',
            (companion_id,),
        ).fetchone()
        if row is None:
            raise KeyError(companion_id)
        payload, digest = row
        if not isinstance(payload, bytes) or sha256(payload).hexdigest() != digest:
            raise ValueError('received deadline evidence content has changed')
        return payload

    def put_plan(self, payload: str) -> int:
        with self.connection:
            cursor = self.connection.execute('INSERT INTO frozen_routes(payload) VALUES (?)', (payload,))
            route_id = cursor.lastrowid
        return route_id

    def load_plan(self, route_id: int) -> str:
        if type(route_id) is not int or route_id <= 0:
            raise ValueError('invalid route number')
        row = self.connection.execute('SELECT payload FROM frozen_routes WHERE route_id = ?', (route_id,)).fetchone()
        if row is None:
            raise KeyError(route_id)
        return row[0]
