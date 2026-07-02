#!/usr/bin/env python3
"""Run reproducible local ASR acceptance with generated meeting speech.

This suite uses Windows SAPI to synthesize short meeting clips, then runs the
normal ClawOS meeting-audio pipeline without sidecar transcripts. It records
WER, latency, action-item hit rate, artifacts, and durable run ids.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import struct
import subprocess
import sys
import tempfile
import time
import wave
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
        "noise_profile": "clean",
    },
    {
        "name": "research_sync",
        "text": "Bob says decision save the research summary to knowledge base. Action Bob verify citations by Monday. Risk citations may be incomplete.",
        "action_terms": ["bob", "verify", "citations", "monday"],
        "noise_profile": "clean",
    },
    {
        "name": "office_report",
        "text": "Carol says decision generate the office report. Action Carol export the meeting card by Tuesday. Risk report layout needs review.",
        "action_terms": ["carol", "export", "meeting", "tuesday"],
        "noise_profile": "clean",
    },
    {
        "name": "competition_delivery",
        "text": "David says decision prepare the competition runbook. Action David check offline reproducibility by Wednesday. Risk hardware validation is pending.",
        "action_terms": ["david", "offline", "reproducibility", "wednesday"],
        "noise_profile": "clean",
    },
    {
        "name": "bilingual_ai_plan",
        "text": "Emma says decision keep AI learning basics and frontier topics. Action Emma update the AI curriculum by Thursday. Risk English Chinese mixed terms confuse transcription.",
        "action_terms": ["emma", "curriculum", "thursday", "transcription"],
        "noise_profile": "clean",
    },
    {
        "name": "interruption_review",
        "text": "Frank says decision review interruptions separately. Action Frank mark speaker turns by Friday. Risk overlapping speakers reduce accuracy.",
        "action_terms": ["frank", "speaker", "turns", "friday"],
        "noise_profile": "clean",
    },
    {
        "name": "noisy_room_review",
        "text": "Grace says decision keep the noisy room sample. Action Grace label action items by Monday. Risk background noise may hide owners.",
        "action_terms": ["grace", "label", "action", "monday"],
        "noise_profile": "background_noise",
        "volume": 92,
    },
    {
        "name": "long_quarterly_review",
        "text": "Helen says decision split the long meeting into chapters. Action Helen publish the quarterly summary by next Wednesday. Risk long audio increases latency.",
        "action_terms": ["helen", "quarterly", "summary", "wednesday"],
        "noise_profile": "clean",
        "repeat": 3,
    },
    {
        "name": "overlap_interruptions",
        "text": "Iris says decision record interruptions separately. Action Iris compare speaker turns by Friday. Risk overlapping speakers reduce accuracy.",
        "action_terms": ["iris", "speaker", "turns", "friday"],
        "noise_profile": "overlap",
    },
    {
        "name": "remote_sync_echo",
        "text": "Jack says decision accept the remote sync plan. Action Jack remove duplicate notes by Tuesday. Risk echo may duplicate words.",
        "action_terms": ["jack", "duplicate", "notes", "tuesday"],
        "noise_profile": "echo",
    },
    {
        "name": "fast_standup",
        "text": "Kelly says decision shorten standup updates. Action Kelly send blockers by noon. Risk fast speech misses deadlines.",
        "action_terms": ["kelly", "blockers", "noon", "deadlines"],
        "noise_profile": "clean",
        "rate": 2,
    },
    {
        "name": "quiet_speaker",
        "text": "Leo says decision capture quiet speakers. Action Leo confirm owners by Thursday. Risk low volume reduces recall.",
        "action_terms": ["leo", "owners", "thursday", "volume"],
        "noise_profile": "background_noise",
        "volume": 68,
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


def _apply_audio_profile(output: Path, profile: str) -> None:
    profile = str(profile or "clean")
    if profile == "clean":
        return
    try:
        with wave.open(str(output), "rb") as reader:
            params = reader.getparams()
            frames = reader.readframes(reader.getnframes())
        if params.sampwidth != 2:
            return
        samples = list(struct.unpack("<" + "h" * (len(frames) // 2), frames))
        random.seed(profile)
        delay = int(params.framerate * 0.12) * max(1, params.nchannels)
        adjusted = []
        for idx, sample in enumerate(samples):
            value = sample
            if profile == "background_noise":
                value += int(520 * math.sin(idx / 17.0)) + random.randint(-320, 320)
            elif profile == "overlap":
                value += int(1200 * math.sin(idx / 9.0))
            elif profile == "echo" and idx >= delay:
                value += int(samples[idx - delay] * 0.28)
            adjusted.append(max(-32768, min(32767, int(value))))
        with wave.open(str(output), "wb") as writer:
            writer.setparams(params)
            writer.writeframes(struct.pack("<" + "h" * len(adjusted), *adjusted))
    except Exception:
        return


def synthesize_wav(text: str, output: Path, *, rate: int = 0, volume: int = 100, repeat: int = 1, noise_profile: str = "clean") -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    spoken_text = " ".join([text] * max(1, int(repeat or 1)))
    script = f"""
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = {int(rate)}
$synth.Volume = {max(1, min(100, int(volume)))}
$synth.SetOutputToWaveFile('{str(output).replace("'", "''")}')
$synth.Speak('{spoken_text.replace("'", "''")}')
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
    _apply_audio_profile(output, noise_profile)


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
        synthesize_wav(
            case["text"],
            audio,
            rate=int(case.get("rate", 0)),
            volume=int(case.get("volume", 100)),
            repeat=int(case.get("repeat", 1)),
            noise_profile=str(case.get("noise_profile", "clean")),
        )
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
            "noise_profile": case.get("noise_profile", "clean"),
            "duration_profile": {
                "repeat": int(case.get("repeat", 1)),
                "rate": int(case.get("rate", 0)),
                "volume": int(case.get("volume", 100)),
            },
            "audio_path": str(audio),
            "meeting_card_path": item.get("artifacts", {}).get("meeting_card", {}).get("path", ""),
            "run_id": item.get("run_record", {}).get("run_id", ""),
            "transcript_excerpt": transcript[:500],
            "failure_reason": "" if transcript.strip() else "asr_transcript_empty",
        })
    latencies = sorted(item["latency_ms"] for item in results)
    by_profile = {}
    for item in results:
        bucket = by_profile.setdefault(item["noise_profile"], {"case_count": 0, "passed_count": 0, "average_wer": 0.0, "average_action_hit_rate": 0.0})
        bucket["case_count"] += 1
        bucket["passed_count"] += 1 if item["pass"] else 0
        bucket["average_wer"] += item["wer"]
        bucket["average_action_hit_rate"] += item["action_hit_rate"]
    for bucket in by_profile.values():
        count = max(1, bucket["case_count"])
        bucket["average_wer"] = round(bucket["average_wer"] / count, 4)
        bucket["average_action_hit_rate"] = round(bucket["average_action_hit_rate"] / count, 4)
        bucket["pass_rate"] = round(bucket["passed_count"] / count, 4)
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
        "by_profile": by_profile,
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
