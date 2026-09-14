# Cross-module evidence and learning acceptance

Run from the repository root:

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/cross_module_acceptance.py
```

Report: ignored `clawos/output/cross-module-acceptance.json`. The runner fails when any case fails or is skipped; each case includes duration, errors and fixture origin. Human correctness and manual rework remain null until actually measured.

## Current checks

| Journey | Checked outcome | Boundary |
|---|---|---|
| Document questions | Different questions select different evidence, including late chunks; missing evidence blocks; review gate | Lexical retrieval returns excerpts, not a verified answer |
| Scanned materials | Mixed-page detection, review gates, engine failure/partial status and provenance | Fixtures/mocks do not measure production OCR accuracy |
| Meetings | Explicit labels preserved; unattributed text not lost; ASR no longer invents speaker alternation | No real audio speaker-identity model is claimed |
| Office edits | DOCX/PPTX run preservation, XLSX styles/cache gates, PDF reopen/rollback | Does not establish WPS/Word rendering parity |
| Code repair | Actual fixture repo modification, tests, rollback and bounded retry | Not an independent real-repository success rate |
| Education | Actual PDF/DOCX parse, source/version ownership, model-output validation, executable project/ZIP, chapter drafts and recovery | Model quality is not established by mocked response tests |

Final cross-module regression: **45/45**, September 14, 2026. Full worktree run: **590 tests; one subprocess timeout**, with the affected self-evolution test passing a separate rerun in 12.422 seconds. This is not a fully green original run.

Real browser: configured model generated three chapter questions; draft survived reload; complete independent inquiry stayed needs_review; chapter switch restored answers. Desktop layout had no horizontal overflow. Provider unavailable returned a truthful error without a success event. These use a synthetic public QA text, not private learning materials.

## Product scope and remaining acceptance

Education and paper/knowledge workflows share parsing and evidence selection, while learning records remain separate and imports do not silently publish into the knowledge index. Citation revisions identify the material or passage scope. Review-required passages are withheld from tutoring/scoring/project evidence.

Chapter learning currently splits identifiable heading spans within source fragments. It offers subject-directed questions and an independent inquiry record (question, method, observed result, reflection, source quote). Questions are model-generated and quotations are validated; students' submissions are not automatically certified. The existing executable RAG project remains fixed code, not independently edited student code.

Before claiming top-tier quality, add separately held-out, teacher-labelled materials and real recordings/repositories; capture initial and corrected outputs, per-task correctness, actual human review time and recovery. Add reviewed subject rubrics, grading, complete cross-chapter prerequisite paths, robust formula/table teaching and sandboxed independent learner code. Do not convert fixture pass rates into these claims.
