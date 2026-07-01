#!/usr/bin/env python3
"""Run reproducible local ASR acceptance with generated meeting speech.

This suite uses Windows SAPI to synthesize short meeting clips, then runs the
normal ClawOS meeting-audio pipeline without sidecar transcripts. It records
WER, latency, action-item hit rate, artifacts, and durable run ids.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryos.memory_store import MemoryStore
from security.policy import ToolSecurityPolicy
from workspace_services import WorkspaceServices


CASES = [
    {
        "name": "demo_planning",
        "text": "Alice says decision use local ASR small model. Action Alice prepare demo notes by Friday. Risk model download may be slow.",
        "action_terms": ["alice", "prepare", "demo", "friday"],
    },
    {
        "name": "research_sync",
        "text": "Bob says decision save the research summary to knowledge base. Action Bob verify citations by Monday. Risk citations may be incomplete.",
        "action_terms": ["bob", "verify", "citations", "monday"],
    },
    {
        "name": "office_report",
        "text": "Carol says decision generate the office report. Action Carol export the meeting card by Tuesday. Risk report layout needs review.",
        "action_terms": ["carol", "export", "meeting", "tuesday"],
    },
    {
        "name": "competition_delivery",
        "text": "David says decision prepare the competition runbook. Action David check offline reproducibility by Wednesday. Risk hardware validation is pending.",
        "action_terms": ["david", "offline", "reproducibility", "wednesday"],
    },
    {
        "name": "bilingual_ai_plan",
        "text": "Emma says decision keep AI learning basics and frontier topics. Action Emma update the AI curriculum by Thursday. Risk English Chinese mixed terms confuse transcription.",
        "action_terms": ["emma", "curriculum", "thursday", "transcription"],
    },
    {
        "name": "interruption_review",
        "text": "Frank says decision review interruptions separately. Action Frank mark speaker turns by Friday. Risk overlapping speakers reduce accuracy.",
        "action_terms": ["frank", "speaker", "turns", "friday"],
    },
]


def default_model_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base).expanduser() / "ClawOS" / "asr_models"


def normalize_words(text: str) -> list[str]:
    text = re.sub(r"\[[0-9:. -]+\]\s*", " ", str(text or ""))
    text = re.sub(r"\bspeaker\s+\d+\s*:\s*", " ", text, flags=re.I)
    return re.findall(r"[a-z0-9]+", text.lower())


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref = normalize_words(reference)
    hyp = normalize_words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    previous = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, 1):
        current = [i]
        for j, hyp_word in enumerate(hyp, 1):
            cost = 0 if ref_word == hyp_word else 1
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + cost,
            ))
        previous = current
    return round(previous[-1] / max(1, len(ref)), 4)


def synthesize_wav(text: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    script = f"""
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = 0
$synth.Volume = 100
$synth.SetOutputToWaveFile('{str(output).replace("'", "''")}')
$synth.Speak('{text.replace("'", "''")}')
$synth.Dispose()
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if not output.exists() or output.stat().st_size <= 44:
        raise RuntimeError(f"failed to synthesize speech: {output}")


def run_suite(out: Path, keep_audio: bool = True) -> dict:
    os.environ.setdefault("CLAWOS_ASR_MODEL", "small")
    os.environ.setdefault("CLAWOS_ASR_MODEL_DIR", str(default_model_dir().resolve()))
    out.mkdir(parents=True, exist_ok=True)
    work_root = out / "audio" if keep_audio else Path(tempfile.mkdtemp(prefix="clawos_asr_eval_"))
    work_root.mkdir(parents=True, exist_ok=True)
    store = MemoryStore(str(out / "meeting_audio_real_asr.db"))
    services = WorkspaceServices(store, ToolSecurityPolicy([work_root, out, ROOT]))
    results = []
    for case in CASES:
        audio = work_root / f"{case['name']}.wav"
        synthesize_wav(case["text"], audio)
        started = time.perf_counter()
        item = services.import_meeting_audio(
            audio,
            title=f"Real ASR {case['name']}",
            output_dir=out / "artifacts",
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        transcript = item.get("transcript", "")
        terms = case["action_terms"]
        action_hits = sum(1 for term in terms if term.lower() in transcript.lower())
        action_hit_rate = round(action_hits / max(1, len(terms)), 4)
        wer = word_error_rate(case["text"], transcript)
        results.append({
            "name": case["name"],
            "pass": item.get("transcript_status") == "transcribed" and bool(transcript.strip()),
            "wer": wer,
            "latency_ms": elapsed_ms,
            "action_hit_rate": action_hit_rate,
            "transcription_engine": item.get("transcription", {}).get("engine"),
            "model": item.get("transcription", {}).get("model"),
            "language": item.get("transcription", {}).get("language"),
            "audio_path": str(audio),
            "meeting_card_path": item.get("artifacts", {}).get("meeting_card", {}).get("path", ""),
            "run_id": item.get("run_record", {}).get("run_id", ""),
            "transcript_excerpt": transcript[:500],
            "failure_reason": "" if transcript.strip() else "asr_transcript_empty",
        })
    latencies = sorted(item["latency_ms"] for item in results)
    report = {
        "name": "meeting-audio-real-asr-small",
        "asr_model": os.environ.get("CLAWOS_ASR_MODEL", "small"),
        "model_dir": os.environ.get("CLAWOS_ASR_MODEL_DIR", ""),
        "case_count": len(results),
        "passed_count": sum(1 for item in results if item["pass"]),
        "failed_count": sum(1 for item in results if not item["pass"]),
        "metrics": {
            "average_wer": round(sum(item["wer"] for item in results) / max(1, len(results)), 4),
            "average_action_hit_rate": round(sum(item["action_hit_rate"] for item in results) / max(1, len(results)), 4),
            "latency_p50_ms": latencies[len(latencies) // 2] if latencies else 0,
            "latency_p95_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else 0,
        },
        "cases": results,
    }
    report_path = out / "meeting_audio_real_asr_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="output/asr_real_eval")
    parser.add_argument("--no-keep-audio", action="store_true")
    args = parser.parse_args()
    report = run_suite(Path(args.out), keep_audio=not args.no_keep_audio)
    print(
        "Meeting real ASR: "
        f"{report['passed_count']}/{report['case_count']} transcribed "
        f"avg_wer={report['metrics']['average_wer']} "
        f"action_hit={report['metrics']['average_action_hit_rate']} "
        f"p95={report['metrics']['latency_p95_ms']}ms "
        f"report={report['report_path']}"
    )
    return 0 if report["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
