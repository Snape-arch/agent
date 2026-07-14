# Real task evidence contract

Competition evidence is not a screenshot and not a capability claim. It is a durable `clawos.real-task-evidence.v1` record produced by an actual execution. The console defaults to verified records only; deterministic providers, fixture data, generated audio, examples and Mock runs remain available to regression tests but are excluded from the score.

Every chain must contain the same eight evidenced stages:

1. `user_goal`: original request or approved task ticket.
2. `agent_plan`: bounded plan, risks and approval points.
3. `subagent_delegation`: role, isolated assignment, dependency and returned result for each subagent.
4. `tool_trace`: ordered tool calls with timestamps, duration, status and redacted arguments.
5. `rework`: the failed or challenged version, reason and changed result. A no-op “no rework” label is not accepted.
6. `quality_gate`: machine checks plus independent review; status must be `pass`.
7. `final_artifacts`: files with byte size and SHA-256, never a filename-only claim.
8. `knowledge_capture`: durable knowledge or learning record that can be retrieved in a later task.

## The five fixed demonstrations

| Scenario | Required real input | Minimum quality evidence | Final artifacts |
|---|---|---|---|
| `coding` | User repository and issue | failing test → patch → passing tests → diff review | patch/diff, test log, review record |
| `meeting` | User-supplied audio; no generated tone or sidecar-only substitution | actual ASR engine, diarization review, decision/action reconciliation | transcript, minutes, `.eml`, `.ics`, knowledge record |
| `data_analysis` | User-supplied workbook or CSV | formula integrity, totals reconciliation, filters/freeze panes and LibreOffice render | analysis workbook, management report, rendered QA |
| `paper` | User-supplied long PDF | page-grounded citations, annotation persistence, evidence challenge and reproduction gate | annotated paper data, evidence Q&A, reproduction plan |
| `learning` | Retrieved knowledge items from the user library | dependency graph, quiz evidence, wrong-answer cause and scheduled review | route graph, quiz result, error review, mastery record |

## Capture and verify

Each execution writes a run JSON using the existing `RunRecord` fields plus `provenance` and `workflow.evidence_chain`. Set `provenance.input_origin` to only one of `user_supplied`, `repository`, or `live_connector`; set the real provider and execution mode. Never edit these fields merely to pass the gate.

```powershell
.\.venv\Scripts\python.exe scripts\verify_real_evidence.py evidence\coding.json evidence\meeting.json evidence\data_analysis.json evidence\paper.json evidence\learning.json --memory-db memoryos.db --out output\real-evidence\verification.json
```

The command hashes files again, rejects incomplete or non-real chains, and persists only eligible runs. Until all five exist, the console intentionally shows a high-quality empty slot rather than sample progress.

## Reproducible environment

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap_test_env.ps1 -InstallDesktopTools
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\test_all.ps1
```

`requirements-test.txt` is the deterministic suite profile. Heavy local-model, vector and ASR backends remain in `requirements.txt` and can be added with `-IncludeLocalAI`; their model weights are external acceptance gates rather than prerequisites for the core suite.
