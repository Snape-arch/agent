"""Historical ClawOS maintenance cases, using exact files from Git revisions."""

IMPORTS = """\
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
sys.path.insert(0, str(Path.cwd() / 'clawos'))
"""

ATOMIC = """\
import os
import json
from services.file_transactions import write_text
from services.artifact_delivery_service import ArtifactDeliveryService

def verify(writer, name, retries, exception=PermissionError):
    real_replace = os.replace
    with TemporaryDirectory(dir='.') as directory:
        root = Path(directory).resolve()
        target = root / name
        target.write_text('old', encoding='utf-8')
        attempts = []

        def transient(source, destination):
            assert target.read_text(encoding='utf-8') == 'old', 'published before atomic replace'
            attempts.append(Path(source))
            if len(attempts) <= retries:
                raise exception('injected replace failure')
            real_replace(source, destination)

        should_fail = retries >= 8 or exception is not PermissionError
        with patch('os.replace', side_effect=transient), patch('time.sleep'), patch('tempfile.gettempdir', return_value=str(root)):
            try:
                writer(root, target)
            except exception:
                if not should_fail:
                    raise AssertionError('transient replace should recover') from None
            else:
                assert not should_fail, 'persistent failure silently ignored'
        assert len(attempts) == (1 if exception is not PermissionError else min(retries + 1, 8)), 'unexpected retry count'
        assert not any(path.exists() for path in attempts), 'temporary replacement was not cleaned up'
        expected = 'old' if should_fail else 'new'
        if not should_fail and name.endswith('.json'):
            assert json.loads(target.read_text(encoding='utf-8')) == {'state': expected}
        else:
            assert target.read_text(encoding='utf-8') == expected

writers = [
    (lambda root, target: write_text(target, 'new'), 'text.txt'),
    (lambda root, target: ArtifactDeliveryService(target, [root])._write({'state': 'new'}), 'registry.json'),
]
"""

PDF = """\
from types import SimpleNamespace
from services.pdf_page_renderer import PdfPageRenderer

def check(*invalid_pages):
    def fail_open(*args, **kwargs):
        raise AssertionError('invalid input reached PDF parser')

    # Exercise the real cache and input validation without the PDF library.
    with TemporaryDirectory(dir='.') as directory, patch.dict(sys.modules, {'fitz': SimpleNamespace(open=fail_open)}):
        source = (Path(directory) / 'paper.pdf').resolve()
        source.write_bytes(b'%PDF-fixture')
        stat = source.stat()
        renderer = PdfPageRenderer()
        value = {'page': 1}
        renderer.cache[(str(source), stat.st_mtime_ns, stat.st_size, 1)] = value
        assert renderer.render(source, 1) == value
        for page in invalid_pages:
            try:
                renderer.render(source, page)
            except ValueError:
                pass
            else:
                raise AssertionError('invalid page reached cached result')
        assert renderer.render(source, 1) == value
"""

EVIDENCE = """\
import sqlite3
from services.document_evidence_policy import source_usable

db = sqlite3.connect(':memory:')
db.row_factory = sqlite3.Row
db.executescript('''
CREATE TABLE documents(id INTEGER, status TEXT, metadata TEXT);
CREATE TABLE document_chunks(document_id INTEGER, citation TEXT, metadata TEXT);
INSERT INTO documents VALUES (1, 'ready', '{}'), (2, 'ready', '{}'), (4, 'needs_review', '{}');
INSERT INTO document_chunks VALUES (1, 'doc:1#page=1', '{}'),
    (4, 'doc:4#page=2', '{"review_required":true}'), (3, 'doc:3#page=1', '{}');
''')
"""

TASKS = [
    dict(id='atomic-publish', baseline='5d9af15a6861905a86bab06495ddfbc39f367935',
         fixed='bcb334fc0718445320f440dfb013489e33277a3d',
         paths=['clawos/services/file_transactions.py','clawos/services/artifact_delivery_service.py'],
         dependencies=[],
         objective='Both write_text and ArtifactDeliveryService._write fail on transient atomic replace permission errors. '
                   'Repair both paths. Use up to 8 attempts only for PermissionError, keep atomically replacing the same sibling '
                   'temporary file with bounded retry waits, and re-raise persistent failures. Other OS errors must fail immediately. '
                   'Keep the old destination intact on failure, clean the temporary file, and preserve the existing APIs and locking.',
         public=ATOMIC+"\nfor writer, name in writers:\n    verify(writer, name, 2)\n",
         post=ATOMIC+"\nfor writer, name in writers:\n    verify(writer, name, 7)\n    verify(writer, name, 8)\n    verify(writer, name, 8, OSError)\n"),
    dict(id='pdf-cache-type', baseline='68f6c2ee148794f523b2ce2bde6168e823a5536b',
         fixed='c8d183dbc8d015638022b1f3fc02067cf4eef064', paths=['clawos/services/pdf_page_renderer.py'],
         dependencies=[],
         objective='PdfPageRenderer.render can return a cached page for True or 1.0 because they compare equal to integer 1. '
                   'Reject any non-exact integer and nonpositive page with ValueError before cache lookup or PDF parsing. '
                   'Keep valid integer page hits and current path, PDF-size and page bounds.',
         public=PDF+'\ncheck(True)\n', post=PDF+'\ncheck(1.0, False, 0, -1, None, "1", [1])\n'),
    dict(id='citation-exact-source', baseline='bbc6929b34ab7566596cebadbd80fa01ac2b47cf',
         fixed='76f5e4fcad31e1152d6238e052d05dc314e7550a', paths=['clawos/services/document_evidence_policy.py'],
         dependencies=[],
         objective='Make source_usable reject doc: sources if the authoritative document row or all chunks are missing. '
                   'Fragment citations must resolve to the exact surviving chunk, not another chunk from the same document. '
                   'Keep review checks, document-level lookups, non-doc compatibility and the read-only SQLite contract.',
         public=EVIDENCE+"\nassert source_usable(db, 'doc:1#page=1') is True\n"
                         "assert source_usable(db, 'doc:1#page=9') is False, 'stale fragment fell back to surviving chunk'\n"
                         "assert source_usable(db, 'doc:4#page=2') is False\n",
         post=EVIDENCE+"\nassert source_usable(db, 'doc:2') is False, 'empty document accepted'\n"
                       "assert source_usable(db, 'doc:3#page=1') is False, 'orphan chunk accepted'\n"
                       "assert source_usable(db, 'doc:1') is True\n"
                       "assert source_usable(db, 'doc:4') is False\n"
                       "assert source_usable(db, 'https://example.invalid/evidence') is True\n"),
]
