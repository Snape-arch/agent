"""Shared lexical evidence selection. A match is an excerpt, never answer verification."""
import hashlib
import heapq
import re

STOP = set("what when where how why is are was the a an of to in for does do please tell me about".split())


def terms(text):
    text = str(text).lower()
    words = {w for w in re.findall(r"[a-z0-9_]+", text) if w not in STOP}
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        words.update(run[i:i+2] for i in range(len(run)-1))
    return words


def evidence(row, revision=""):
    meta = row.get("metadata") or {}
    text = str(row.get("content", row.get("text", ""))).strip()
    return dict(row, text=text,
        citation=row.get("citation") or (str(row["id"]) if "document_id" not in row else f"doc:{row['document_id']}#chunk={row.get('chunk_index')}"),
        revision=revision or row.get("revision") or hashlib.sha256(text.encode()).hexdigest(),
        revision_scope="material" if revision else "passage",
        review_required=bool(row.get("review_required") or meta.get("review_required")))


def retrieve(query, rows, limit=5, revision=""):
    tokens = terms(query)
    def candidates():
        for index, row in enumerate(rows):
            item = evidence(row, revision)
            if item["review_required"] or not item["text"]:
                continue
            hits = tokens & terms(item["text"])
            score = len(hits) / max(1, len(tokens))
            if tokens and (score < .3 or not hits):
                continue
            if query.strip() and not tokens:
                continue
            yield (score, -index, dict(item, retrieval_score=round(score, 4)))
    return [item for _, _, item in heapq.nlargest(max(1,min(int(limit),12)), candidates(), key=lambda x:x[:2])]
