# Reliable coding collaboration acceptance — 2026-10-04

Continues `42e798e`. This phase upgrades coding collaboration from fixed role answers to a model-planned, bounded edit DAG. It preserves the previous negative live-model record rather than replacing its verdict. Runtime data, synthetic repositories, model receipts and logs remain ignored under `clawos/output`; existing executables and weights under `tools` are reused without modification.

## Delivered mechanism

- `ReliableCollaborationService` asks the configured provider to split the supplied objective and authorized source files into up to eight concrete tasks. It validates identifiers, write scopes, dependency membership and acyclicity, then freezes the DAG. Planning-format repair is bounded. This is dynamic initial decomposition, not unrestricted mid-run graph expansion.
- One immutable baseline captures the original checkout's tracked/dirty content through the existing workspace service. Each attempt receives its own Git worktree; independent model workers run concurrently, and dependent workers receive real ancestor commits. Workers see only their assignment, writable files and read-only dependency files. They cannot select commands, invoke arbitrary tools or write the source checkout.
- The coordinator validates exact replacement/create/hunk proposals and syntax, commits accepted edits, and checkpoints each completed task before releasing dependents. Failed/interrupted attempts remain visible and use fresh worktrees. Retry bounds do not reset on resume.
- Integration applies worker commits in deterministic DAG order. Git performs normal three-way merging; identical already-applied edits are skipped. Actual overlapping conflicts supply base/ours/theirs to a bounded resolver restricted to conflict paths. A failed or out-of-scope resolution remains blocked. Nothing is pushed or merged into the user's branch automatically.
- Caller-selected test commands run against the integrated workspace through `CodingWorkflowService`. Two bounded repairs may use actual failure output. Every failed test round is retained. A separate model review sees final files, integrated diff and actual tests; review cannot override failed tests or unresolved conflicts. A valid negative review is preserved, while malformed review JSON/types can receive one format retry.
- An OS-held, nonblocking process lock prevents replacing a live coordinator and is released on actual process death. Atomic fsync/replace checkpoints bind the objective, caller, authorized files, commands and limits. Recovery verifies baseline/workspace metadata, accepted HEAD/patch digests, frozen provider configuration and captured model receipts. External source changes, corrupted receipts/checkpoints or changed requests reject reuse. It is single-host process ownership, not a distributed lease.
- Shared model-call/token admission covers concurrent workers. Interrupted/unknown usage is charged conservatively; cumulative wall budget includes the interval since a crashed coordinator's last recorded start. Suspended time is never successful-load evidence. Default bounds: 24 model calls, 32,000 token budget, 120-second calls/tests, 900-second run budget, three worker attempts; concurrency defaults to three and is capped at four.
- Original custom-role execution now saves each completed parallel role rather than waiting for a whole wave; cancellation drains pending tasks. Checkpoints use the shared atomic writer. Synchronous tool callbacks move off the event loop. The coding guarantees above belong to `reliable_coding`, not all legacy arbitrary side-effect tools.

## Entry points

`POST /api/subagents/run` and the existing `autonomous_subagents` tool support:

```json
{
  "team_profile": "reliable_coding",
  "repo_path": "C:/path/to/repository",
  "objective": "Describe concrete acceptance requirements",
  "allowed_paths": ["src/module.py"],
  "test_commands": [["python", "-m", "unittest", "discover"]],
  "confirmed": true
}
```

Use `GET /api/subagents/collaboration/{run_id}` for recorded progress and coordinator ownership. To resume, send the same frozen request with `resume_run`; no live owner, task/config change or evidence corruption is permitted. A passed replay verifies evidence without calling models again. Persistent run records expose attempts, conflicts, repairs and review. Every result requires human release of its isolated changes.

## Verification

| Check | Final result | Ignored evidence |
| --- | --- | --- |
| Serial isolated full Python regression | **832/832**, 654.066 s; zero failures/errors | `output/regression/b4cd67d1194a421eb3de4ce488f49be8`, `output/reliable-collaboration-full-regression.log` |
| Collaboration mechanism tests | **21/21**, 167.989 s | `output/regression/fe6ca03c003a446289c4be333f581d6b` |
| Original role-service compatibility/cancellation | **9/9**, 0.593 s | `output/regression/d9f0021604384a2aa00ec0fc01cf0ec9` |
| Final scenario-tool output-root binding | **2/2**, 0.306 s | `output/regression/af2175fcc7804517a11f37575dacbf95` |
| Existing Node tests | **17/17**, 271.1461 ms | Existing document editor tests; no JavaScript changes |
| Actual local Qwen: dynamic dependencies, parallel edits and crash recovery | **PASS**, 96.594 s, six actual model calls, 2,358 charged tokens, peak two worker requests | `output/reliable-collaboration-verified-recovery-20261004/report.json` |
| Actual local Qwen: same-function Git conflict and resolution | **PASS**, 55.281 s, five actual model calls, 1,633 charged tokens, peak two worker requests, one actual conflict resolution | `output/reliable-collaboration-verified-conflict-20261004/report.json` |

The full 832-test discovery precedes the final scenario-tool output-root adjustment and the two new entry tests. Those final lines passed their separate 2/2 entry check; this is not a claim that a single 834-test full run occurred. Focused fixtures use actual Git worktrees/process termination but controlled model responses and a substituted test executor. They are mechanism regression, not live-model or OS-isolation proof.

