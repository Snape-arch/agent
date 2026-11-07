"""Self evolution HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
import asyncio


class SelfEvolutionAPI:
    def __init__(self, *,
        _collaboration: Callable[..., Any],
        _evolution_json: Callable[..., Any],
        enqueue_runtime_task: Callable[..., Any],
        memory_store_provider: Callable[[], Any],
        routing_provider_provider: Callable[[], Any],
        http_client_provider: Callable[[], Any],
    ):
        self._collaboration = _collaboration
        self._evolution_json = _evolution_json
        self.enqueue_runtime_task = enqueue_runtime_task
        self.memory_store_provider = memory_store_provider
        self.routing_provider_provider = routing_provider_provider
        self.http_client_provider = http_client_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/self-evolution/runs', self.api_self_evolution_runs, methods=['GET'])
        self.router.add_api_route('/api/self-evolution/board', self.api_self_evolution_board, methods=['GET'])
        self.router.add_api_route('/api/self-evolution/experiments', self.api_evolution_experiments, methods=['GET'])
        self.router.add_api_route('/api/self-evolution/experiments/{experiment_id}', self.api_evolution_experiment_detail, methods=['GET'])
        self.router.add_api_route('/api/self-evolution/experiments', self.api_evolution_experiment_freeze, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/experiments/{experiment_id}/replay', self.api_evolution_experiment_replay, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/experiments/{experiment_id}/nominate', self.api_evolution_experiment_nominate, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/experiments/{experiment_id}/control', self.api_evolution_experiment_control, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/experiments/{experiment_id}/review-outputs', self.api_evolution_review_outputs, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/experiments/{experiment_id}/reviews', self.api_evolution_review_submit, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/experiments/{experiment_id}/review/{kind}', self.api_evolution_review_get, methods=['GET'])
        self.router.add_api_route('/api/self-evolution/experiments/{experiment_id}/model-capture', self.api_evolution_capture_plan, methods=['GET'])
        self.router.add_api_route('/api/self-evolution/experiments/{experiment_id}/model-capture', self.api_evolution_capture_execute, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/experiments/{experiment_id}/model-capture/pause', self.api_evolution_capture_pause, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/experiments/{experiment_id}/model-receipts', self.api_evolution_capture_receipts, methods=['GET'])
        self.router.add_api_route('/api/self-evolution/review-users', self.api_evolution_review_users, methods=['GET'])
        self.router.add_api_route('/api/self-evolution/experiments/{experiment_id}/review-grants', self.api_evolution_review_grant, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/runs', self.api_self_evolution_create_run, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/candidates', self.api_self_evolution_candidate, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/runs/{run_id}/evaluate', self.api_self_evolution_evaluate, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/runs/{run_id}/publish', self.api_self_evolution_publish, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/runs/{run_id}/quality-signal', self.api_self_evolution_quality_signal, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/runs/{run_id}/quality-snapshot', self.api_self_evolution_quality_snapshot, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/runs/{run_id}/canary', self.api_self_evolution_canary, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/runs/{run_id}/activate', self.api_self_evolution_activate, methods=['POST'])
        self.router.add_api_route('/api/self-evolution/runs/{run_id}/rollback', self.api_self_evolution_rollback, methods=['POST'])

    async def api_self_evolution_runs(self, status: str = "", limit: int = 100):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        rows = self.memory_store_provider().list_self_evolution_runs(status=status, limit=limit)
        return JSONResponse({"runs": rows, "count": len(rows)})


    async def api_self_evolution_board(self, limit: int = 50):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from reflection.self_evolution import SelfEvolutionManager
        manager = SelfEvolutionManager(self.memory_store_provider())
        runs = self.memory_store_provider().list_self_evolution_runs(limit=limit)
        for run in runs:
            run['paired_quality_evidence'] = manager.quality_evidence(run['id'])
            current = self.memory_store_provider().get_runtime_policy(run['target_type'], run['target_key'])
            run['current_policy_version'] = int(current['version']) if current else 0
            run['stale_baseline'] = (run.get('status') in {'candidate','validated','shadow','canary'}
                and run.get('baseline_policy_version', -1) != run['current_policy_version'])
            run['owns_active_policy'] = bool(current and current.get('active') and run.get('status')=='published'
                and run['current_policy_version']==(run.get('rollback_payload') or {}).get('policy_version')
                and current.get('payload')==run.get('candidate_payload'))
            run['effective_stage'] = ('superseded' if run.get('status')=='published' and not run['owns_active_policy']
                                      else run.get('release_stage') or run.get('status') or 'candidate')
        snapshot = self.memory_store_provider().runtime_quality_snapshot()
        stage_counts: dict[str, int] = {}
        for run in runs:
            stage = str(run['effective_stage'])
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        blocked = [
            run for run in runs
            if run.get("status") == "rejected"
            or not (run.get("gate_result") or {}).get("passed", True)
        ]
        active = [run for run in runs if run['owns_active_policy']]
        score = 100
        if not runs:
            score -= 25
        if blocked:
            score -= min(30, len(blocked) * 5)
        if snapshot.get("cancel_rate", 0) > 0.15 or snapshot.get("long_task_failure_rate", 0) > 0.10:
            score -= 20
        score = max(0, min(100, score))
        return JSONResponse({
            "runs": runs,
            "stage_counts": stage_counts,
            "quality_snapshot": snapshot,
            "active_count": len(active),
            "blocked_count": len(blocked),
            "enterprise_score": score,
            "score_scope": "legacy_heuristic_not_acceptance",
            "stale_count": sum(bool(run['stale_baseline']) for run in runs),
            "enterprise_ready": False,
        })


    async def api_evolution_experiments(self):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        experiments = self.memory_store_provider().list_evolution_experiments(limit=20)
        from services.evolution_experiments import source_fingerprints, loaded_executor_digest
        current_sources, current_executor = source_fingerprints(), loaded_executor_digest()
        summaries = []
        for experiment in experiments:
            definition, report = experiment['definition'], experiment['report']
            policy = self.memory_store_provider().get_runtime_policy(definition['target_type'], definition['target_key'])
            stale = (definition.get('source_sha256') != current_sources
                     or definition.get('loaded_executor_digest') != current_executor
                     or definition.get('baseline_policy_version') != (int(policy['version']) if policy else 0))
            summaries.append({key: experiment[key] for key in ('id','status','definition_digest','created_at','job')})
            summaries[-1].update(target_type=definition['target_type'], target_key=definition['target_key'],
                                 stale_evidence=stale,
                                 case_count=len(definition['cases']), candidate_count=len(definition['candidates']),
                                 report={key: report.get(key) for key in ('selected_candidate_id','search_groups','holdout_groups',
                                         'eligible_for_regression_queue','gates','baseline','candidate','paired_gate','stratified_gate','error','message')})
            if stale:
                summaries[-1]['report']['eligible_for_regression_queue'] = False
        return JSONResponse({'experiments': summaries, 'runtime_promotion_evidence': False})


    async def api_evolution_experiment_detail(self, experiment_id: int):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        experiment = self.memory_store_provider().get_evolution_experiment(experiment_id)
        if not experiment:
            raise HTTPException(404, "experiment not found")
        return JSONResponse({'experiment': experiment})


    async def api_evolution_experiment_freeze(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.evolution_experiments import EvolutionExperimentService
        if len(await request.body()) > 8 * 1024 * 1024:
            raise HTTPException(413, "experiment exceeds 8MiB")
        data = await self._evolution_json(request)
        try:
            experiment = await asyncio.to_thread(EvolutionExperimentService(self.memory_store_provider()).freeze,
                target_type=data.get('target_type',''), target_key=data.get('target_key',''),
                baseline_payload=data.get('baseline_payload',{}), cases=data.get('cases'),
                documents=data.get('documents'), reflections=data.get('reflections'), created_by=data.get('actor_id','console'))
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({'experiment': experiment})


    async def api_evolution_experiment_replay(self, experiment_id: int):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.evolution_experiments import EvolutionExperimentService
        try:
            experiment = await asyncio.to_thread(EvolutionExperimentService(self.memory_store_provider()).replay, experiment_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return JSONResponse({'experiment': experiment})


    async def api_evolution_experiment_nominate(self, experiment_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.evolution_experiments import EvolutionExperimentService
        data = await self._evolution_json(request)
        try:
            run = EvolutionExperimentService(self.memory_store_provider()).nominate(experiment_id, data.get('actor_id','console'))
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return JSONResponse({'run': run, 'next_step': 'execute regression, then collect fresh shadow and canary evidence'})


    async def api_evolution_experiment_control(self, experiment_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, 'MemoryOS not initialized')
        from services.evolution_jobs import EvolutionJobStore
        value = await self._evolution_json(request)
        try:
            result = await asyncio.to_thread(EvolutionJobStore(self.memory_store_provider()).control, experiment_id, value.get('action'))
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return JSONResponse({'experiment': result})


    async def api_evolution_review_outputs(self, experiment_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, 'MemoryOS not initialized')
        from services.evolution_review import EvolutionReviewService
        value = await self._evolution_json(request)
        try:
            packet = await asyncio.to_thread(EvolutionReviewService(self.memory_store_provider()).freeze_outputs,
                                            experiment_id, value, value.get('actor_id','console'))
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({'packet': packet})


    async def api_evolution_review_submit(self, experiment_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, 'MemoryOS not initialized')
        from services.evolution_review import EvolutionReviewService
        value = await self._evolution_json(request)
        try:
            summary = await asyncio.to_thread(EvolutionReviewService(self.memory_store_provider()).submit, experiment_id, value)
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({'summary': summary})


    async def api_evolution_review_get(self, experiment_id: int, kind: str):
        if not self.memory_store_provider():
            raise HTTPException(503, 'MemoryOS not initialized')
        from services.evolution_review import EvolutionReviewService
        service = EvolutionReviewService(self.memory_store_provider())
        methods = {'packet': service.packet, 'summary': service.summary, 'evidence': service.evidence}
        if kind not in methods:
            raise HTTPException(404, 'review resource not found')
        try:
            result = await asyncio.to_thread(methods[kind], experiment_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        return JSONResponse({kind: result})


    async def api_evolution_capture_plan(self, experiment_id:int):
        from services.evolution_capture import EvolutionModelCapture
        if not self.memory_store_provider(): raise HTTPException(503,'MemoryOS not initialized')
        service=EvolutionModelCapture(self.memory_store_provider())
        try: return {'plan':service.plan(experiment_id),'capture':service.state(experiment_id)}
        except ValueError as exc: raise HTTPException(400,str(exc))


    async def api_evolution_capture_execute(self, experiment_id:int,request:Request):
        from services.evolution_capture import EvolutionModelCapture
        if not self.memory_store_provider(): raise HTTPException(503,'MemoryOS not initialized')
        data=await self._evolution_json(request)
        try:
            return await EvolutionModelCapture(self.memory_store_provider()).capture(experiment_id,self.routing_provider_provider(),http_client=self.http_client_provider(),
                max_calls=data.get('max_calls',80),max_tokens=data.get('max_tokens',256),timeout=data.get('timeout',30))
        except (ValueError,asyncio.TimeoutError) as exc:
            raise HTTPException(409,'capture not completed: '+str(exc)[:200])


    async def api_evolution_capture_pause(self, experiment_id:int):
        from services.evolution_capture import EvolutionModelCapture
        if not self.memory_store_provider(): raise HTTPException(503,'MemoryOS not initialized')
        try: return {'capture':EvolutionModelCapture(self.memory_store_provider()).control(experiment_id)}
        except ValueError as exc: raise HTTPException(409,str(exc))


    async def api_evolution_capture_receipts(self, experiment_id:int):
        from services.evolution_capture import EvolutionModelCapture
        if not self.memory_store_provider(): raise HTTPException(503,'MemoryOS not initialized')
        try: return {'receipts':EvolutionModelCapture(self.memory_store_provider()).receipts(experiment_id)}
        except ValueError as exc: raise HTTPException(409,str(exc))


    async def api_evolution_review_users(self):
        if not self.memory_store_provider(): raise HTTPException(503,'MemoryOS not initialized')
        self._collaboration()
        with self.memory_store_provider()._conn() as conn:
            users=[dict(row) for row in conn.execute("SELECT id,name FROM collaboration_users WHERE id!='local-user' ORDER BY name LIMIT 100")]
        return {'users':users,'boundary':'server-issued session users; not real-person or professional identity verification'}


    async def api_evolution_review_grant(self, experiment_id:int,request:Request):
        if not self.memory_store_provider(): raise HTTPException(503,'MemoryOS not initialized')
        from services.evolution_review import EvolutionReviewService
        data=await self._evolution_json(request); self._collaboration()
        try: return {'grant':EvolutionReviewService(self.memory_store_provider()).grant(experiment_id,data.get('user_id'),data.get('role'))}
        except (ValueError,TypeError) as exc: raise HTTPException(400,str(exc))


    async def api_self_evolution_create_run(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from reflection.self_evolution import SelfEvolutionManager
        data = await request.json()
        try:
            manager = SelfEvolutionManager(self.memory_store_provider())
            if data.get("mine_reflections"):
                run = manager.propose_from_recent_reflections(
                    target_type=data.get("target_type", ""),
                    target_key=data.get("target_key", ""),
                    baseline_payload=data.get("baseline_payload", {}),
                    limit=data.get("reflection_limit", 50),
                    created_by=data.get("actor_id", "reflection-miner"),
                )
            else:
                run = manager.create_run(
                    target_type=data.get("target_type", ""),
                    target_key=data.get("target_key", ""),
                    baseline_payload=data.get("baseline_payload", {}),
                    candidate_payload=data.get("candidate_payload", {}),
                    benchmarks=data.get("benchmarks", {}),
                    title=data.get("title", ""),
                    conclusion=data.get("conclusion", ""),
                    created_by=data.get("actor_id", "system"),
                )
            queued = bool(data.get("auto_queue", True))
            task = {}
            if queued:
                task = self.enqueue_runtime_task(
                    "self-evolution",
                    f"Self-evolution benchmark run {run['id']}",
                    source="self_evolution",
                    metadata={
                        "worker_action": "self_evolution_benchmark",
                        "run_id": run["id"],
                        "idempotency_key": data.get("idempotency_key", ""),
                    },
                )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"run": run, "queued": queued, "task": task})


    async def api_self_evolution_candidate(self, request: Request):
        from reflection.self_evolution import SelfEvolutionManager
        data = await request.json()
        try:
            if data.get("reflections"):
                candidate = SelfEvolutionManager.generate_candidate_from_failures(
                    data.get("target_type", ""),
                    data.get("baseline_payload", {}),
                    data.get("reflections") or [],
                    strategy=data.get("strategy", "evidence_clustered"),
                )
            else:
                candidate = SelfEvolutionManager.generate_candidate(
                    data.get("target_type", ""),
                    data.get("baseline_payload", {}),
                    strategy=data.get("strategy", "balanced"),
                )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        from services.evolution_experiments import candidate_pool
        try:
            pool = candidate_pool(data.get('target_type',''), data.get('baseline_payload',{}), data.get('reflections'))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"candidate_payload": candidate, "candidates": pool,
                             "selection_requires_replay": True, "verified_gain": False})


    async def api_self_evolution_evaluate(self, run_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from reflection.self_evolution import SelfEvolutionManager
        await request.json()
        try:
            run = await asyncio.to_thread(SelfEvolutionManager(self.memory_store_provider()).run_automatic_benchmarks, run_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"run": run})


    async def api_self_evolution_publish(self, run_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from reflection.self_evolution import SelfEvolutionManager
        data = await request.json()
        try:
            run = SelfEvolutionManager(self.memory_store_provider()).start_shadow(run_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"run": run})


    async def api_self_evolution_quality_signal(self, run_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from reflection.self_evolution import SelfEvolutionManager
        data = await request.json()
        try:
            run = SelfEvolutionManager(self.memory_store_provider()).record_quality_signal(
                run_id,
                data.get("signal_type", "quality"),
                data.get("value", 0),
                metadata=data.get("metadata", {}),
                created_by=data.get("actor_id", "system"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"run": run})


    async def api_self_evolution_quality_snapshot(self, run_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from reflection.self_evolution import SelfEvolutionManager
        data = await request.json()
        try:
            run = SelfEvolutionManager(self.memory_store_provider()).attach_runtime_quality_snapshot(
                run_id,
                created_by=data.get("actor_id", "system"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"run": run})


    async def api_self_evolution_canary(self, run_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from reflection.self_evolution import SelfEvolutionManager
        data = await request.json()
        try:
            run = SelfEvolutionManager(self.memory_store_provider()).promote_canary(
                run_id,
                traffic_percent=data.get("traffic_percent", 10),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"run": run})


    async def api_self_evolution_activate(self, run_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from reflection.self_evolution import SelfEvolutionManager
        data = await request.json()
        if not bool(data.get("confirmed")):
            raise HTTPException(409, "explicit confirmed=true is required for activation")
        try:
            run = SelfEvolutionManager(self.memory_store_provider()).activate(
                run_id,
                actor_id=data.get("actor_id", "system"),
                reason=data.get("reason", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"run": run})


    async def api_self_evolution_rollback(self, run_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        if data.get('mine_reflections') and self.memory_store_provider():
            data['reflections'] = [card for card in self.memory_store_provider().list_reflection_cards(limit=100)
                                   if card.get('outcome') in {'failure','partial'}]
        if data.get('confirmed') is not True:
            raise HTTPException(409, 'confirmed=true is required for rollback')
        from reflection.self_evolution import SelfEvolutionManager
        try:
            run = SelfEvolutionManager(self.memory_store_provider()).rollback(run_id, data.get('actor_id', 'user'), data.get('reason', ''))
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return JSONResponse({'run': run})
