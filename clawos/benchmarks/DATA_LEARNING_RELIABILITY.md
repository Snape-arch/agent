# Database, knowledge retrieval and learning continuity

## Changes

- Context snapshot retention now deletes only the current session's older snapshots. Previously saving one session could delete every other session's snapshots. Already deleted snapshots cannot be reconstructed by this fix.
- Backups have collision-resistant names and a SQLite integrity check. Restore reads committed WAL pages through SQLite's backup API, checks that the source is a ClawOS database, prepares schema migrations in a temporary copy, then backs up the live store and restores under its lock. It no longer replaces the file underneath existing connections. Failed staging leaves the live data intact.
- `scripts/database_health.py` inspects integrity, foreign keys, database row counts, missing original document files and unlinked legacy knowledge without initializing or migrating the database. `--backup-dir` creates a verified SQLite backup. Uploaded source files and external vector assets are separate and must be retained; this is not a complete workspace backup.
- Chinese BM25 uses adjacent character pairs so differently phrased questions can match source sentences. This fixes a recall failure; it is still lexical retrieval, not a new semantic model or measured general recall improvement.
- Chapter state distinguishes not started, answering, awaiting review, needs revision, disagreement and passed. The current question version and latest submission determine the state; a new submission cannot inherit an old pass.
- A learning progress summary resumes unfinished work. Review feedback becomes a dimension-specific remediation list with original quotations and explicit disagreement. Tutor context now includes the current passage's saved explanation, chapter submissions, reviews and remediation, without importing unrelated passage assessments.
- Question versions are retrieved by their persistent ID, even after more than 200 activities. Revision mismatches are rejected. The activity display remains bounded.
- Browser drafts survive refresh and stay separate per material, passage/chapter, question version and learning step. Successful server saves clear corresponding local answer fields so old browser drafts cannot overwrite newer explanations when moving between practice and assessment. This is local browser recovery, not cross-device synchronization or concurrent editing resolution.
- Tutor Markdown uses the shared safe renderer for tables, lists and code. Education asset URLs are versioned.

## Verification

```powershell
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos/tests -p test_data_learning_reliability.py
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos/tests
.\clawos\.venv\Scripts\python.exe clawos/scripts/database_health.py --database clawos/memoryos.db --backup-dir output/database-backups
```

Focused reliability tests: 7/7, including an open destination connection, source WAL, pre-restore preservation, migration failure, session isolation, Chinese matching, long history and review lifecycle. Existing material tests: 10/10; knowledge transaction tests: 12/12; evidence/learning: 5/5; document review: 15/15; shared Markdown/SSE: 7/7. Full-suite result is recorded in `PROJECT_CONTEXT.md`. Intermediate full runs exposed an outdated current-question status assertion and an OCR assertion accidentally matching `959` inside a random revision hash. The latter now checks the full erroneous OCR token `959%+`.

The existing `clawos/memoryos.db` passed integrity and foreign-key checks. It contained 30 conversations, 552 legacy knowledge rows, 177 v2 records, 3 documents and 166 chunks; no unlinked legacy knowledge or missing source files were found. A verified 9,822,208-byte backup was created under ignored `clawos/output/database-backups`. The source database was not restored, cleaned or reindexed.

Browser reproduction uses isolated synthetic content, with no live model requests:

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/learning_preview.py --port 18903 --session data-learning-polish
.\clawos\.venv\Scripts\python.exe clawos/scripts/seed_learning_polish.py
```

Open the URL printed by the seed script. Verified: remediation and progress display, unsaved chapter answer surviving reload, revised submission returning to awaiting review, practice/assessment round trip retaining the newer answer, tutor nested lists/table, desktop and 390px layout without horizontal overflow. The seed script appends synthetic question/submission/review events to the named QA database only.

## Remaining limits

The production process was not restarted. Reviews remain formative model feedback, not proof of mastery or independently executed experiments. Chapter boundaries still follow extracted headings/fragments; whole-book prerequisites and teacher-calibrated subject evaluation are future work. Existing FastAPI/openpyxl/SWIG warnings are unrelated to these changes.