The final real-model arithmetic run planned three tasks with genuine dependencies and passed 15 harness assertions across five input pairs. Its child actually exited with code 17 after the multiplication worker's commit `edc8ecf4a4510d732a4c16ebe54838134263c60e` was durably recorded. Recovery reused that exact commit and created a fresh attempt for the interrupted addition worker. The conflict run planned two independent edits to the same function, triggered a real Git conflict, resolved it through a model request restricted to the conflicting file, and passed five harness assertions. Both final reports verified unchanged loaded sources, preserved original synthetic checkouts, real provider receipts, actual integrated tests and model review. No fixture outcome substitutes for these two live runs.

The existing local `Qwen3.5-9B-Q4_K_M.gguf` and llama-server were reused read-only on loopback port 18926 (two slots, context 8192, GPU layers 20). The owned model process was closed after acceptance; production and the previous isolated frontend preview were not restarted. Observed Windows Job Object execution enforced process/memory limits but failed low-integrity workspace labeling, with filesystem isolation and non-bypass direct socket isolation both false. An authenticated proxy default-denied external traffic. `production_sandbox_ready` was false; passing task assertions does not upgrade that boundary.

Both live reports capture the same unchanged core fingerprints:

| Core source | SHA256 |
| --- | --- |
| `services/reliable_collaboration.py` | `4d43501e340d6031cdcc44b3a118c269fd5c1068f1755f5547fe840faea1f83a` |
| `services/autonomous_subagent_service.py` | `fa4299e081ec404bb3d8336a08e119be059817828c8aebf4d87ee0391cbdded0` |
| `clawos_server.py` | `c73fadbcec760fb42c68d04715e2a1fed4d3572b66550640ab29ec47e5be42dd` |
| `scripts/reliable_collaboration_acceptance.py` | `f6cb4484b7ab4a2acfda61e13acc6437b9085ad7de1103bd636e4f5a65d49667` |

Recovery report SHA256: `7e1cff701a3bd1bd25cbf79fd5816aa7bf95aa904ab8aed1d332cd2717cf1359`; conflict report: `40a7f36aba99711d160c60207415645adac16c41045c7c28949c54a030c21b4b`. The final nine-source bundle is `2bc3e66ca0230f86b6c1b012a22ddf98ab5ac96c925c4b9dbca64e24febce7a0`, recorded in ignored `output/reliable-collaboration-source-fingerprints.json` (sorted path/hash entries, canonical sorted-key JSON, SHA256). It covers the four core files plus function schema, scenario tool and three test files. The everyday `memoryos.db` remains `8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`.

Delivery follows the user's authorized `Snape-arch/agent` remote and `codex/coding-agent-competitive-p0-p2` branch. Only related source/tests/acceptance/handoff documents are included; `tools`, weights, credentials, databases, output and the pre-existing skill-registry modification are excluded. No force push or master merge.

Intermediate negative attempts remain in ignored output: initial strict planner parsing failed (42.453 s); the first broader-context workers exceeded their assignments (130.375 s and a later repeat); after narrowing worker context, actual integrated tests passed but malformed reviewer JSON correctly rejected the run (107.172 s). These are not successful task outcomes. Later developmental runs exercised a real crash/restart and actual conflict resolution, but final acceptance must match unchanged loaded source fingerprints.

Reproduce with the existing local loopback model, without loading credentials:

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/run_regression.py
.\clawos\.venv\Scripts\python.exe clawos/scripts/reliable_collaboration_acceptance.py --live --url http://127.0.0.1:18926/v1 --out clawos/output/collaboration-recovery --exercise-recovery
.\clawos\.venv\Scripts\python.exe clawos/scripts/reliable_collaboration_acceptance.py --live --url http://127.0.0.1:18926/v1 --scenario conflict --out clawos/output/collaboration-conflict
```

The recovery harness calls `os._exit(17)` only in its owned synthetic child, after a real accepted worker commit is durably recorded. All model outputs are from the actual configured provider; independent fixture assertions are authored by the harness, not proposed by workers. The harness captures source fingerprints at import and rejects on-disk changes during acceptance.

## Boundaries

- Real model acceptance uses small synthetic Python repositories. It proves this bounded execution/recovery mechanism, not a public-repository success rate, SWE-bench performance, independent reviewer quality, teacher gain or parity with Claude Code/Codex.
- Workers, resolver and reviewer can use the same configured model; separate requests/context are not independent people or independently trained judges. Strong caller/hidden tests remain necessary. Whole-file correctness is not established by a model's approval alone.
- Files are bounded UTF-8 text: 24 authorized paths, 128 KB per file, 384 KB context envelope; token admission may reject smaller inputs. No deletes/binary changes, arbitrary shell actions, remote Git delivery or general office/data collaboration upgrade is claimed.
- OS sandbox selection is inherited from coding execution. The observed local acceptance may use the compatibility Windows Job Object with process/memory limits and an authenticated egress proxy. That does not provide full filesystem isolation or non-bypass socket isolation. `CLAWOS_REQUIRE_OS_SANDBOX=1` fails closed without the required installed boundary; this phase does not install host ACLs or change production policy.
- Source preservation checks tracked Git state and authorized files, not every ignored/runtime file or every host resource. The caller approves test commands; the model cannot supply them. Source drift blocks replay/release status and does not overwrite external changes.
- Checkpoint hashes detect corruption and bind internal evidence; they are not an external cryptographic attestation or organizational authentication. No distributed multi-host ownership, continuously observed multi-day load or automatic worktree pruning was accepted here. Existing workspace lifecycle metadata remains available.
- The previous document 48-hour test remains FAILED. It is unrelated to these short coding tests and was not restarted.
