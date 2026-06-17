# Office Artifacts: Built-in XLSX and PPTX Tools

Date: 2026-06-17

## Architecture Check

The architecture diagrams are mostly complete at the target-design level:

- The overall architecture includes Office Assistant, Competition Assistant, Data Agent, Tool Agent, MCP Tool Hub, MemoryOS, Reflection Engine, and local-first infrastructure.
- MemoryOS includes Table Memory as a multi-modal memory type.
- The sequence diagram already routes file/report generation through Planner, Research/Writer/Data agents, Tool Executor, MemoryOS, and Reflection.

The gap was implementation-level: XLSX/PPTX generation and editing were not exposed as ClawOS-owned tools. Relying on the Codex desktop spreadsheet/presentation plugins would not satisfy the requirement that the program itself can be moved to another computer and still complete the task.

## Implemented Capability

Added self-contained OpenXML helpers:

- `clawos/office_artifacts.py`

No Microsoft Office installation is required. No `openpyxl` or `python-pptx` dependency is required for the supported operations.

Supported XLSX operations:

- Create `.xlsx` workbooks with one or more sheets.
- Write string, number, and boolean cells.
- Edit existing generated/simple `.xlsx` files by setting cell values.

Supported PPTX operations:

- Create `.pptx` decks with title and bullet slides.
- Edit generated/simple `.pptx` files by replacing text in slide XML.

## Entry Points

Tool:

- `office_artifact`

Actions:

- `spreadsheet_create`
- `spreadsheet_edit`
- `presentation_create`
- `presentation_edit`

API:

- `POST /api/workspace/office/spreadsheets`
- `POST /api/workspace/office/spreadsheets/edit`
- `POST /api/workspace/office/presentations`
- `POST /api/workspace/office/presentations/edit`

Capability probe:

- `GET /api/workspace/capabilities`

## Security

`office_artifact` is a write tool and is covered by `ToolSecurityPolicy`:

- `file_path` and `output_path` must stay inside allowed roots.
- Tool execution requires confirmation through the existing write-tool policy.
- Artifacts are recorded in the `office_artifacts` table.

## Validation

```powershell
python -m unittest clawos.tests.test_workspace_services clawos.tests.test_frontend_static
python -m py_compile clawos\office_artifacts.py clawos\workspace_services.py clawos\scripts\tool_runner.py clawos\clawos_server.py clawos\security\policy.py
git diff --check
```

Result:

- `20 tests OK`
- Compile OK
- Diff whitespace check OK, with only Windows LF/CRLF warnings

Demo artifacts:

- `output/office/customer_metrics.xlsx`
- `output/office/customer_metrics_edited.xlsx`
- `output/office/customer_briefing.pptx`
- `output/office/customer_briefing_edited.pptx`

## Boundary

This is a portable, dependency-light Office baseline suitable for demos and common customer workflows. Advanced features such as charts, formulas, pivot tables, master slides, rich themes, images, and animations should be added incrementally as explicit product requirements.
