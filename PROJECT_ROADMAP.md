# ClawOS Project Roadmap

## Product Positioning

ClawOS is a Windows local personal Agent OS. It is not a SaaS product, a generic chatbot, or a plain file knowledge base. The system should help one user run long-term work across models, tools, tasks, memory, knowledge, skills, and review loops.

Primary users:

- Teammates and reviewers who need to understand the project quickly.
- The local user who needs a practical daily workbench.

## Core Scenarios

The first four scenarios are fixed:

- Learning: course material, mistakes, concepts, review plans, progress records.
- Research: papers, citation Q&A, comparisons, reproduction notes, literature summaries.
- Project/code: repository analysis, task breakdown, implementation, tests, handoff notes.
- Office/artifacts: meetings, reports, spreadsheets, slide outlines, email drafts.

Do not add high-risk vertical domains such as medical, legal, or financial advice as first-class scenarios until the core local workflow is stable.

## Product Structure

The frontend should have two layers:

- Cover page: explains what ClawOS is, shows completed capabilities and readiness state, and provides a direct entry into the workbench.
- Workbench: the daily-use interface for tasks, files, projects, knowledge, model status, and outputs.

The first workbench screen should be task-first:

- Model status: API, local Qwen, or mock/offline test mode.
- Task input: text, attachments, web URLs, and project paths.
- Scenario entry points: learning, research, project/code, office.
- Recent context: tasks, documents, projects, and memories.
- Advanced views: tools, permissions, traces, and audits should stay available but not dominate the first screen.

## Backend Direction

Keep the current Python/FastAPI stack. Do not switch frameworks before the MVP+ flow is stable.

Next architecture step:

- Split `ModelService` from provider/config/fallback code.
- Split `KnowledgeService` from document, chunk, search, graph, and citation-answer code.
- Keep routes thin and move business logic out of `clawos_server.py` incrementally.

Target module boundaries:

- `api/`: FastAPI routes.
- `services/`: model, task, knowledge, skill, reflection services.
- `memoryos/` or repositories: SQLite persistence.
- `providers/`: model, search, embedding, OCR providers.
- `runtime/`: task queue, worker, step/event execution.
- `security/`: risk policy, confirmation, audit.

## Database Direction

Continue with SQLite for the local personal OS. The next database work is governance, not a database replacement.

Priorities:

- Schema migrations with version tracking.
- Backup and restore for MemoryOS, knowledge, tasks, and config metadata.
- Data partitions for sessions, memories, knowledge documents, chunks, tasks, events, skills, and reflection.
- Index and cleanup policy for documents, chunks, logs, uploads, and orphaned files.
- Privacy boundaries for local-only data, exportable data, and externally callable data.

Avoid multi-user, cloud sync, and distributed storage until the local product loop is reliable.

## Knowledge Direction

The core knowledge base is required:

- File upload.
- Document parsing.
- Chunking.
- Search.
- Citation Q&A.
- Basic knowledge graph.
- Connection to chat and task context.

Professional knowledge boards are optional if time is tight. The minimum acceptable version is template-based boards:

- Learning templates.
- Research templates.
- Project templates.
- Office templates.

These boards should save structured entries into the same knowledge system and be searchable/citable. Full expert graph analysis can wait.

## Model Strategy

Use three model modes:

- API primary: when `MODEL_API_KEY` is configured, use DeepSeek or another OpenAI-compatible API as the main model.
- Local Qwen fallback: when no API key is configured, use the local Qwen GGUF through a local OpenAI-compatible server.
- Mock test mode: only for offline validation, benchmark checks, CI, and handoff smoke tests.

The committed Qwen dependency is a manifest, not the binary weight file:

- Manifest: `clawos/models/qwen3_5_9b_q4_k_m.json`.
- Local weight target: `tools/models/qwen3.5-9b-gguf/Qwen3.5-9B-Q4_K_M.gguf`.
- Download script: `clawos/scripts/download_qwen_model.ps1`.
- Local server script: `clawos/scripts/start_qwen_llama_server.ps1`.

The UI should show whether the system is using API, local Qwen, or mock/offline mode.

## Task System Direction

The next task-system target is traceable, recoverable, and reusable tasks.

Each user request should become a task with:

- Title and scenario.
- Inputs: text, files, URLs, project paths.
- Model used.
- Tools used.
- Knowledge citations.
- Output artifacts.
- Step trace and event log.

Tasks should support:

- Running, waiting for confirmation, success, failure, cancellation.
- Retry and resume after failure.
- Reflection into lessons and improvement suggestions.
- Promotion of repeated successful flows into Skills.

Do not build a complex autonomous multi-agent scheduler before this task loop is stable.

## Skills Direction

Skills are reusable workflows. They are not a plugin marketplace.

Two classes are required:

- Built-in Skills: shipped with ClawOS, tested, default available, covering learning, research, project/code, and office.
- User Skills: generated from successful tasks or edited manually, then reviewed, tested, and published by the user.

Skill metadata should include:

- Trigger words.
- Scenario.
- Parameters.
- Steps and tools.
- Risk level.
- Example input/output.
- Evaluation tests.
- Version history.

## Permission Strategy

ClawOS is local-first, but high-risk operations need clear confirmation.

Must confirm:

- Writing, deleting, moving, or overwriting files.
- Shell commands.
- Git commit, push, reset, or branch operations.
- Network fetch/search.
- Real API calls that may spend quota.
- Long-running tasks.
- Model/runtime downloads.
- Exporting packages that may include personal data.

Generally safe without confirmation:

- Reading authorized workspace paths.
- Searching local knowledge.
- Mock validation.
- Viewing history, model status, and local task traces.
- Generating drafts that are not written to disk.

The Permission Center should show current authorization, recent high-risk operations, pending confirmations, and default policy.

## Priority Plan

P0: Demonstration loop

- Cover page.
- Task workbench.
- Model status display.
- Knowledge upload and citation Q&A.
- Task trace.
- One built-in Skill demo.
- Local Qwen fallback.

P1: Architecture and reliability

- `ModelService`.
- `KnowledgeService`.
- SQLite migrations.
- Backup and restore.
- Configurable Permission Center.
- Task retry/resume.

P2: Professional templates

- Learning template board.
- Research template board.
- Project template board.
- Office template board.
- Generate structured knowledge entries from task results.

P3: Early highlights

- Multi-model routing.
- Skill generation from successful tasks.
- OCR worker.
- Pluggable embedding/vector retrieval.
- Minimal background worker.

P3 work can move earlier when it improves the demo, fits existing modules, has low risk, and has a clear validation path.

## Immediate Next Steps

1. Build the cover page and make the workbench entry clear.
2. Show API/Qwen/mock model state in the UI.
3. Keep Qwen fallback validated through scripts and `/api/model/health`.
4. Start `ModelService` extraction before adding more model routing logic.
5. Start `KnowledgeService` extraction before expanding professional boards.
