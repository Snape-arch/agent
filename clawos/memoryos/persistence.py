"""Shared SQLite session, nested savepoints and repository base."""
import sqlite3
import threading
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from memoryos.serialization import json_loads


def atomic_workflow(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        with self.transaction():
            return method(self, *args, **kwargs)
    return run


class AtomicConnection(sqlite3.Connection):
    """Execute schema statements without sqlite3.executescript's implicit COMMIT."""
    def executescript(self, script):
        pending = ''
        for part in script.split(';'):
            pending += part + ';'
            if sqlite3.complete_statement(pending):
                self.execute(pending)
                pending = ''
        if pending.strip(' ;\n\r\t'):
            self.execute(pending)
        return self.cursor()



class SQLiteSession:
    def __init__(self, db_path: str = ""):
        self._db_path = db_path or str(Path(__file__).parent.parent / "memoryos.db")
        self._lock = threading.RLock()
        self._transaction_state = threading.local()

    @contextmanager
    def connection(self):
        active = getattr(self._transaction_state, 'connection', None)
        if active is not None:
            self._transaction_state.sequence += 1
            name = f"nested_{self._transaction_state.sequence}"
            active.execute(f"SAVEPOINT {name}")
            try:
                yield active
                active.execute(f"RELEASE SAVEPOINT {name}")
            except BaseException:
                active.execute(f"ROLLBACK TO SAVEPOINT {name}")
                active.execute(f"RELEASE SAVEPOINT {name}")
                raise
            return
        with self._lock:
            conn = sqlite3.connect(self._db_path, timeout=10, factory=AtomicConnection)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
    @contextmanager
    def transaction(self):
        """Publish a complete synchronous workflow; nested methods use savepoints."""
        if getattr(self._transaction_state, 'connection', None) is not None:
            with self.connection() as connection:
                yield connection
            return
        with self.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            self._transaction_state.connection = connection
            self._transaction_state.sequence = 0
            try:
                yield connection
            finally:
                self._transaction_state.connection = None


class Repository:
    def __init__(self, session: SQLiteSession):
        self.session = session

    def _conn(self):
        return self.session.connection()

    def transaction(self):
        return self.session.transaction()

    @property
    def _transaction_state(self):
        return self.session._transaction_state

    _json_loads = staticmethod(json_loads)
