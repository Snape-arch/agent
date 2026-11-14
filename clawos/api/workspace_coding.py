"""Workspace coding HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
from fastapi import Request
import asyncio
import json
import os


class WorkspaceCodingAPI:
    def __init__(self, *,
        get_coding_workflow_service: Callable[..., Any],
        output_root_provider: Callable[[], Any],
        context_builder_provider: Callable[[], Any],
        memory_store_provider: Callable[[], Any],
        security_policy_provider: Callable[[], Any],
        upstream_provider_provider: Callable[[], Any],
        workspace_services_provider: Callable[[], Any],
    ):
        self.get_coding_workflow_service = get_coding_workflow_service
        self.output_root_provider = output_root_provider
        self.context_builder_provider = context_builder_provider
        self.memory_store_provider = memory_store_provider
        self.security_policy_provider = security_policy_provider
        self.upstream_provider_provider = upstream_provider_provider
        self.workspace_services_provider = workspace_services_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/workspace/coding/workflow', self.api_coding_workflow, methods=['POST'])
        self.router.add_api_route('/api/workspace/coding/strategy', self.api_coding_strategy, methods=['POST'])
        self.router.add_api_route('/api/workspace/coding/autonomous', self.api_autonomous_coding, methods=['POST'])
        self.router.add_api_route('/api/workspace/coding/ide-context', self.api_coding_ide_context, methods=['POST'])
        self.router.add_api_route('/api/workspace/coding/repository-intelligence', self.api_coding_repository_intelligence, methods=['POST'])
        self.router.add_api_route('/api/workspace/coding/lsp/probe', self.api_coding_lsp_probe, methods=['POST'])
        self.router.add_api_route('/api/workspace/coding/lsp/discovery', self.api_coding_lsp_discovery, methods=['GET'])
        self.router.add_api_route('/api/workspace/coding/lsp/semantic-graph', self.api_coding_lsp_semantic_graph, methods=['POST'])
        self.router.add_api_route('/api/workspace/coding/multilanguage-benchmark', self.api_coding_multilanguage_benchmark, methods=['POST'])
        self.router.add_api_route('/api/workspace/coding/oss-corpus-benchmark', self.api_coding_oss_corpus_benchmark, methods=['POST'])
        self.router.add_api_route('/api/workspace/coding/outcome-benchmark', self.api_coding_outcome_benchmark, methods=['POST'])
        self.router.add_api_route('/api/workspace/coding/review-gate', self.api_coding_review_gate, methods=['POST'])
        self.router.add_api_route('/api/workspace/coding/worktrees', self.api_coding_worktree_create, methods=['POST'])
        self.router.add_api_route('/api/workspace/coding/worktrees', self.api_coding_worktree_status, methods=['GET'])
        self.router.add_api_route('/api/workspace/coding/worktrees/merge-plan', self.api_coding_worktree_merge_plan, methods=['POST'])
        self.router.add_api_route('/api/workspace/coding/worktrees/remove', self.api_coding_worktree_remove, methods=['POST'])
        self.router.add_api_route('/api/workspace/coding/commit', self.api_coding_workspace_commit, methods=['POST'])

    async def api_coding_workflow(self, request: Request):
        data = await request.json()
        action = str(data.get("action") or "inspect")
        service = self.get_coding_workflow_service()
        try:
            if action == "inspect":
                result = service.inspect(
                    data.get("repo_path", ""),
                    data.get("query", ""),
                    data.get("limit", 80),
                    token_budget=data.get("token_budget", 12000),
                    focus_paths=data.get("focus_paths") or [],
                    diagnostics=data.get("diagnostics") or [],
                )
            elif action == "discover_tests":
                result = {
                    "commands": service.discover_tests(
                        data.get("repo_path", ""), data.get("changed_paths") or []
                    )
                }
            elif action == "plan":
                result = service.plan(data.get("repo_path", ""), data.get("objective", ""), data.get("changes") or [], data.get("test_commands") or [])
            elif action == "execute":
                result = await asyncio.to_thread(service.execute, data.get("repo_path", ""), data.get("objective", ""), data.get("changes") or [], data.get("test_commands") or [], confirmed=bool(data.get("confirmed")), repair_rounds=data.get("repair_rounds") or [], max_rounds=data.get("max_rounds", 2), timeout_seconds=data.get("timeout_seconds", 180), actor=data.get("actor", "coding-agent"), acceptance_criteria=data.get("acceptance_criteria") or [])
                if result.get("status") == "passed" and data.get("create_change_request"):
                    files = sorted({str(item.get("path") or "") for item in (data.get("changes") or []) if item.get("path")})
                    result["change_request"] = self.workspace_services_provider().create_git_change_request(data.get("repo_path", ""), data.get("commit_message") or data.get("objective") or "Coding workflow change", files, created_by=data.get("actor", "coding-agent"))
            elif action == "rollback":
                result = await asyncio.to_thread(service.rollback, data.get("repo_path", ""), data.get("checkpoint", ""), confirmed=bool(data.get("confirmed")), actor=data.get("actor", "user"))
            else:
                raise ValueError(f"unknown coding workflow action: {action}")
        except (ValueError, PermissionError, RuntimeError) as exc:
            raise HTTPException(409 if isinstance(exc, PermissionError) else 400, str(exc))
        return JSONResponse(result)


    async def api_coding_strategy(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.coding_strategy_service import CodingStrategyService
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(400, "request must be an object")
        service = CodingStrategyService(self.memory_store_provider(), self.output_root_provider())
        action = data.get('action', 'preview')
        try:
            if action == 'ingest':
                result = await asyncio.to_thread(service.evidence.ingest, data.get('folder', ''))
            elif action == 'failures':
                result = await asyncio.to_thread(service.evidence.failures)
            elif action == 'nominate_failure':
                result = await asyncio.to_thread(service.evidence.nominate_failures, data.get('category', 'format'))
            elif action == 'nominate_routing':
                result = await asyncio.to_thread(service.nominate_routing, data.get('decision_id', ''))
            elif action in {'rollout','rollout_evidence'}:
                from services.coding_rollout_service import CodingRolloutService
                rollout=CodingRolloutService(self.memory_store_provider(),self.output_root_provider())
                if action=='rollout_evidence':
                    result=await asyncio.to_thread(rollout.verified,data.get('run_id'))
                else:
                    if not self.upstream_provider_provider():raise HTTPException(503,'model provider is not initialized')
                    result=await rollout.run(data.get('run_id'),data.get('cases'),lambda _role:self.upstream_provider_provider(),
                        confirmed=data.get('confirmed') is True,limits=data.get('limits'),
                        baseline_mode=data.get('baseline_mode','single'),repetitions=data.get('repetitions',1))
            elif action in {'preview', 'run', 'compare'}:
                if not self.upstream_provider_provider():
                    raise HTTPException(503, "model provider is not initialized")
                factory = lambda _role: self.upstream_provider_provider()
                options = dict(limits=data.get('limits'), baseline_mode=data.get('baseline_mode', 'single'),
                               auto_route=data.get('auto_route', False))
                if action == 'preview':
                    result = await asyncio.to_thread(service.preview, data.get('case'), factory, **options)
                else:
                    result = await service.run(data.get('case'), factory, **options,
                        confirmed=data.get('confirmed') is True, paired=action == 'compare',
                        repetitions=data.get('repetitions', 1))
            else:
                raise ValueError('unknown coding strategy action')
        except (ValueError, KeyError, TypeError, OSError, PermissionError, RuntimeError, TimeoutError) as exc:
            raise HTTPException(409 if isinstance(exc, (PermissionError,TimeoutError)) else 400, str(exc))
        return JSONResponse(result)


    async def api_autonomous_coding(self, request: Request):
        from services.agentic_coding_loop_service import AgenticCodingLoopService
        from services.coding_session_store import CodingSessionStore
        from services.coding_trace_service import CodingTraceService

        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(400, "JSON object is required")
        action = data.get('action', 'run')
        if action not in ('run', 'start', 'resume', 'history', 'memory_list', 'memory_save', 'memory_delete'):
            raise HTTPException(400, "unknown coding session action")
        sessions = CodingSessionStore(self.output_root_provider() / 'coding' / 'continuity')
        repo_path = data.get('repo_path')
        if action in ('history', 'memory_list', 'memory_save', 'memory_delete'):
            if not isinstance(repo_path, str) or not repo_path.strip():
                raise HTTPException(400, "repo_path is required")
            project = sessions.project(repo_path, 'local-user')
            try:
                if action == 'history':
                    return JSONResponse({'checkpoints': await asyncio.to_thread(sessions.history, project)})
                if action == 'memory_list':
                    query, offset = data.get('query', ''), data.get('offset', 0)
                    if not isinstance(query, str) or len(query) > 200 or type(offset) is not int or offset < 0:
                        raise ValueError('invalid project memory search')
                    rows = await asyncio.to_thread(sessions.notes, project, query=query, offset=offset)
                    return JSONResponse({'notes': rows, 'next_offset': offset + 50 if len(rows) == 50 else None})
                if data.get('confirmed') is not True:
                    raise HTTPException(409, "confirmed=true is required to change project memory")
                if action == 'memory_save':
                    row = await asyncio.to_thread(sessions.save_note, project, data.get('topic'), data.get('note'),
                                                  data.get('scope', ''), data.get('note_id'))
                    return JSONResponse({'note': row})
                note_id = data.get('note_id')
                if not isinstance(note_id, str):
                    raise ValueError('note_id is required')
                return JSONResponse({'deleted': await asyncio.to_thread(sessions.delete_note, project, note_id)})
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        if not self.upstream_provider_provider():
            raise HTTPException(503, "model provider is not initialized")
        if not data.get("session_id") or (action != 'resume' and not data.get("task_id")):
            raise HTTPException(400, "task_id and session_id are required for a new run")
        service = AgenticCodingLoopService(
            self.upstream_provider_provider(),
            workflow=self.get_coding_workflow_service(),
            context=getattr(self.context_builder_provider(), "_coding_context", None),
            trace=CodingTraceService(self.output_root_provider() / "traces" / "coding.json"),
            learning_store=self.memory_store_provider(),
            session_store=sessions,
        )
        try:
            options = dict(
                objective=data.get("objective", ""),
                confirmed=data.get("confirmed") is True,
                focus_paths=data.get("focus_paths") or [],
                test_commands=data.get("test_commands"),
                diagnostics=data.get("diagnostics") or [],
                enable_lsp=bool(data.get("enable_lsp", False)),
                max_turns=data.get("max_turns", 8),
                timeout_seconds=data.get("timeout_seconds", 180),
                task_id=str(data.get("task_id") or ""),
                session_id=str(data.get("session_id") or "default"),
            )
            if action == 'run':
                result = await service.run(repo_path or '', actor_id=str(data.get("actor_id") or "local-user"), **options)
            else:
                if not isinstance(repo_path, str) or not repo_path.strip():
                    raise ValueError('repo_path is required')
                checkpoint_id = data.get('checkpoint_id') if action == 'resume' else None
                if action == 'resume' and (not isinstance(checkpoint_id, str) or not checkpoint_id):
                    raise ValueError('checkpoint_id is required')
                result = await service.run_resumable(repo_path, checkpoint_id=checkpoint_id,
                                                     pause_after=data.get('pause_after'), **options)
        except (ValueError, OSError, RuntimeError) as exc:
            raise HTTPException(
                409 if isinstance(exc, (PermissionError, TimeoutError)) else 400, str(exc)
            )
        return JSONResponse(result)


    async def api_coding_ide_context(self, request: Request):
        """Normalize untrusted editor state into repository-scoped context."""
        from services.coding_quality_service import IDEContextContract

        data = await request.json()
        try:
            return JSONResponse(IDEContextContract.normalize(
                data.get("repo_path", ""), data.get("context") or {}
            ))
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc))


    async def api_coding_repository_intelligence(self, request: Request):
        """Build the cached repo graph and optionally return a task slice/impact."""
        from services.repository_intelligence_service import RepositoryIntelligenceService

        data = await request.json()
        try:
            service = RepositoryIntelligenceService(
                self.output_root_provider() / "coding" / "repository-intelligence"
            )
            execution_coverage = {}
            if data.get("coverage_py_report"):
                execution_coverage = await asyncio.to_thread(
                    service.bind_coverage_py_report,
                    data.get("repo_path", ""), data.get("coverage_py_report") or {},
                    run_id=str(data.get("coverage_run_id") or ""),
                    command=data.get("coverage_command") or [],
                    tests_passed=data.get("coverage_tests_passed") is True,
                )
            graph = await asyncio.to_thread(
                service.build, data.get("repo_path", ""),
                semantic_graph=data.get("semantic_graph") or {},
                execution_coverage=execution_coverage,
            )
            result = {
                "schema": graph["schema"], "repo": graph["repo"],
                "digest": graph["digest"], "metrics": graph["metrics"],
                "incremental": graph["incremental"], "repo_map": graph["repo_map"],
                "evidence_summary": graph.get("evidence_summary") or {},
                "execution_coverage": graph.get("execution_coverage") or {},
            }
            objective = str(data.get("objective") or "").strip()
            focus_paths = data.get("focus_paths") or []
            if objective or focus_paths:
                result["task_context"] = service.task_slice(
                    graph, objective, focus_paths=focus_paths,
                    max_files=int(data.get("max_files") or 24),
                    max_nodes=int(data.get("max_nodes") or 240),
                    depth=int(data.get("depth") or 2),
                )
            changed_paths = data.get("changed_paths") or []
            if changed_paths:
                result["impact_analysis"] = service.impact_analysis(
                    graph, changed_paths, depth=int(data.get("impact_depth") or 3)
                )
            if bool(data.get("include_graph")):
                result["nodes"] = graph["nodes"]
                result["edges"] = graph["edges"]
            return JSONResponse(result)
        except (ValueError, OSError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))


    async def api_coding_lsp_probe(self, request: Request):
        from services.lsp_bridge_service import DEFAULT_LANGUAGE_SERVER_MANAGER

        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(
                409, "confirmed=true is required to launch a language server"
            )
        command = data.get("command") or []
        repo_path = data.get("repo_path", "")
        action = str(data.get("action") or "symbols")
        try:
            if action == "stop":
                stopped = await asyncio.to_thread(
                    DEFAULT_LANGUAGE_SERVER_MANAGER.stop, repo_path, command
                )
                return JSONResponse({"stopped": stopped})
            bridge = await asyncio.to_thread(
                DEFAULT_LANGUAGE_SERVER_MANAGER.get,
                repo_path,
                command,
                timeout_seconds=data.get("timeout_seconds", 5),
            )
            path = data.get("document_path", "")
            language_id = data.get("language_id", "")
            if action == "status":
                result = bridge.status()
            elif action == "symbols":
                result = {"symbols": await asyncio.to_thread(
                    bridge.document_symbols, path, language_id=language_id
                )}
            elif action in {"definition", "hover"}:
                method = getattr(bridge, action)
                result = {action: await asyncio.to_thread(
                    method, path, data.get("line", 0), data.get("character", 0),
                    language_id=language_id,
                )}
            elif action == "references":
                result = {"references": await asyncio.to_thread(
                    bridge.references, path, data.get("line", 0),
                    data.get("character", 0), language_id=language_id,
                )}
            elif action == "rename":
                result = {"workspace_edit": await asyncio.to_thread(
                    bridge.rename, path, data.get("line", 0),
                    data.get("character", 0), data.get("new_name", ""),
                    language_id=language_id,
                )}
            elif action == "diagnostics":
                result = {"diagnostics": await asyncio.to_thread(
                    bridge.diagnostics, path, language_id=language_id
                )}
            else:
                raise ValueError("unsupported LSP action")
            return JSONResponse({**bridge.status(), **result, "persistent": True})
        except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
            raise HTTPException(400, str(exc))


    async def api_coding_lsp_discovery(self):
        from services.lsp_semantic_graph_service import LanguageServerDiscovery
        return JSONResponse(LanguageServerDiscovery().discover())


    async def api_coding_lsp_semantic_graph(self, request: Request):
        from services.lsp_semantic_graph_service import LSPSemanticGraphService
        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(409, "confirmed=true is required to launch language servers")
        try:
            service = LSPSemanticGraphService(cache_root=self.output_root_provider() / "coding" / "semantic-index")
            if data.get("language"):
                result = await asyncio.to_thread(
                    service.build, data.get("repo_path", ""), language=data["language"],
                    command=data.get("command") or None, files=data.get("files") or None,
                    max_symbols=data.get("max_symbols", 500), include_calls=bool(data.get("include_calls", True)),
                )
            else:
                result = await asyncio.to_thread(
                    service.build_available, data.get("repo_path", ""),
                    files=data.get("files") or None,
                    max_languages=data.get("max_languages", 3),
                    max_files=data.get("max_files", 40),
                    max_symbols=data.get("max_symbols", 300),
                    include_calls=bool(data.get("include_calls", True)),
                )
            return JSONResponse(result)
        except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
            raise HTTPException(400, str(exc))


    async def api_coding_multilanguage_benchmark(self, request: Request):
        from services.coding_multilanguage_benchmark import CodingMultilanguageBenchmark
        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(409, "confirmed=true is required to run compiler benchmark cases")
        output = self.output_root_provider() / "coding-benchmark" / "multilanguage-latest.json" if data.get("persist", True) else None
        return JSONResponse(await asyncio.to_thread(CodingMultilanguageBenchmark().run, output))


    async def api_coding_oss_corpus_benchmark(self, request: Request):
        from services.coding_oss_corpus_benchmark import CodingOSSCorpusBenchmark
        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(409, "confirmed=true is required to mutate and execute corpus checkouts")
        manifest_path = self.security_policy_provider().resolve_path(str(data.get("manifest_path") or "")) if self.security_policy_provider() else Path(str(data.get("manifest_path") or "")).expanduser().resolve()
        corpus_root = self.security_policy_provider().resolve_path(str(data.get("corpus_root") or "")) if self.security_policy_provider() else Path(str(data.get("corpus_root") or "")).expanduser().resolve()
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            result = await asyncio.to_thread(
                CodingOSSCorpusBenchmark().evaluate, corpus_root, manifest,
                bootstrap_samples=int(data.get("bootstrap_samples") or 2000),
            )
            if data.get("persist", True):
                target = self.output_root_provider() / "coding-benchmark" / "oss-corpus-latest.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                result["report_path"] = str(target)
            return JSONResponse(result)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(400, str(exc))


    async def api_coding_outcome_benchmark(self, request: Request):
        from services.coding_quality_service import CodingOutcomeBenchmark

        data = await request.json()
        result = CodingOutcomeBenchmark().evaluate(
            data.get("cases") or [],
            minimum_cases=data.get("minimum_cases", 30),
            bootstrap_samples=data.get("bootstrap_samples", 1000),
        )
        if data.get("persist") is True:
            if data.get("confirmed") is not True:
                raise HTTPException(
                    409, "confirmed=true is required to persist benchmark evidence"
                )
            target = self.output_root_provider() / "coding-benchmark" / "latest.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            result["persisted_report"] = str(target)
        return JSONResponse(result)


    async def api_coding_review_gate(self, request: Request):
        from services.coding_quality_service import CodingReviewGate

        data = await request.json()
        verification_key = os.environ.get("CLAWOS_REVIEW_SIGNING_KEY", "")
        if not verification_key:
            raise HTTPException(
                503,
                "CLAWOS_REVIEW_SIGNING_KEY is required for trusted review evidence",
            )
        return JSONResponse(CodingReviewGate.evaluate(
            data.get("changed_paths") or [],
            data.get("ci_runs") or [],
            data.get("reviews") or [],
            verification_key=verification_key,
        ))


    async def api_coding_worktree_create(self, request: Request):
        from services.coding_workspace_service import CodingWorkspaceService

        data = await request.json()
        try:
            result = await asyncio.to_thread(
                CodingWorkspaceService().create,
                data.get("repo_path", ""),
                data.get("workspace_path", ""),
                data.get("branch", ""),
                base_ref=data.get("base_ref", "HEAD"),
                confirmed=bool(data.get("confirmed")),
            )
        except (ValueError, PermissionError, RuntimeError) as exc:
            raise HTTPException(409 if isinstance(exc, PermissionError) else 400, str(exc))
        return JSONResponse(result)


    async def api_coding_worktree_status(self, repo_path: str):
        from services.coding_workspace_service import CodingWorkspaceService

        try:
            return JSONResponse(CodingWorkspaceService().status(repo_path))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))


    async def api_coding_worktree_merge_plan(self, request: Request):
        from services.coding_workspace_service import CodingWorkspaceService

        data = await request.json()
        try:
            return JSONResponse(CodingWorkspaceService().merge_plan(
                data.get("repo_path", ""),
                data.get("branch", ""),
                base_ref=data.get("base_ref", "HEAD"),
            ))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))


    async def api_coding_worktree_remove(self, request: Request):
        from services.coding_workspace_service import CodingWorkspaceService

        data = await request.json()
        try:
            result = await asyncio.to_thread(
                CodingWorkspaceService().remove,
                data.get("repo_path", ""),
                data.get("workspace_path", ""),
                confirmed=data.get("confirmed") is True,
            )
        except (ValueError, PermissionError, RuntimeError) as exc:
            raise HTTPException(
                409 if isinstance(exc, PermissionError) else 400, str(exc)
            )
        return JSONResponse(result)


    async def api_coding_workspace_commit(self, request: Request):
        from services.coding_workspace_service import CodingWorkspaceService

        data = await request.json()
        try:
            result = await asyncio.to_thread(
                CodingWorkspaceService().commit,
                data.get("workspace_path", ""),
                data.get("paths") or [],
                data.get("message", ""),
                confirmed=bool(data.get("confirmed")),
                author=data.get("author", "coding-agent"),
            )
        except (ValueError, PermissionError, RuntimeError) as exc:
            raise HTTPException(409 if isinstance(exc, PermissionError) else 400, str(exc))
        return JSONResponse(result)
