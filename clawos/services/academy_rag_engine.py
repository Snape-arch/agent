"""Small reproducible RAG teaching benchmark; synthetic, non-production data.

This module also runs standalone after exporting the workshop project.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

VERSION = "makerspace-rag.v1"
DOCUMENTS = [
    {"id": "hours", "title": "开放时间", "current": True,
     "text": "创客空间开放时间为周二至周日 09:00—18:00。每周一闭馆维护。"},
    {"id": "loan-old", "title": "器材借用旧版", "current": False,
     "text": "器材借用期限为 14 天。这份旧版规定已停用。"},
    {"id": "loan", "title": "器材借用现行规定", "current": True,
     "text": "器材借用期限为 7 天。归还后工作人员检查器材完整性。"},
    {"id": "booking", "title": "工作坊预约", "current": True,
     "text": "工作坊每场最多 12 人。工作坊预约应至少提前 24 小时完成。"},
    {"id": "printer", "title": "打印服务", "current": True,
     "text": "打印服务仅提供黑白打印。纸张规格为 A4。"},
    {"id": "locker", "title": "储物柜", "current": True,
     "text": "储物柜只供当天使用。闭馆前请取走个人物品。"},
]
CASES = [
    {"id": "hours", "query": "创客空间开放时间是什么？", "source": "hours", "fact": "09:00—18:00", "kind": "事实定位"},
    {"id": "loan", "query": "器材借用期限是多少天？", "source": "loan", "fact": "7 天", "kind": "过期来源"},
    {"id": "booking", "query": "工作坊每场最多多少人？", "source": "booking", "fact": "12 人", "kind": "事实定位"},
    {"id": "advance", "query": "工作坊预约应至少提前多久？", "source": "booking", "fact": "24 小时", "kind": "片段完整性"},
    {"id": "printer", "query": "打印服务提供什么颜色？", "source": "printer", "fact": "黑白打印", "kind": "事实定位"},
    {"id": "missing", "query": "创客空间停车位预约价格是多少？", "source": None, "fact": None, "kind": "无答案拒答"},
]
DEFAULT_CONFIG = {"chunk_size": 24, "top_k": 1, "min_score": 0.05, "current_only": False}


def validate_config(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_CONFIG):
        raise ValueError("配置必须包含 chunk_size、top_k、min_score、current_only")
    if type(value["chunk_size"]) is not int or not 8 <= value["chunk_size"] <= 160:
        raise ValueError("片段长度应为 8–160 个字符")
    if type(value["top_k"]) is not int or not 1 <= value["top_k"] <= 4:
        raise ValueError("召回数量应为 1–4")
    if type(value["min_score"]) not in (int, float) or not math.isfinite(value["min_score"]) or not 0 <= value["min_score"] <= 1:
        raise ValueError("拒答阈值应为 0–1")
    if type(value["current_only"]) is not bool:
        raise ValueError("现行资料开关必须为布尔值")
    return dict(value)


def tokens(text):
    chars = re.sub(r"[\W_]", "", text.lower())
    return {chars[i:i+2] for i in range(len(chars)-1)}


def retrieve(query, config):
    config = validate_config(config)
    q = tokens(query)
    chunks = []
    for doc in DOCUMENTS:
        if config["current_only"] and not doc["current"]:
            continue
        for start in range(0, len(doc["text"]), config["chunk_size"]):
            text = doc["text"][start:start+config["chunk_size"]]
            score = len(q & tokens(text)) / max(1, len(q))
            if score > 0 and score >= config["min_score"]:
                chunks.append(dict(id=f"{doc['id']}:{start}", document_id=doc["id"], title=doc["title"],
                                   start=start, end=start+len(text), text=text, score=round(score, 6), current=doc["current"]))
    return sorted(chunks, key=lambda c: -c["score"])[:config["top_k"]]


def baseline_answer(chunks):
    if not chunks:
        return {"answer": "资料不足，无法回答。", "citations": [], "abstain": True}
    # Deliberately simple baseline: copy the strongest retrieved passage. It
    # cannot perform paraphrase, multi-hop synthesis, or semantic verification.
    return {"answer": chunks[0]["text"], "citations": [chunks[0]["id"]], "abstain": False}


def evaluate(case, chunks, response):
    if not isinstance(response, dict) or not isinstance(response.get("answer"), str) or not isinstance(response.get("citations"), list) or type(response.get("abstain")) is not bool:
        raise ValueError("回答需要 answer 文本、citations 数组和 abstain 布尔值")
    if len(response["answer"]) > 8000 or any(not isinstance(c, str) for c in response["citations"]) or len(response["citations"]) > 8:
        raise ValueError("回答或引用超出允许范围")
    by_id = {c["id"]: c for c in chunks}
    citations = response["citations"]
    located = bool(citations) and all(c in by_id for c in citations)
    retrieved = case["source"] is None or any(c["document_id"] == case["source"] and case["fact"] in c["text"] for c in chunks)
    supported = located and any(by_id[c]["document_id"] == case["source"] and (case["fact"] or "") in by_id[c]["text"] for c in citations)
    fact = case["fact"] is not None and case["fact"] in response["answer"]
    decision = response["abstain"] == (case["source"] is None)
    passed = (response["abstain"] and not citations) if case["source"] is None else (not response["abstain"] and retrieved and supported and fact)
    failures = []
    if not retrieved:
        failures.append("retrieval")
    if not decision:
        failures.append("abstention")
    if case["source"] is not None and not supported:
        failures.append("citation")
    if case["source"] is not None and not fact:
        failures.append("fact")
    if case["source"] is None and citations:
        failures.append("citation")
    return dict(passed=bool(passed), retrieved=retrieved, citation_supported=bool(supported),
                expected_fact_present=bool(fact), decision_correct=decision, failures=failures,
                boundary="固定教学样本的事实字符串、来源和拒答检查；未验证自由文本中的所有语义主张。")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def run(config):
    config = validate_config(config)
    rows = []
    for case in CASES:
        chunks = retrieve(case["query"], config)
        response = baseline_answer(chunks)
        rows.append(dict(case_id=case["id"], query=case["query"], kind=case["kind"], chunks=chunks,
                         response=response, evaluation=evaluate(case, chunks, response)))
    return dict(version=VERSION, config=config, mode="extractive", corpus_digest=digest(DOCUMENTS), rows=rows,
                passed=sum(r["evaluation"]["passed"] for r in rows), total=len(rows))


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run the exported synthetic RAG teaching benchmark")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()
    print(json.dumps(run(json.loads(Path(args.config).read_text(encoding="utf-8"))), ensure_ascii=False, indent=2))
