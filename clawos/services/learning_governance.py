"""Shared, fail-closed learning promotion thresholds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
from collections import defaultdict
import math
import random


@dataclass(frozen=True)
class LearningThresholds:
    shadow_samples: int = 30
    canary_samples: int = 30
    activation_samples: int = 30
    lightweight_router_samples: int = 30
    deep_router_trajectories: int = 500
    trajectory_rl_trajectories: int = 2000
    trajectory_rl_steps: int = 10_000
    preference_pairs: int = 100


THRESHOLDS = LearningThresholds()


def independent_evidence_ids(rows: Iterable[dict[str, Any]]) -> set[str]:
    """Return task/session/repository-bound evidence IDs.

    An aggregate snapshot or repeated observation without an independent
    identity deliberately contributes no promotion evidence.
    """

    identities: set[str] = set()
    for row in rows:
        metadata = dict(row.get("metadata") or {})
        evidence_id = str(metadata.get("evidence_id") or "").strip()
        task_id = str(metadata.get("task_id") or "").strip()
        session_id = str(metadata.get("session_id") or "").strip()
        repository_id = str(metadata.get("repository_id") or "").strip()
        identity = evidence_id or (
            f"task:{task_id}|session:{session_id}|repo:{repository_id}"
            if task_id and session_id
            else ""
        )
        if identity:
            identities.add(identity)
    return identities


QUALITY_DIRECTIONS = {
    "user_retry_rate": -1, "cancel_rate": -1, "long_task_failure_rate": -1,
    "retrieval_hit_rate": 1, "quality_score": 1, "citation_coverage": 1,
    "task_success_rate": 1,
}


def runtime_health_passed(rows):
    latest = {}
    for row in rows:  # Store supplies newest-first records.
        meta = row.get("metadata") or {}
        if meta.get("variant") == "control" or meta.get("source") in {"runtime_snapshot", "offline_replay", "policy_materialization"}:
            continue
        latest.setdefault(row.get("signal_type"), float(row.get("value") or 0))
    limits = {"user_retry_rate": .20, "cancel_rate": .15, "long_task_failure_rate": .10}
    return (all(latest.get(key, 0) <= limit for key, limit in limits.items())
            and latest.get("retrieval_hit_rate", 1) >= .80)


def paired_quality_report(rows, *, minimum=30, stage=None, tolerance=0.02, family_size=1):
    """Compare the same metric on the same independent task, never two marginals.

    Repeated identical observations add no support. Conflicting duplicates,
    mismatched frozen inputs and non-finite values fail closed. Offline replay
    and aggregate snapshots cannot be relabelled as live promotion evidence.
    Bootstrap resamples task clusters; each cluster has equal weight.
    """
    buckets = defaultdict(dict)
    rejected = defaultdict(int)
    bindings = {}
    for row in rows:
        meta = row.get("metadata") or {}
        if meta.get("source") in {"runtime_snapshot", "offline_replay", "policy_materialization"}:
            continue
        if stage and meta.get("observed_stage") != stage:
            continue
        metric = str(row.get("signal_type") or "")
        variant = meta.get("variant")
        identities = independent_evidence_ids([row])
        if metric not in QUALITY_DIRECTIONS or variant not in {"control", "candidate"} or not identities:
            continue
        identity = next(iter(identities))
        binding = (str(meta.get("task_id") or ""), str(meta.get("session_id") or ""),
                   str(meta.get("input_digest") or ""))
        if identity in bindings and bindings[identity] != binding:
            rejected["identity_or_input_mismatch"] += 1
        bindings[identity] = binding
        try:
            value = float(row["value"])
        except (TypeError, ValueError, KeyError):
            rejected["invalid_value"] += 1
            continue
        if not math.isfinite(value) or not 0 <= value <= 1:
            rejected["invalid_value"] += 1
            continue
        key = (identity, metric)
        old = buckets[key].get(variant)
        cluster = str(meta.get("cluster_id") or meta.get("task_id") or identity)
        if old is not None and old != (value, cluster):
            rejected["conflicting_duplicate"] += 1
        buckets[key][variant] = (value, cluster)
    metrics = defaultdict(list)
    matched_ids = set()
    for (identity, metric), variants in buckets.items():
        if set(variants) != {"control", "candidate"}:
            continue
        control, control_cluster = variants["control"]
        candidate, candidate_cluster = variants["candidate"]
        if control_cluster != candidate_cluster:
            rejected["cluster_mismatch"] += 1
            continue
        matched_ids.add(identity)
        metrics[metric].append((control_cluster, QUALITY_DIRECTIONS[metric] * (candidate - control)))
    summaries = {}
    # Bonferroni correction for the inspected metrics; fixed deterministic seed.
    alpha = 0.05 / (max(1, len(metrics)) * max(1, family_size))
    for metric, pairs in sorted(metrics.items()):
        clusters = defaultdict(list)
        for cluster, delta in pairs:
            clusters[cluster].append(delta)
        values = [sum(deltas) / len(deltas) for deltas in clusters.values()]
        rng = random.Random(1701)
        draws = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(1000))
        lower = draws[int(alpha * (len(draws) - 1))]
        summaries[metric] = {
            "pair_count": len(pairs), "independent_clusters": len(values),
            "mean_oriented_lift": sum(values) / len(values), "confidence_lower": lower,
            "passed": len(values) >= max(30, minimum) and lower >= -tolerance,
        }
    return {
        "schema": "clawos.paired-quality.v1", "observed_stage": stage,
        "matched_task_count": len(matched_ids), "metrics": summaries,
        "rejected": dict(rejected), "tolerance": tolerance,
        "confidence": "one-sided cluster bootstrap, family-wise alpha=0.05",
        "passed": bool(summaries) and not rejected and all(item["passed"] for item in summaries.values()),
        "scope": "task-bound reported runtime outcomes; no automatic semantic verification",
    }


def stratified_quality_report(rows, *, stage=None):
    """Predeclared task segments must each pass; averages cannot hide harm."""
    rows = list(rows)
    segments = defaultdict(list)
    identities = {}
    conflict = False
    for row in rows:
        meta = row.get('metadata') or {}
        if stage and meta.get('observed_stage') != stage:
            continue
        if meta.get('source') in {'runtime_snapshot', 'offline_replay', 'policy_materialization'}:
            continue
        segment = str(meta.get('segment') or 'default')
        for identity in independent_evidence_ids([row]):
            if identity in identities and identities[identity] != segment:
                conflict = True
            identities[identity] = segment
        segments[segment].append(row)
    reports = {segment: paired_quality_report(items, stage=stage, family_size=len(segments))
               for segment, items in sorted(segments.items())}
    return {'schema': 'clawos.stratified-quality.v1', 'segments': reports,
            'identity_segment_conflict': conflict, 'minimum_per_segment': 30,
            'passed': bool(reports) and not conflict and all(report['passed'] for report in reports.values()),
            'meaning': 'predeclared segments, Bonferroni across segments and metrics; insufficient support blocks'}
