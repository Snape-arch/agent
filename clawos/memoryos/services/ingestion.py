"""IngestionService - auto-extract memories from conversations."""
import json, re

class IngestionService:
    """Extracts structured memories from raw conversation text."""

    PROFILE_PATTERNS = [
        (r"(?:I am|name is)[ 	]+(?:a|an)?[ 	]*(.+?)(?:[,.]|$)", "role"),
        (r"(?:research|研究方向|研究)[ 	]+(?:is|是|方向|field)[ 	]*(.+?)(?:[,.]|$)", "research_direction"),
        (r"(?:skills?|技能|擅长)[ 	]+(?:are|include|有|包括)[ 	]*(.+?)(?:[,.]|$)", "skills"),
        (r"(?:interests?|兴趣|喜欢)[ 	]+(?:in|是|在)[ 	]*(.+?)(?:[,.]|$)", "interests"),
    ]

    PREFERENCE_PATTERNS = [
        (r"(?:code|代码)[ 	]+(?:style|风格)[ 	]+(?:prefer|偏好|喜欢|like)[ 	]+(.+?)(?:[,.]|$)", "code_style"),
        (r"(?:ppt|slides?)[ 	]+(?:style|风格)[ 	]+(?:prefer|偏好|喜欢|like)[ 	]+(.+?)(?:[,.]|$)", "ppt_style"),
        (r"(?:reply|response|回复|回答)[ 	]+(?:style|风格|方式)[ 	]+(?:prefer|偏好|喜欢|like)[ 	]+(.+?)(?:[,.]|$)", "reply_style"),
        (r"(?:tool|工具)[ 	]+(?:prefer|偏好|喜欢|like)[ 	]+(.+?)(?:[,.]|$)", "tool_preference"),
    ]

    def __init__(self, store):
        self._store = store

    def ingest_conversation(self, session_id, role, content):
        if role != "user":
            return {"profiles": [], "preferences": []}
        pf = []
        for pattern, key in self.PROFILE_PATTERNS:
            m = re.search(pattern, content, re.IGNORECASE)
            if m:
                v = m.group(1).strip()[:100]
                cat = "basic_info" if key == "role" else "interests" if key in ("interests","research_direction") else "skills"
                self._store.set_profile(key, v, cat, importance=0.7)
                pf.append({"key": key, "value": v})
        pr = []
        for pattern, key in self.PREFERENCE_PATTERNS:
            m = re.search(pattern, content, re.IGNORECASE)
            if m:
                v = m.group(1).strip()[:100]
                cat = "content" if key in ("code_style","ppt_style","reply_style") else "tool"
                self._store.set_preference(key, v, cat, confidence=0.6)
                pr.append({"key": key, "value": v})
        return {"profiles": pf, "preferences": pr}

    def extract_knowledge(self, title, content, category="domain"):
        self._store.add_knowledge(title, content, category)
