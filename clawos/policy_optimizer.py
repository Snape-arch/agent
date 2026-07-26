"""Contextual multi-armed bandit for tool, agent, prompt, and workflow policies."""

from __future__ import annotations

import math
import random
from datetime import datetime


class PolicyOptimizer:
    """Persistent Contextual UCB with explicit reward evidence."""

    def __init__(self, store, random_seed=0, policy_network=None):
        self._store = store
        self._random = random.Random(random_seed)
        if policy_network is None:
            from agent_learning import AgentSkillPolicyNetwork

            policy_network = AgentSkillPolicyNetwork(store)
        self._policy_network = policy_network

    def register_group(self, name, arms, exploration_rate=0.1):
        group = self._store.upsert_policy_group(
            name,
            optimizer_type="hybrid_ucb_agent_skill_policy_v0",
            exploration_rate=exploration_rate,
        )
        registered = []
        for arm in arms:
            registered.append(self._store.upsert_policy_arm(
                name,
                arm["name"],
                arm.get("arm_type", "workflow"),
                payload=arm.get("payload", {}),
                contexts=arm.get("contexts", []),
                status=arm.get("status", "active"),
            ))
        return {"group": group, "arms": registered}

    def select(self, group_name, context=None, task_id=None, session_id=""):
        context = context or {}
        arms, group = self._store.list_policy_arms(group_name)
        if not group or not arms:
            raise ValueError("policy group has no active arms")
        eligible = [arm for arm in arms if self._context_matches(arm, context)]
        eligible = eligible or arms
        total_pulls = sum(int(arm["pull_count"]) for arm in eligible)
        exploration_rate = max(0.0, min(float(group["exploration_rate"]), 1.0))
        learned = self._policy_network.active_scores(
            group_name, context, eligible
        ) if self._policy_network else {"model": None, "scores": {}}
        network_scores = learned.get("scores") or {}
        exploit_scored = [
            (
                self._hybrid_score(
                    arm, total_pulls, network_scores.get(arm["name"])
                ),
                arm,
            )
            for arm in eligible
        ]
        exploit_score, exploit_arm = max(
            exploit_scored, key=lambda item: (item[0], -item[1]["id"])
        )
        explore = self._random.random() < exploration_rate
        if explore:
            selected = self._random.choice(eligible)
            score = next(
                item_score for item_score, arm in exploit_scored
                if int(arm["id"]) == int(selected["id"])
            )
        else:
            score, selected = exploit_score, exploit_arm
        behavior_propensity = (
            exploration_rate / max(len(eligible), 1)
            + (
                1.0 - exploration_rate
                if int(selected["id"]) == int(exploit_arm["id"])
                else 0.0
            )
        )
        enriched_context = {
            **context,
            "_agent_learning": {
                "model": learned.get("model"),
                "network_score": network_scores.get(selected["name"]),
                "behavior_propensity": round(behavior_propensity, 8),
                "eligible_arms": [arm["name"] for arm in eligible],
                "exploit_arm": exploit_arm["name"],
            },
        }
        selection = self._store.create_policy_selection(
            group["id"],
            selected["id"],
            enriched_context,
            1e12 if math.isinf(score) else score,
            exploration=explore,
            task_id=task_id,
            session_id=session_id,
        )
        if task_id:
            try:
                from agent_learning import TrajectoryLearningService

                TrajectoryLearningService(self._store).record_decision(
                    int(task_id),
                    state=enriched_context,
                    action_type=selected["arm_type"],
                    action_name=selected["name"],
                    action_payload=selected.get("payload") or {},
                    policy_selection_id=int(selection["id"]),
                    behavior_propensity=behavior_propensity,
                )
            except ValueError:
                # A caller may use a task identifier from another store.
                pass
        return selection

    def reward(
        self, selection_id, success, satisfaction=0.5,
        latency_ms=0, resource_cost=0, latency_budget_ms=1000,
        evidence=None,
    ):
        success = self._clamp(success)
        satisfaction = self._clamp(satisfaction)
        latency_cost = self._clamp(float(latency_ms or 0) / max(1.0, float(latency_budget_ms)))
        resource_cost = self._clamp(resource_cost)
        value = (
            0.4 * success
            + 0.3 * satisfaction
            - 0.2 * latency_cost
            - 0.1 * resource_cost
        )
        value = round(value, 6)
        selection = self._store.record_policy_reward(
            selection_id,
            success,
            satisfaction,
            latency_cost,
            resource_cost,
            value,
            evidence=evidence,
        )
        self._store.complete_agent_trajectory_selection(
            selection_id,
            value,
            reward_components={
                "success": success,
                "satisfaction": satisfaction,
                "latency_cost": latency_cost,
                "resource_cost": resource_cost,
            },
            observation=evidence or {},
        )
        return {"selection": selection, "reward": value}

    def reward_from_task(
        self,
        selection_id,
        task_id,
        satisfaction=0.5,
        resource_cost=None,
    ):
        """Derive reward from a terminal server-side task instead of caller claims."""

        selection = self._store.get_policy_selection(selection_id)
        detail = self._store.get_task(task_id)
        task = (detail or {}).get("task") or {}
        if not selection or not task:
            raise ValueError("policy selection or task not found")
        if selection.get("task_id") and int(selection["task_id"]) != int(task_id):
            raise ValueError("policy selection is bound to another task")
        status = str(task.get("status") or "")
        if status not in {"succeeded", "failed", "canceled", "cancelled"}:
            raise ValueError("task must be terminal before reward")
        latency_ms = self._task_latency_ms(task)
        metadata = task.get("metadata") or {}
        derived_resource = float(
            metadata.get("resource_cost")
            or metadata.get("token_cost_normalized")
            or 0
        )
        return self.reward(
            selection_id,
            success=1.0 if status == "succeeded" else 0.0,
            satisfaction=satisfaction,
            latency_ms=latency_ms,
            resource_cost=derived_resource if resource_cost is None else resource_cost,
            evidence={
                "source": "server_task",
                "task_id": int(task_id),
                "status": status,
                "policy_version": metadata.get("policy_version"),
            },
        )

    def stats(self, group_name):
        return self._store.policy_group_stats(group_name)

    def promote(self, group_name, target_type, target_key, min_pulls=5, actor_id="system"):
        stats = self.stats(group_name)
        if not stats:
            raise ValueError("policy group not found")
        required_pulls = max(5, int(min_pulls))
        eligible = [
            arm for arm in stats["arms"]
            if arm["status"] == "active" and int(arm["pull_count"]) >= required_pulls
        ]
        if not eligible:
            raise ValueError(
                f"no policy arm has the required {required_pulls} reward observations"
            )
        winner = max(
            eligible,
            key=lambda arm: (
                arm.get("confidence_lower_95", arm["average_reward"]),
                arm["average_reward"],
                arm["success_rate"],
                -arm["id"],
            ),
        )
        return self._store.promote_policy_arm(
            stats["group"]["id"],
            winner["id"],
            target_type,
            target_key,
            actor_id=actor_id,
        )

    def rollback(self, promotion_id, actor_id="system"):
        return self._store.rollback_policy_promotion(promotion_id, actor_id=actor_id)

    @staticmethod
    def _ucb_score(arm, total_pulls):
        pulls = int(arm["pull_count"])
        if pulls == 0:
            return float("inf")
        average = float(arm["reward_sum"]) / pulls
        bonus = math.sqrt(2.0 * math.log(max(2, total_pulls + 1)) / pulls)
        return average + bonus

    @classmethod
    def _hybrid_score(cls, arm, total_pulls, network_score=None):
        ucb = cls._ucb_score(arm, total_pulls)
        if math.isinf(ucb) or network_score is None:
            return ucb
        return ucb + 0.35 * float(network_score)

    @staticmethod
    def _context_matches(arm, context):
        tags = {str(tag).lower() for tag in arm.get("contexts", [])}
        if not tags:
            return True
        context_tags = {str(tag).lower() for tag in context.get("tags", [])}
        scenario = str(context.get("scenario", "")).lower()
        if scenario:
            context_tags.add(scenario)
        return bool(tags & context_tags)

    @staticmethod
    def _clamp(value):
        return max(0.0, min(float(value or 0), 1.0))

    @staticmethod
    def _task_latency_ms(task):
        try:
            started = datetime.fromisoformat(str(task.get("created_at", "")).replace("Z", "+00:00"))
            completed = datetime.fromisoformat(str(task.get("completed_at", "")).replace("Z", "+00:00"))
            return max(0.0, (completed - started).total_seconds() * 1000.0)
        except (TypeError, ValueError):
            return float((task.get("metadata") or {}).get("duration_ms") or 0)
