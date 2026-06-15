"""IngestionService - auto-extract memories from conversations."""

import re


class IngestionService:
    """Extracts structured memories from raw conversation text."""

    PROFILE_PATTERNS = [
        (r"(?:I am|name is|my name is)\s+(?:a|an)?\s*(.+?)(?:[,.。；;]|$)", "role"),
        (r"(?:我叫|我的名字是|名字是)\s*(.+?)(?:[，,。；;]|$)", "name"),
        (r"(?:research|研究方向|研究领域|研究)\s*(?:is|是|为|field)?\s*(.+?)(?:[,.，。；;]|$)", "research_direction"),
        (r"(?:skills?|技能|擅长)\s*(?:are|include|是|包括|有)?\s*(.+?)(?:[,.，。；;]|$)", "skills"),
        (r"(?:interests?|兴趣|爱好)\s*(?:in|是|为|包括)?\s*(.+?)(?:[,.，。；;]|$)", "interests"),
    ]

    PREFERENCE_PATTERNS = [
        (r"(?:code|代码)\s*(?:style|风格)\s*(?:prefer|偏好|喜欢|like|是|为)?\s*(.+?)(?:[,.，。；;]|$)", "code_style"),
        (r"(?:ppt|slides?|幻灯片|演示)\s*(?:style|风格)\s*(?:prefer|偏好|喜欢|like|是|为)?\s*(.+?)(?:[,.，。；;]|$)", "ppt_style"),
        (r"(?:reply|response|回复|回答)\s*(?:style|风格|方式)\s*(?:prefer|偏好|喜欢|like|是|为)?\s*(.+?)(?:[,.，。；;]|$)", "reply_style"),
        (r"(?:我喜欢|我偏好)\s*(.+?(?:回复|回答|风格|语气|方式).+?)(?:[,.，。；;]|$)", "reply_style"),
        (r"(?:tool|工具)\s*(?:prefer|偏好|喜欢|like|是|为)?\s*(.+?)(?:[,.，。；;]|$)", "tool_preference"),
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
                value = m.group(1).strip()[:100]
                category = "basic_info" if key in ("role", "name") else "interests" if key in ("interests", "research_direction") else "skills"
                result = self._store.set_profile(
                    key,
                    value,
                    category,
                    importance=0.7,
                    source="conversation_ingestion",
                    actor_id=session_id,
                    evidence=[{
                        "evidence_type": "conversation",
                        "source_ref": session_id,
                        "excerpt": content[:1000],
                    }],
                    conflict_policy="review",
                )
                pf.append({
                    "key": key,
                    "value": value,
                    "review_required": bool(result.get("review_required")),
                })
        pr = []
        for pattern, key in self.PREFERENCE_PATTERNS:
            m = re.search(pattern, content, re.IGNORECASE)
            if m:
                value = m.group(1).strip()[:100]
                category = "content" if key in ("code_style", "ppt_style", "reply_style") else "tool"
                result = self._store.set_preference(
                    key,
                    value,
                    category,
                    confidence=0.6,
                    source="conversation_ingestion",
                    actor_id=session_id,
                    evidence=[{
                        "evidence_type": "conversation",
                        "source_ref": session_id,
                        "excerpt": content[:1000],
                    }],
                    conflict_policy="review",
                )
                pr.append({
                    "key": key,
                    "value": value,
                    "review_required": bool(result.get("review_required")),
                })
        return {"profiles": pf, "preferences": pr}

    def extract_knowledge(self, title, content, category="domain"):
        self._store.add_knowledge(title, content, category)
