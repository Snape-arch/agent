"""Persistent checkpoints and verified project evidence for coding tasks."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
from contextlib import closing
from heapq import nlargest

from .coding_execution_context import CodingExecutionContext
from .file_transactions import _file_lock, write_text


class CodingSessionStore:
    def __init__(self, root):
        self.root = Path(root).resolve()

    @staticmethod
    def project(repo, actor):
        return CodingExecutionContext.digest([os.path.normcase(str(Path(repo).resolve())), actor])

    def _checkpoint(self, project, run_id):
        if not re.fullmatch(r'ctr-[0-9a-f]{32}', run_id):
            raise ValueError('invalid coding checkpoint identifier')
        return self.root / 'sessions' / project / (run_id + '.json')

    def lock(self, project, run_id):
        return _file_lock(self._checkpoint(project, run_id).with_suffix('.resume'), timeout=0.1)

    def exists(self, project, run_id):
        return self._checkpoint(project, run_id).is_file()

    def save(self, project, run_id, state):
        record = {'schema': 'clawos.coding-resume.v1', 'project': project, 'run_id': run_id, 'state': state}
        record['digest'] = CodingExecutionContext.digest(record)
        write_text(self._checkpoint(project, run_id), json.dumps(record, ensure_ascii=False, separators=(',', ':')))

    def load(self, project, run_id):
        path = self._checkpoint(project, run_id)
        if not path.is_file():
            raise ValueError('coding checkpoint not found in this project')
        record = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(record, dict):
            raise ValueError('invalid coding checkpoint record')
        digest = record.pop('digest', None)
        if (record.get('schema') != 'clawos.coding-resume.v1' or record.get('project') != project
                or record.get('run_id') != run_id or CodingExecutionContext.digest(record) != digest):
            raise ValueError('coding checkpoint integrity check failed')
        return record['state']

    def history(self, project):
        folder = self.root / 'sessions' / project
        paths = []
        for path in folder.glob('ctr-*.json'):
            try:
                paths.append((path.stat().st_mtime_ns, path))
            except OSError:
                continue
        rows = []
        for _, path in sorted(paths, key=lambda pair: pair[0], reverse=True)[:50]:
            try:
                state = self.load(project, path.stem)
            except (OSError, ValueError):
                continue
            rows.append({'checkpoint_id': path.stem, 'workspace': state['baseline']['workspace']['workspace'], **{
                key: state[key] for key in ('task_id', 'session_id', 'objective', 'status', 'next_turn')
            }})
        return rows

    def _connect(self):
        self.root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.root / 'projects.sqlite3', timeout=8)
        connection.row_factory = sqlite3.Row
        connection.execute('''CREATE TABLE IF NOT EXISTS coding_evidence (
            project TEXT, path TEXT, source_sha256 TEXT, run_id TEXT, tests INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(project, path, source_sha256)
        )''')
        connection.execute('''CREATE INDEX IF NOT EXISTS coding_evidence_recent
                              ON coding_evidence(project, updated_at DESC)''')
        connection.execute('''CREATE TABLE IF NOT EXISTS project_notes (
            project TEXT, id TEXT, topic TEXT, note TEXT, scope TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(project, id)
        )''')
        return connection

    def save_note(self, project, topic, note, scope='', note_id=None):
        for label, value, limit in (('topic', topic, 120), ('note', note, 2400), ('scope', scope, 300)):
            if not isinstance(value, str) or len(value) > limit or (label != 'scope' and not value.strip()):
                raise ValueError(f'invalid coding project {label}')
        if scope:
            if scope.endswith('/'):
                scope = scope[:-1]
                CodingExecutionContext.safe_path(scope + '/scope.py')
                scope += '/'
            else:
                CodingExecutionContext.safe_path(scope)
        identifier = note_id if note_id is not None else uuid.uuid4().hex
        if not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f]{32}', identifier):
            raise ValueError('invalid project note identifier')
        with closing(self._connect()) as connection, connection:
            if note_id is None:
                connection.execute('INSERT INTO project_notes(project,id,topic,note,scope) VALUES(?,?,?,?,?)',
                                   (project, identifier, topic.strip(), note.strip(), scope))
            else:
                updated = connection.execute('''UPDATE project_notes SET topic=?,note=?,scope=?,
                    updated_at=CURRENT_TIMESTAMP WHERE project=? AND id=?''',
                    (topic.strip(), note.strip(), scope, project, identifier))
                if not updated.rowcount:
                    raise ValueError('project note not found')
        return {'id': identifier, 'topic': topic.strip(), 'note': note.strip(), 'scope': scope}

    def delete_note(self, project, note_id):
        with closing(self._connect()) as connection, connection:
            return connection.execute('DELETE FROM project_notes WHERE project=? AND id=?',
                                      (project, note_id)).rowcount == 1

    def notes(self, project, *, query='', offset=0):
        if not (self.root / 'projects.sqlite3').is_file():
            return []
        with closing(self._connect()) as connection:
            rows = connection.execute('''SELECT id,topic,note,scope,updated_at FROM project_notes
                WHERE project=? AND instr(lower(topic || ' ' || note), lower(?)) > 0
                ORDER BY updated_at DESC, id LIMIT 50 OFFSET ?''', (project, query, offset)).fetchall()
        return [dict(row) for row in rows]

    def recall_notes(self, project, objective, paths):
        if not (self.root / 'projects.sqlite3').is_file():
            return []
        terms = re.findall(r'[a-z_][a-z_0-9]{2,}', objective.lower())
        for phrase in re.findall(r'[\u3400-\u9fff]{2,}', objective):
            terms.extend(phrase[i:i + 2] for i in range(len(phrase) - 1))
        terms = list(dict.fromkeys(terms))[:24]
        with closing(self._connect()) as connection:
            rows = connection.execute('''SELECT topic,note,scope FROM project_notes WHERE project=?
                ORDER BY updated_at DESC, id''', (project,))
            def relevant():
                for row in rows:
                    scope = row['scope']
                    if scope and not any(path.startswith(scope) if scope.endswith('/') else path == scope for path in paths):
                        continue
                    words = (row['topic'] + ' ' + row['note']).lower()
                    score = sum(term in words for term in terms) + int(bool(scope))
                    if score:
                        yield score, dict(row)

            return [row for _, row in nlargest(4, relevant(), key=lambda item: item[0])]

    def remember(self, project, repo, run_id, workflow):
        rounds = workflow.get('rounds', [])
        tests = rounds[-1]['tests'] if rounds else []
        if workflow.get('status') != 'passed' or not tests or not all(
            test.get('exit_code') == 0 and test.get('sandbox', {}).get('strict_boundary_verified') is True
            and not test.get('timed_out') for test in tests
        ):
            return
        rows = []
        for path in rounds[-1]['review']['changed_files']:
            try:
                source = CodingExecutionContext.read(repo, path)
            except (OSError, ValueError):
                continue
            if source is not None:
                rows.append((project, path, hashlib.sha256(source).hexdigest(), run_id, len(tests)))
        if rows:
            with closing(self._connect()) as connection, connection:
                connection.executemany('''INSERT INTO coding_evidence(project,path,source_sha256,run_id,tests)
                    VALUES(?,?,?,?,?) ON CONFLICT(project,path,source_sha256) DO UPDATE SET
                    run_id=excluded.run_id, tests=excluded.tests, updated_at=CURRENT_TIMESTAMP''', rows)

    def recall(self, project, repo, relevant_paths):
        if not relevant_paths or not (self.root / 'projects.sqlite3').is_file():
            return []
        matches = []
        with closing(self._connect()) as connection:
            for path in dict.fromkeys(relevant_paths):
                try:
                    data = CodingExecutionContext.read(repo, path)
                except (OSError, ValueError):
                    continue
                if data is None:
                    continue
                row = connection.execute('''SELECT path,source_sha256,run_id,tests,updated_at FROM coding_evidence
                    WHERE project=? AND path=? AND source_sha256=?''',
                    (project, path, hashlib.sha256(data).hexdigest())).fetchone()
                if row:
                    matches.append(dict(row))
        return [{k: v for k, v in row.items() if k != 'updated_at'}
                for row in nlargest(6, matches, key=lambda row: row['updated_at'])]
