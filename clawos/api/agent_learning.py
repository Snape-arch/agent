"""Agent learning HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
import hashlib
import json


class AgentLearningAPI:
    def __init__(self, *,
        output_root_provider: Callable[[], Any],
        memory_store_provider: Callable[[], Any],
    ):
        self.output_root_provider = output_root_provider
        self.memory_store_provider = memory_store_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/agent-learning/trajectories', self.api_agent_learning_trajectories, methods=['GET'])
        self.router.add_api_route('/api/agent-learning/trajectories/{trajectory_id}', self.api_agent_learning_trajectory, methods=['GET'])
        self.router.add_api_route('/api/agent-learning/dataset', self.api_agent_learning_dataset, methods=['GET'])
        self.router.add_api_route('/api/agent-learning/preferences', self.api_agent_learning_preference, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/feedback', self.api_agent_learning_feedback, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/data-quality', self.api_agent_learning_data_quality, methods=['GET'])
        self.router.add_api_route('/api/agent-learning/reward-calibrations', self.api_agent_learning_reward_calibrations, methods=['GET'])
        self.router.add_api_route('/api/agent-learning/reward-calibrations/train', self.api_agent_learning_reward_calibration_train, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/reward-calibrations/{calibration_id}/evaluate', self.api_agent_learning_reward_calibration_evaluate, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/reward-calibrations/{calibration_id}/activate', self.api_agent_learning_reward_calibration_activate, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/preference-ranker/readiness', self.api_agent_learning_preference_ranker_readiness, methods=['GET'])
        self.router.add_api_route('/api/agent-learning/preference-ranker/models', self.api_agent_learning_preference_ranker_models, methods=['GET'])
        self.router.add_api_route('/api/agent-learning/preference-ranker/train', self.api_agent_learning_preference_ranker_train, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/preference-ranker/models/{model_id}/evaluate', self.api_agent_learning_preference_ranker_evaluate, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/preference-ranker/models/{model_id}/activate', self.api_agent_learning_preference_ranker_activate, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/preference-ranker/rank', self.api_agent_learning_preference_ranker_rank, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/advanced-readiness', self.api_agent_learning_advanced_readiness, methods=['GET'])
        self.router.add_api_route('/api/agent-learning/ope/evaluate', self.api_agent_learning_ope_evaluate, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/trajectory-ranker/train', self.api_agent_learning_trajectory_ranker_train, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/offline-policy/sandbox', self.api_agent_learning_offline_policy_sandbox, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/artifacts', self.api_agent_learning_artifacts, methods=['GET'])
        self.router.add_api_route('/api/agent-learning/artifacts/{artifact_id}/transition', self.api_agent_learning_artifact_transition, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/models', self.api_agent_learning_models, methods=['GET'])
        self.router.add_api_route('/api/agent-learning/models/train', self.api_agent_learning_train, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/models/{model_id}/evaluate', self.api_agent_learning_evaluate, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/models/{model_id}/activate', self.api_agent_learning_activate, methods=['POST'])
        self.router.add_api_route('/api/agent-learning/models/{model_id}/rollback', self.api_agent_learning_rollback, methods=['POST'])

    async def api_agent_learning_trajectories(self,
        status: str = "", scenario: str = "", limit: int = 100,
    ):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        rows = self.memory_store_provider().list_agent_trajectories(
            status=status, scenario=scenario, limit=limit
        )
        return JSONResponse({"trajectories": rows, "count": len(rows)})


    async def api_agent_learning_trajectory(self, trajectory_id: int):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        item = self.memory_store_provider().get_agent_trajectory(trajectory_id=trajectory_id)
        if not item:
            raise HTTPException(404, "trajectory not found")
        return JSONResponse({"trajectory": item})


    async def api_agent_learning_dataset(self, group_name: str = "", limit: int = 5000):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.trajectory import TrajectoryLearningService

        dataset = TrajectoryLearningService(self.memory_store_provider()).export_dataset(
            group_name=group_name, limit=limit
        )
        return JSONResponse(dataset)


    async def api_agent_learning_preference(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.trajectory import TrajectoryLearningService

        data = await request.json()
        try:
            item = TrajectoryLearningService(self.memory_store_provider()).record_preference(
                task_context=data.get("task_context") or {},
                chosen=data.get("chosen") or {},
                rejected=data.get("rejected") or {},
                owner_id=data.get("owner_id", "default"),
                chosen_trajectory_id=data.get("chosen_trajectory_id"),
                rejected_trajectory_id=data.get("rejected_trajectory_id"),
                source=data.get("source", "explicit_user"),
                confidence=data.get("confidence", 1.0),
                metadata=data.get("metadata") or {},
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"preference": item})


    async def api_agent_learning_feedback(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.feedback import FeedbackLearningService

        data = await request.json()
        try:
            result = FeedbackLearningService(self.memory_store_provider()).record(
                task_id=int(data.get("task_id") or 0),
                signal_type=data.get("signal_type", ""),
                value=data.get("value"),
                owner_id=data.get("owner_id", "default"),
                reason_category=data.get("reason_category", ""),
                correction=data.get("correction") or {},
                metadata=data.get("metadata") or {},
                idempotency_key=str(
                    data.get("idempotency_key")
                    or request.headers.get("Idempotency-Key", "")
                    or ""
                ),
            )
            if bool(data.get("quality_consent")):
                from services.answer_quality_service import AnswerQualityService

                detail = self.memory_store_provider().get_task(int(data.get("task_id") or 0))
                task = detail.get("task") or {}
                answer = str(data.get("quality_answer") or "").strip()
                correction = data.get("correction") if isinstance(data.get("correction"), dict) else {}
                if answer:
                    quality_feedback = AnswerQualityService(self.memory_store_provider()).record({
                        "query": str(task.get("title") or ""), "answer": answer,
                        "expected_answer": str(correction.get("expected_answer") or ""),
                        "evidence": data.get("quality_evidence") or [],
                        "must_refuse": bool(data.get("must_refuse")), "origin": "consented_user",
                        "consented": True, "dataset_split": "production", "task_id": str(task.get("id") or ""),
                        "owner_id": str(data.get("owner_id") or "default"),
                        "workspace_id": str((task.get("metadata") or {}).get("workspace_id") or "default"),
                        "metadata": {"agent_feedback_id": (result.get("feedback") or {}).get("id"),
                                     "signal_type": data.get("signal_type"), "value": data.get("value")},
                    })
                    result["answer_quality_feedback"] = {
                        "recorded": True, "id": quality_feedback["id"],
                        "validation": quality_feedback["validation"],
                    }
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def api_agent_learning_data_quality(self):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.feedback import FeedbackLearningService

        return JSONResponse(FeedbackLearningService(self.memory_store_provider()).quality_report())


    async def api_agent_learning_reward_calibrations(self, limit: int = 100):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        rows = self.memory_store_provider().list_reward_calibrations(limit=limit)
        return JSONResponse({"calibrations": rows, "count": len(rows)})


    async def api_agent_learning_reward_calibration_train(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.calibration import RewardCalibrator

        data = await request.json()
        try:
            calibration = RewardCalibrator(self.memory_store_provider()).train(
                min_trajectories=data.get("min_trajectories", 50),
                min_explicit_feedback=data.get("min_explicit_feedback", 20),
                min_arm_exposure=data.get("min_arm_exposure", 10),
                trained_by=data.get("actor_id", "system"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"calibration": calibration})


    async def api_agent_learning_reward_calibration_evaluate(self, calibration_id: int):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.calibration import RewardCalibrator

        try:
            calibration = RewardCalibrator(self.memory_store_provider()).evaluate(calibration_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"calibration": calibration})


    async def api_agent_learning_reward_calibration_activate(self,
        calibration_id: int, request: Request,
    ):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.calibration import RewardCalibrator

        data = await request.json()
        try:
            calibration = RewardCalibrator(self.memory_store_provider()).activate(
                calibration_id, confirmed=bool(data.get("confirmed"))
            )
        except ValueError as exc:
            status_code = 409 if "confirmed=true" in str(exc) else 400
            raise HTTPException(status_code, str(exc))
        return JSONResponse({"calibration": calibration})


    async def api_agent_learning_preference_ranker_readiness(self):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.ranker import PreferenceRanker

        return JSONResponse(PreferenceRanker.readiness(self.memory_store_provider()))


    async def api_agent_learning_preference_ranker_models(self, limit: int = 100):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        rows = self.memory_store_provider().list_preference_ranker_models(limit=limit)
        return JSONResponse({"models": rows, "count": len(rows)})


    async def api_agent_learning_preference_ranker_train(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.ranker import PreferenceRanker

        data = await request.json()
        try:
            model = PreferenceRanker(
                self.memory_store_provider(),
                feature_dim=data.get("feature_dim", 128),
                epochs=data.get("epochs", 80),
            ).train(
                min_pairs=data.get("min_pairs", 100),
                min_per_scenario=data.get("min_per_scenario", 20),
                trained_by=data.get("actor_id", "system"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"model": model})


    async def api_agent_learning_preference_ranker_evaluate(self, model_id: int):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.ranker import PreferenceRanker

        try:
            model = PreferenceRanker(self.memory_store_provider()).evaluate(model_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"model": model})


    async def api_agent_learning_preference_ranker_activate(self,
        model_id: int, request: Request,
    ):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.ranker import PreferenceRanker

        data = await request.json()
        try:
            model = PreferenceRanker(self.memory_store_provider()).activate(
                model_id, confirmed=bool(data.get("confirmed"))
            )
        except ValueError as exc:
            status_code = 409 if "confirmed=true" in str(exc) else 400
            raise HTTPException(status_code, str(exc))
        return JSONResponse({"model": model})


    async def api_agent_learning_preference_ranker_rank(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.ranker import PreferenceRanker

        data = await request.json()
        try:
            result = PreferenceRanker(self.memory_store_provider()).rank(
                data.get("task_context") or {},
                data.get("candidates") or [],
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def api_agent_learning_advanced_readiness(self):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.readiness import AdvancedLearningReadiness

        return JSONResponse(AdvancedLearningReadiness(self.memory_store_provider()).report())


    async def api_agent_learning_ope_evaluate(self, request: Request):
        from services.advanced_policy_learning import RobustOffPolicyEvaluator
        from services.evidence_registry import LearningArtifactRegistry

        data = await request.json()
        probabilities = {
            str(key): float(value)
            for key, value in (data.get("candidate_probabilities") or {}).items()
        }
        records = data.get("records") or []
        if not probabilities and not any(
            item.get("candidate_probabilities") for item in records
        ):
            raise HTTPException(
                400, "global or per-record candidate_probabilities are required"
            )
        try:
            result = RobustOffPolicyEvaluator().evaluate(
                records,
                lambda record, candidates: {
                    arm: float(
                        (record.get("candidate_probabilities") or probabilities).get(
                            arm, 0.0
                        )
                    )
                    for arm in candidates
                },
                bootstrap_samples=data.get("bootstrap_samples", 400),
                minimum_ess=data.get("minimum_ess", 20),
                minimum_overlap=data.get("minimum_overlap", 0.20),
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc))
        if data.get("persist") is True:
            try:
                result["artifact"] = LearningArtifactRegistry(
                    self.output_root_provider() / "evidence" / "learning_artifacts.json"
                ).create(
                    "robust_ope",
                    result,
                    source_data_digest=hashlib.sha256(
                        json.dumps(records, sort_keys=True).encode("utf-8")
                    ).hexdigest(),
                    confirmed=data.get("confirmed") is True,
                )
            except (PermissionError, ValueError) as exc:
                raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def api_agent_learning_trajectory_ranker_train(self, request: Request):
        from services.advanced_policy_learning import TrajectoryPreferenceRanker
        from services.evidence_registry import LearningArtifactRegistry

        data = await request.json()
        pairs = data.get("pairs") or []
        result = TrajectoryPreferenceRanker().train(
            pairs,
            epochs=data.get("epochs", 200),
            learning_rate=data.get("learning_rate", 0.05),
            minimum_pairs=data.get("minimum_pairs", 100),
        )
        if data.get("persist") is True and result.get("status") != "blocked":
            try:
                result["artifact"] = LearningArtifactRegistry(
                    self.output_root_provider() / "evidence" / "learning_artifacts.json"
                ).create(
                    "trajectory_ranker",
                    result,
                    source_data_digest=hashlib.sha256(
                        json.dumps(pairs, sort_keys=True).encode("utf-8")
                    ).hexdigest(),
                    confirmed=data.get("confirmed") is True,
                )
            except (PermissionError, ValueError) as exc:
                raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def api_agent_learning_offline_policy_sandbox(self, request: Request):
        from services.advanced_policy_learning import OfflinePolicySandbox
        from services.evidence_registry import LearningArtifactRegistry

        data = await request.json()
        trajectories = data.get("trajectories") or []
        result = OfflinePolicySandbox.advantage_weights(
            trajectories,
            temperature=data.get("temperature", 0.5),
            maximum_weight=data.get("maximum_weight", 20),
            minimum_trajectories=data.get("minimum_trajectories", 2000),
            minimum_steps=data.get("minimum_steps", 10000),
        )
        if data.get("persist") is True and result.get("status") != "blocked":
            try:
                result["artifact"] = LearningArtifactRegistry(
                    self.output_root_provider() / "evidence" / "learning_artifacts.json"
                ).create(
                    "offline_policy_dataset",
                    result,
                    source_data_digest=hashlib.sha256(
                        json.dumps(trajectories, sort_keys=True).encode("utf-8")
                    ).hexdigest(),
                    confirmed=data.get("confirmed") is True,
                )
            except (PermissionError, ValueError) as exc:
                raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def api_agent_learning_artifacts(self, kind: str = ""):
        from services.evidence_registry import LearningArtifactRegistry
        return JSONResponse({
            "artifacts": LearningArtifactRegistry(
                self.output_root_provider() / "evidence" / "learning_artifacts.json"
            ).list(kind)
        })


    async def api_agent_learning_artifact_transition(self,
        artifact_id: str, request: Request
    ):
        from services.evidence_registry import LearningArtifactRegistry
        data = await request.json()
        try:
            result = LearningArtifactRegistry(
                self.output_root_provider() / "evidence" / "learning_artifacts.json"
            ).transition(
                artifact_id,
                str(data.get("state") or ""),
                evidence=data.get("evidence") or {},
                confirmed=data.get("confirmed") is True,
            )
        except (PermissionError, ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def api_agent_learning_models(self, group_name: str = "", limit: int = 100):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        rows = self.memory_store_provider().list_agent_policy_models(
            group_name=group_name, limit=limit
        )
        return JSONResponse({"models": rows, "count": len(rows)})


    async def api_agent_learning_train(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.policy import AgentSkillPolicyNetwork

        data = await request.json()
        group_name = str(data.get("group_name") or "").strip()
        if not group_name:
            raise HTTPException(400, "group_name is required")
        try:
            model = AgentSkillPolicyNetwork(
                self.memory_store_provider(),
                feature_dim=data.get("feature_dim", 128),
                epochs=data.get("epochs", 60),
            ).train(
                group_name,
                min_examples=data.get("min_examples", 30),
                trained_by=data.get("actor_id", "system"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"model": model})


    async def api_agent_learning_evaluate(self, model_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.policy import TrajectoryCritic

        data = await request.json()
        try:
            model = TrajectoryCritic(self.memory_store_provider()).evaluate(
                model_id,
                min_samples=data.get("min_samples", 30),
                regression_tolerance=data.get("regression_tolerance", 0.02),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"model": model})


    async def api_agent_learning_activate(self, model_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.policy import TrajectoryCritic

        data = await request.json()
        try:
            model = TrajectoryCritic(self.memory_store_provider()).activate(
                model_id, confirmed=bool(data.get("confirmed"))
            )
        except ValueError as exc:
            status_code = 409 if "confirmed=true" in str(exc) else 400
            raise HTTPException(status_code, str(exc))
        return JSONResponse({"model": model})


    async def api_agent_learning_rollback(self, model_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.learning.policy import TrajectoryCritic

        data = await request.json()
        try:
            result = TrajectoryCritic(self.memory_store_provider()).rollback(
                model_id, confirmed=bool(data.get("confirmed"))
            )
        except ValueError as exc:
            status_code = 409 if "confirmed=true" in str(exc) else 400
            raise HTTPException(status_code, str(exc))
        return JSONResponse(result)
