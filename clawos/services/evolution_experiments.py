"""Bounded reflective search and immutable, read-only paired task replay.

This is native configuration search, not a claim of GEPA training or online RL.
The built-in replay executes production retrieval/routing functions on a frozen
corpus. Prompt semantics require a separate real provider/judge protocol.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import tempfile
import time
import importlib
import inspect
import types
from pathlib import Path

from reflection.evolution_runtime import RuntimePolicyController
from services.learning_governance import paired_quality_report


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def source_fingerprints():
    root = Path(__file__).resolve().parents[1]
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in (
        "services/evolution_experiments.py", "services/learning_governance.py",
        "reflection/evolution_runtime.py", "memoryos/services/retrieval.py",
        "services/knowledge_core_service.py", "memoryos/memory_store.py")}


def loaded_executor_digest():
    """Bind evidence to imported code as well as files (long-lived workers)."""
    signatures = []
    for name in ('services.evolution_experiments', 'services.learning_governance',
                 'reflection.evolution_runtime', 'memoryos.services.retrieval',
                 'services.knowledge_core_service', 'memoryos.memory_store'):
        module = importlib.import_module(name)
        for member_name, member in sorted(vars(module).items()):
            if inspect.isclass(member) and member.__module__ == name:
                members = sorted(vars(member).items())
            elif inspect.isfunction(member) and member.__module__ == name:
                members = [(member_name, member)]
            else:
                continue
            for method_name, method in members:
                if isinstance(method, (staticmethod, classmethod)):
                    method = method.__func__
                if inspect.isfunction(method):
                    method = inspect.unwrap(method)
                    signatures.append((name, member_name, method_name, _code_digest(method.__code__)))
    return digest(signatures)


def _code_digest(code):
    # marshal records interpreter string-interning state; that state can change
    # after executing a function. Hash immutable bytecode/constants instead.
    def constant(value):
        if isinstance(value, types.CodeType):
            return {"code": _code_digest(value)}
        if isinstance(value, (tuple, frozenset)):
            values = list(value) if isinstance(value, tuple) else sorted(value, key=repr)
            return [constant(item) for item in values]
        return {"type": type(value).__name__, "value": repr(value)}
    return digest({"bytecode": code.co_code.hex(), "constants": [constant(item) for item in code.co_consts],
                   "names": code.co_names, "variables": code.co_varnames, "freevars": code.co_freevars,
                   "cellvars": code.co_cellvars, "flags": code.co_flags,
                   "args": [code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount],
                   "exception_table": getattr(code, 'co_exceptiontable', b'').hex()})


def candidate_pool(target_type, baseline, reflections=None):
    from reflection.self_evolution import SelfEvolutionManager
    SelfEvolutionManager._assert_allowed_target(target_type)
    if not isinstance(baseline, dict):
        raise ValueError("baseline must be an object")
    rows = [row for row in (reflections or []) if isinstance(row, dict)][:100]
    counts = Counter(str(row.get("failure_category") or "unknown") for row in rows)
    evidence = {"reflection_count": len(rows), "failure_categories": dict(counts),
                "verified_gain": False, "method": "bounded_reflective_config_search.v1"}
    repeated = Counter(" ".join(str(pattern).lower().split())[:160]
                       for row in rows for pattern in row.get("patterns") or [])
    evidence["repeated_patterns"] = [{"pattern": pattern, "count": count}
                                     for pattern, count in repeated.most_common(5) if count >= 2]
    alternatives = []
    if target_type in {"retrieval_params", "retrieval_policy"}:
        top = RuntimePolicyController.retrieval_options({"payload": baseline})["top_k"]
        latency_pressure = counts.get("latency", 0) + counts.get("resource", 0)
        for name, k, citation in (("compact", max(1, top // (3 if latency_pressure else 2)), True),
                                  ("coverage", min(50, max(top + (2 if latency_pressure else 5), top * (1 if latency_pressure else 2))), True),
                                  ("evidence", top, True)):
            alternatives.append((name, {**baseline, "top_k": k, "recall_top_k": max(30, k),
                                        "citation_aware": citation}))
    elif target_type in {"prompt", "prompt_policy"}:
        text = str(baseline.get("system") or baseline.get("prompt") or "")[:16000]
        rules = {
            "grounded": "Cite the supplied sources for factual claims; abstain when evidence is insufficient.",
            "conditions": "Preserve experimental conditions and distinguish observed results from inference.",
            "repair": "Validate inputs, check the failed step against evidence, and use the documented fallback.",
        }
        for name, rule in rules.items():
            alternatives.append((name, {**baseline, "system": text + "\n\n" + rule}))
    elif target_type in {"report_template", "template_policy"}:
        for name, sections in (
            ("evidence", ["abstract", "method", "evidence", "limitations"]),
            ("comparison", ["abstract", "conditions", "comparisons", "limitations", "next_actions"]),
            ("compact", ["abstract", "evidence", "limitations", "next_actions"]),
        ):
            alternatives.append((name, {**baseline, "sections": sections, "typography": "journal"}))
    else:
        alternatives.append(("preserve", {**baseline}))
        alternatives.append(("reduce_surface", {**baseline, "deny_tools": sorted(set(
            baseline.get("deny_tools", []) + ["shell_exec", "file_write", "web_fetch"]))}))
        # Restrict the surface only: candidate search never expands permissions.
        alternatives.append(("local", {**baseline, "deny_tools": sorted(set(
            baseline.get("deny_tools", []) + ["web_fetch", "web_search"]))}))
    unique = {}
    for name, payload in alternatives:
        signature = digest(payload)
        if signature == digest(baseline):
            continue
        unique.setdefault(signature, {"id": signature[:16], "name": name, "payload": payload,
                                      "payload_digest": signature, "evidence": evidence})
    preferred = ("compact" if counts.get("latency") or counts.get("resource") else
                 "repair" if counts.get("parameter") or counts.get("environment") else
                 "reduce_surface" if counts.get("permission") else "coverage")
    # Reflection evidence guides search order/budget, never predeclares a winner.
    for candidate in unique.values():
        candidate["hypothesis"] = {"compact": "降低上下文成本", "coverage": "找回遗漏的来源",
            "evidence": "保留来源标识", "grounded": "减少无证据断言",
            "conditions": "保留实验条件", "repair": "避免重复失败的步骤",
            "reduce_surface": "移除不必要的高风险工具", "local": "避开不可用的外部工具",
            "comparison": "明确实验对比"}.get(candidate["name"], "精简配置")
    return sorted(unique.values(), key=lambda candidate: candidate["name"] != preferred)


class EvolutionExperimentService:
    SUPPORTED_TARGETS = {"retrieval_params", "retrieval_policy", "tool_routing_policy", "tool_policy", "routing_policy"}

    def __init__(self, store):
        self.store = store

    def freeze(self, *, target_type, target_key, baseline_payload, cases, documents=None,
               reflections=None, created_by="system"):
        if target_type not in self.SUPPORTED_TARGETS:
            raise ValueError("built-in replay supports retrieval and read-only tool routing; prompt/template semantics require real model outputs and reviewed labels")
        if not isinstance(baseline_payload, dict) or not str(target_key).strip():
            raise ValueError("target key and baseline object are required")
        if not isinstance(cases, list) or not 2 <= len(cases) <= 500:
            raise ValueError("supply 2..500 reviewed task cases; >=30 held-out independent groups are required for acceptance")
        documents = documents or []
        if not isinstance(documents, list) or len(documents) > 100:
            raise ValueError("at most 100 frozen source documents are supported")
        sources = {}
        frozen_documents = []
        for doc in documents:
            ref = str(doc.get("source_ref") or "").strip()
            content = str(doc.get("content") or "")
            if not ref or ref in sources or not content or len(content) > 32000:
                raise ValueError("source references must be unique with 1..32000 characters of content")
            if not self.store.document_source_usable(ref):
                raise ValueError("source requires review before it can be frozen")
            item = {"source_ref": ref, "title": str(doc.get("title") or "")[:300],
                    "content": content, "content_digest": digest(content)}
            sources[ref] = item
            frozen_documents.append(item)
        seen_ids, seen_inputs = set(), set()
        frozen_cases = []
        for case in cases:
            if not isinstance(case, dict):
                raise ValueError("each case must be an object")
            cid, group = str(case.get("id") or "").strip(), str(case.get("group_id") or "").strip()
            origin = case.get("origin") or "curated"
            if origin not in {"curated", "task"}:
                raise ValueError("case origin must be curated or task")
            query = str(case.get("query") or "").strip()
            task_id = case.get("task_id")
            if origin == "task":
                task = (self.store.get_task(task_id) or {}).get("task") or {}
                if not task:
                    raise ValueError("task-bound case must reference an existing task")
                query = str(task.get("description") or task.get("title") or "").strip()
            if not cid or not group or cid in seen_ids or len(cid) > 120 or len(group) > 120 or not query or len(query) > 4000:
                raise ValueError("each case needs a unique id, bounded group_id and query")
            if not case.get("reviewed_by"):
                raise ValueError("expected outcomes require a named reviewer")
            item = {"id": cid, "group_id": group, "query": query, "origin": origin,
                    "task_id": task_id, "reviewed_by": str(case["reviewed_by"])[:120]}
            if target_type.startswith("retrieval"):
                expected = list(dict.fromkeys(str(ref) for ref in case.get("expected_source_refs") or []))
                if not expected or any(ref not in sources for ref in expected):
                    raise ValueError("retrieval labels must reference the frozen source corpus")
                item["expected_source_refs"] = expected
            else:
                route = case.get("route") or {}
                allowed = route.get("allowed_tools") or []
                required = case.get("required_tools") or []
                forbidden = case.get("forbidden_tools") or []
                if (not isinstance(allowed, list) or not allowed or len(allowed) > 100
                        or not isinstance(required, list) or not isinstance(forbidden, list)
                        or not set(required) <= set(allowed) or set(required) & set(forbidden)):
                    raise ValueError("routing labels must be consistent with the original allowed tools")
                item.update(route={"allowed_tools": allowed, "requires_confirmation": route.get("requires_confirmation") or []},
                            required_tools=required, forbidden_tools=forbidden)
            # A duplicated input is not a second independent task, even under a
            # different id/group. Expected labels are excluded from the digest.
            input_hash = digest({"query": query, "route": item.get("route")})
            if input_hash in seen_inputs:
                raise ValueError("duplicate task input would contaminate independence or the holdout")
            seen_inputs.add(input_hash)
            seen_ids.add(cid)
            item["input_digest"] = input_hash
            item["split"] = "holdout" if int(hashlib.sha256(group.encode()).hexdigest(), 16) % 5 == 0 else "search"
            frozen_cases.append(item)
        candidates = candidate_pool(target_type, baseline_payload, reflections)
        if not candidates:
            raise ValueError("candidate pool contains no policy changes")
        current = self.store.get_runtime_policy(target_type, target_key)
        if current and current.get("payload") != baseline_payload:
            raise ValueError("baseline payload differs from current runtime policy")
        definition = {"schema": "clawos.evolution-experiment.v1", "target_type": target_type,
                      "target_key": str(target_key), "baseline_payload": baseline_payload,
                      "baseline_policy_version": int(current["version"]) if current else 0,
                      "documents": frozen_documents, "cases": frozen_cases, "candidates": candidates,
                      "split_rule": "sha256(group_id) mod 5; 0=holdout, others=search",
                      "executor_version": "production-retrieval-routing.v1",
                      "source_sha256": source_fingerprints(),
                      "loaded_executor_digest": loaded_executor_digest(),
                      "scope": "offline frozen labelled cases; no model, vector or user-traffic claim"}
        if len(json.dumps(definition, ensure_ascii=False).encode()) > 8 * 1024 * 1024:
            raise ValueError("frozen experiment exceeds 8MiB")
        with self.store.transaction():
            # Capture baseline and definition together with a CAS check.
            fresh = self.store.get_runtime_policy(target_type, target_key)
            if (int(fresh["version"]) if fresh else 0) != definition["baseline_policy_version"]:
                raise ValueError("runtime policy changed during freezing")
            with self.store._conn() as conn:
                duplicate = conn.execute("SELECT id FROM evolution_experiments WHERE definition_digest=?", (digest(definition),)).fetchone()
            if duplicate:
                return self.store.get_evolution_experiment(duplicate["id"])
            return self.store.create_evolution_experiment(definition, digest(definition), created_by)

    def replay(self, experiment_id):
        experiment = self.store.claim_evolution_experiment(experiment_id)
        definition = experiment["definition"]
        try:
            if definition.get('source_sha256') != source_fingerprints():
                raise ValueError('replay source changed; freeze a fresh experiment')
            if definition.get('loaded_executor_digest') != loaded_executor_digest():
                raise ValueError('loaded executor changed; restart the preview and freeze a fresh experiment')
            with tempfile.TemporaryDirectory(prefix="clawos-replay-") as td:
                from memoryos.memory_store import MemoryStore
                from memoryos.services.retrieval import RetrievalService
                frozen_store = MemoryStore(str(Path(td) / "replay.db"))
                for document in definition["documents"]:
                    frozen_store.add_knowledge(document["title"], document["content"],
                                               source="replay:" + document["source_ref"], confidence=0.9)
                # Explicitly disable environment/model-dependent rerankers.
                retrieval = RetrievalService(frozen_store, allow_env_reranker=False)
                report = self._execute(definition, retrieval)
            if (definition['source_sha256'] != source_fingerprints()
                    or definition['loaded_executor_digest'] != loaded_executor_digest()):
                raise ValueError('executor changed during replay; evidence cannot be finalized')
            report["definition_digest"] = experiment["definition_digest"]
            report["report_digest"] = digest(report)
            return self.store.finish_evolution_experiment(experiment_id, report)
        except Exception as exc:
            self.store.finish_evolution_experiment(experiment_id, {"error": type(exc).__name__, "message": str(exc)[:500]}, failed=True)
            raise

    def _execute(self, definition, retrieval):
        cases = definition["cases"]
        search = [case for case in cases if case["split"] == "search"]
        holdout = [case for case in cases if case["split"] == "holdout"]
        if not search or not holdout:
            raise ValueError("both search and holdout task groups are required")
        baseline = {"id": "baseline", "name": "baseline", "payload": definition["baseline_payload"]}
        alternatives = [baseline] + definition["candidates"]
        search_outputs = {}
        rankings = []
        deadline = time.perf_counter() + 180
        # Interleave baseline/candidates per case; reverse order on alternate
        # cases to limit warm-cache timing bias. Search never sees holdout labels.
        for index, case in enumerate(search):
            ordered = alternatives if index % 2 == 0 else list(reversed(alternatives))
            for candidate in ordered:
                if time.perf_counter() > deadline:
                    raise ValueError('bounded replay exceeded 180 seconds; reduce the dataset')
                search_outputs.setdefault(candidate["id"], []).append(self._run_case(definition, case, candidate["payload"], retrieval))
        for candidate in alternatives:
            summary = self._summary(search_outputs[candidate["id"]])
            rankings.append({"id": candidate["id"], "name": candidate["name"], **summary})
        frontier = [row for row in rankings if not any(
            other["quality"] >= row["quality"] and other["context_chars"] <= row["context_chars"]
            and (other["quality"] > row["quality"] or other["context_chars"] < row["context_chars"])
            and other["safety_violations"] == 0 for other in rankings if other is not row)]
        eligible = [row for row in frontier if row["safety_violations"] == 0]
        winner = max(eligible, key=lambda row: (row["quality"], -row["context_chars"], row["id"] == "baseline")) if eligible else rankings[0]
        chosen = next(candidate for candidate in alternatives if candidate["id"] == winner["id"])
        pairs, signals = [], []
        for index, case in enumerate(holdout):
            if time.perf_counter() > deadline:
                raise ValueError('bounded replay exceeded 180 seconds; reduce the dataset')
            order = (baseline, chosen) if index % 2 == 0 else (chosen, baseline)
            outcomes = [self._run_case(definition, case, candidate["payload"], retrieval) for candidate in order]
            control, candidate = outcomes if index % 2 == 0 else list(reversed(outcomes))
            pairs.append({"case_id": case["id"], "group_id": case["group_id"], "input_digest": case["input_digest"],
                          "control": control, "candidate": candidate})
            for variant, outcome in (("control", control), ("candidate", candidate)):
                for metric, value in (("quality_score", outcome["quality"]), ("citation_coverage", outcome["citation_coverage"])):
                    signals.append({"signal_type": metric, "value": value,
                                "metadata": {"variant": variant, "evidence_id": case["id"],
                                             "cluster_id": case["group_id"], "input_digest": case["input_digest"]}})
        paired = paired_quality_report(signals)
        safety_ok = not any(pair["candidate"]["safety_violations"] for pair in pairs)
        c = self._summary([pair["candidate"] for pair in pairs])
        b = self._summary([pair["control"] for pair in pairs])
        cost_ok = c["context_chars"] <= max(4000, b["context_chars"] * 2)
        latency_ok = c["p95_latency_ms"] <= b["p95_latency_ms"] * 1.2 + 10
        changed = chosen["id"] != "baseline"
        observed_change = any(digest(pair["control"]["output"]) != digest(pair["candidate"]["output"]) for pair in pairs)
        return {"schema": "clawos.paired-replay.v1", "scope": definition["scope"],
                "selection_split": "search_only", "holdout_used_for_selection": False,
                "search_groups": len({case["group_id"] for case in search}),
                "holdout_groups": len({case["group_id"] for case in holdout}),
                "search_rankings": rankings, "pareto_frontier": [row["id"] for row in frontier],
                "selected_candidate_id": chosen["id"], "selected_payload": chosen["payload"],
                "baseline": b, "candidate": c, "paired_gate": paired, "holdout_pairs": pairs,
                "gates": {"paired_non_regression": paired["passed"], "safety": safety_ok,
                          "context_budget": cost_ok, "latency": latency_ok, "changed_candidate": changed,
                          "actual_output_changed": observed_change},
                "eligible_for_regression_queue": paired["passed"] and safety_ok and cost_ok and latency_ok and changed and observed_change,
                "runtime_promotion_evidence": False, "semantic_entailment_verified": False,
                "meaning": "labelled source recall or routing contract quality; not answer semantics or measured monetary cost"}

    @staticmethod
    def _run_case(definition, case, payload, retrieval):
        started = time.perf_counter()
        if definition["target_type"].startswith("retrieval"):
            options = RuntimePolicyController.retrieval_options({"payload": payload})
            output = retrieval.retrieve_for_context(case["query"], policy=options)
            results = retrieval.retrieve(case["query"], top_k=options["top_k"], recall_k=options["recall_top_k"])
            found = [str(row.get("citation", ""))[7:] for row in results
                     if str(row.get("citation", "")).startswith("replay:")
                     and (str(row.get("title", "")) + " " + str(row.get("content", ""))[:200]) in output]
            expected = case["expected_source_refs"]
            quality = len(set(found) & set(expected)) / len(expected)
            citation_coverage = sum("[replay:" + ref + "]" in output for ref in expected) / len(expected)
            violations = 0
            chars = len(output)
        else:
            output = RuntimePolicyController.apply_routing(case["route"], {"payload": payload})
            tools = set(output["allowed_tools"])
            required = set(case["required_tools"])
            violations = len(tools & set(case["forbidden_tools"]))
            quality = float(required <= tools and not violations)
            citation_coverage = 1.0  # Not applicable to routing, invariant across variants.
            chars = 0
        return {"output": output, "output_digest": digest(output), "quality": quality, "citation_coverage": citation_coverage,
                "safety_violations": violations, "context_chars": chars,
                "latency_ms": (time.perf_counter() - started) * 1000}

    @staticmethod
    def _summary(outcomes):
        latencies = sorted(row["latency_ms"] for row in outcomes)
        return {"case_count": len(outcomes), "quality": sum(row["quality"] for row in outcomes) / len(outcomes),
                "context_chars": sum(row["context_chars"] for row in outcomes) / len(outcomes),
                "safety_violations": sum(row["safety_violations"] for row in outcomes),
                "p95_latency_ms": latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))]}

    def nominate(self, experiment_id, actor_id="system"):
        from reflection.self_evolution import SelfEvolutionManager
        with self.store.transaction():
            experiment = self.store.get_evolution_experiment(experiment_id)
            if not experiment or experiment["status"] != "completed" or not experiment["report"].get("eligible_for_regression_queue"):
                raise ValueError("a completed held-out paired replay must pass before nomination")
            definition, report = experiment["definition"], experiment["report"]
            if definition.get('source_sha256') != source_fingerprints():
                raise ValueError('replay source changed; freeze a fresh experiment')
            if definition.get('loaded_executor_digest') != loaded_executor_digest():
                raise ValueError('loaded executor changed; freeze a fresh experiment')
            current = self.store.get_runtime_policy(definition["target_type"], definition["target_key"])
            if (int(current["version"]) if current else 0) != definition["baseline_policy_version"]:
                raise ValueError("runtime policy changed; freeze and replay a fresh experiment")
            # Idempotent nomination: repeated requests do not create competing runs.
            title = f"Paired replay experiment {experiment_id}"
            with self.store._conn() as conn:
                previous = conn.execute("SELECT id FROM self_evolution_runs WHERE title=?", (title,)).fetchone()
            if previous:
                return self.store.get_self_evolution_run(previous["id"])
            return SelfEvolutionManager(self.store).create_run(
                definition["target_type"], definition["target_key"], definition["baseline_payload"],
                report["selected_payload"], title=title, created_by=actor_id,
                conclusion=f"Offline held-out replay {report['report_digest']}; regression, fresh shadow and canary outcomes still required.")
