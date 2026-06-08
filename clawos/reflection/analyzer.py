"""ReflectionAnalyzer - root cause analysis and insight extraction."""
import json

class ReflectionAnalyzer:
    """Analyzes task outcomes to extract root causes, insights, and improvements."""

    def __init__(self, store, http_client=None, api_config=None):
        self._store = store
        self._http = http_client
        self._config = api_config or {}

    def analyze(self, trajectory, outcome, task_description="", trigger=""):
        """Rule-based analysis (fast, offline)."""
        analysis = {
            "root_cause": self._find_root_cause(trajectory, outcome),
            "insights": self._extract_insights(trajectory, outcome),
            "improvements": self._generate_improvements(outcome),
            "patterns": self._mine_patterns(trajectory),
            "trigger": trigger,
        }
        return analysis

    async def analyze_with_llm(self, trajectory, outcome, task_description="", trigger=""):
        """LLM-powered deep analysis for complex cases."""
        if not self._http or not self._config.get("base_url"):
            return self.analyze(trajectory, outcome, task_description, trigger)

        prompt = self._build_analysis_prompt(trajectory, outcome, task_description)
        try:
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "You are a task analysis expert. Analyze the execution trajectory and provide root cause analysis, actionable insights, and improvement suggestions. Reply in JSON format with keys: root_cause, insights (array), improvements (array), patterns (array)."},
                    {"role": "user", "content": prompt}
                ],
                "stream": False, "temperature": 0.3, "max_tokens": 500
            }
            headers = {
                "Authorization": f"Bearer {self._config.get('api_key', '')}",
                "Content-Type": "application/json"
            }
            url = f"{self._config['base_url'].rstrip('/')}/chat/completions"
            resp = await self._http.post(url, json=payload, headers=headers, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # Fallback: parse text
                return {"root_cause": content[:500], "insights": [], "improvements": [], "patterns": []}
        except Exception:
            return self.analyze(trajectory, outcome, task_description, trigger)

    def _build_analysis_prompt(self, trajectory, outcome, task_description):
        tools_str = json.dumps([{
            "name": tc.get("name", ""),
            "result": str(tc.get("result", ""))[:200]
        } for tc in trajectory.get("tool_calls", [])], ensure_ascii=False)
        return f"""Task: {task_description or "Unknown"}
Outcome: {outcome.get("outcome", "unknown")}
Reason: {outcome.get("reason", "")}
Errors: {outcome.get("errors", [])}
Tool calls: {tools_str}
Key events: {json.dumps(trajectory.get("key_events", []), ensure_ascii=False)}
Please analyze the root cause and provide insights."""

    def _find_root_cause(self, trajectory, outcome):
        errors = outcome.get("errors", [])
        if not errors:
            return "All tools executed successfully. No errors detected."
        error_tools = []
        for tc in trajectory.get("tool_calls", []):
            result = tc.get("result", {})
            if isinstance(result, str):
                try: result = json.loads(result)
                except: pass
            if isinstance(result, dict) and "error" in result:
                error_tools.append({"tool": tc.get("name", ""), "error": str(result["error"])[:200]})
        if error_tools:
            return f"Errors in tools: {json.dumps(error_tools, ensure_ascii=False)}"
        return f"Partial failure: {len(errors)} tools returned errors"

    def _extract_insights(self, trajectory, outcome):
        insights = []
        if outcome["outcome"] == "success":
            insights.append(f"Successful execution of {outcome.get('total_tools', 0)} tools")
            insights.append("Tool chain worked correctly - consider solidifying as a skill")
        elif outcome["outcome"] == "failure":
            insights.append(f"All {outcome.get('total_tools', 0)} tools failed - review input parameters")
            insights.append("Check API keys, file paths, and network connectivity")
        else:
            insights.append(f"Partial success: {outcome.get('error_count', 0)} of {outcome.get('total_tools', 0)} tools failed")
            insights.append("Identify which tool inputs caused errors and validate them")
        return insights

    def _generate_improvements(self, outcome):
        improvements = []
        if outcome["outcome"] in ("failure", "partial"):
            improvements.append("Validate tool input parameters before execution")
            improvements.append("Add parameter sanitization for failing tools")
        if outcome.get("total_tools", 0) > 2:
            improvements.append("Consider registering this workflow as a solidified skill for faster execution")
        improvements.append("Review error logs and adjust tool configurations")
        return improvements

    def _mine_patterns(self, trajectory):
        patterns = []
        tools_used = [tc.get("name", "") for tc in trajectory.get("tool_calls", [])]
        if len(tools_used) > 1:
            patterns.append(f"Common tool sequence: {' -> '.join(tools_used[:5])}")
        # Check against past experiences
        past = self._store.get_recent_experiences(5)
        for exp in past:
            if any(t in (exp.get("task") or "") for t in tools_used):
                patterns.append(f"Similar to past experience: {exp.get('task', '')[:80]}")
                break
        return patterns
