# File Generation and Paper Learning Analysis

Date: 2026-06-16

## What is now supported

- Structured local file generation under sandboxed allowed roots.
- Meeting minutes and data-style outputs can be emitted as Markdown, JSON, TXT, and PDF-oriented artifacts by workflow code.
- Research PDFs can trigger a customer-selectable paper learning analysis report.
- The paper report generator can output:
  - Markdown for editing and knowledge-base ingestion.
  - PDF for customer-facing delivery.

## Paper Learning Analysis Workflow

Entry points:

- Tool: `research_pdf` with `action=learning_analysis`
- API: `POST /api/workspace/research/learning-analysis`
- Capability probe: `GET /api/workspace/capabilities`

Inputs:

- `document_id` or `file_path`
- `title`
- `output_dir`
- `formats`: `["markdown", "pdf"]`
- `depth`: 1 to 5
- `question_count`: 6 to 80

Generated structure:

- Paper deep analysis title.
- Global overview.
- Extracted paper framework.
- Core learning questions.
- Self-questioning topic tree from L1 to L5.
- Evidence snippets with page references.
- Concept glossary.
- Limitations and reproducibility checks.
- Systematic study suggestions.

## Current Boundary

The current generator is deterministic and evidence-based. It reads extracted PDF text, detects outline candidates and concepts, then builds a self-questioning learning report with page-level evidence.

This is intentionally low-risk for the competition demo: it does not hallucinate hidden paper details through an external model. Later, DeepSeek or a local model can enrich each question node while preserving the same API, output paths, and citation evidence contract.

## Validation

```powershell
python -m unittest clawos.tests.test_workspace_services clawos.tests.test_frontend_static
python -m py_compile clawos\workspace_services.py clawos\scripts\tool_runner.py clawos\clawos_server.py clawos\security\policy.py
git diff --check
```

Result: `19 tests OK`; compile OK; diff whitespace check OK with only Windows LF/CRLF warnings.

## Demo Output

Generated from the provided example PDF:

- `output/pdf/paper_learning_analysis_sample_v5/GalaxyVS_Sample_Learning_Analysis_learning_analysis.md`
- `output/pdf/paper_learning_analysis_sample_v5/GalaxyVS_Sample_Learning_Analysis_learning_analysis.pdf`
