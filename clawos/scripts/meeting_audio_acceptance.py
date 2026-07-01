#!/usr/bin/env python3
"""Offline meeting-audio acceptance suite for local ASR/VAD/diarization workflow."""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import tempfile
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
        "name": "two_speaker_clean_sync",
        "kind": "clean",
        "transcript": "Alice: Decision: Ship local ASR path\nBob: Risk: model may be missing\nAction: Alice | prepare notes | 2026-07-02",
    },
    {
        "name": "noisy_room_sidecar",
        "kind": "noisy",
        "transcript": "Speaker 1: Decision: Use sidecar transcript when noise is high\nSpeaker 2: Risk: background noise lowers confidence\nAction: Speaker 2 | collect samples | 2026-07-03",
    },
    {
        "name": "long_meeting_vad_chunks",
        "kind": "long",
        "transcript": "Lead: Decision: Split long audio with VAD\nEngineer: Risk: long audio can timeout\nAction: Engineer | verify chunking | 2026-07-04",
    },
    {
        "name": "bilingual_cn_en",
        "kind": "bilingual",
        "transcript": "Alice: Decision: 保留 bilingual summary\nBob: Risk: English and 中文 mixed terms may confuse ASR\nAction: Bob | update glossary | 2026-07-05",
    },
    {
        "name": "overlap_interruption",
        "kind": "overlap",
        "transcript": "Alice: Decision: mark interruptions in notes\nBob: Risk: 多人打断会影响 speaker attribution\nAction: Alice | review diarization | 2026-07-06",
    },
    {
        "name": "silence_then_voice",
        "kind": "silence",
        "transcript": "Host: Decision: ignore leading silence\nGuest: Risk: silence can waste compute\nAction: Host | trim audio | 2026-07-07",
    },
]


def write_wav(path: Path, kind: str) -> None:
    rate = 16000
    if kind == "long":
        pattern = [(0.35, 0), (0.55, 9000), (0.25, 0), (0.55, 7000)] * 4
    elif kind == "silence":
        pattern = [(1.0, 0), (0.7, 9000)]
    elif kind == "noisy":
        pattern = [(0.2, 900), (0.6, 8000), (0.2, 1200), (0.6, 7000)]
    else:
        pattern = [(0.2, 0), (0.6, 8000), (0.2, 0), (0.55, 6000)]
    samples = []
    phase = 0.0
    for duration, amplitude in pattern:
        count = int(rate * duration)
        for i in range(count):
            if amplitude <= 0:
                value = 0
            else:
                value = int(amplitude * math.sin(phase))
                phase += 2 * math.pi * 440 / rate
            samples.append(value)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))


def run_suite(out: Path | None = None) -> dict:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        store = MemoryStore(str(root / "memory.db"))
        services = WorkspaceServices(store, ToolSecurityPolicy([root]))
        results = []
        for case in CASES:
            audio = root / f"{case['name']}.wav"
            transcript = root / f"{case['name']}.txt"
            write_wav(audio, case["kind"])
            transcript.write_text(case["transcript"], encoding="utf-8")
            item = services.import_meeting_audio(
                audio,
                transcript_path=transcript,
                title=case["name"],
                output_dir=root / "artifacts",
            )
            card = item["meeting_card"]
            passed = (
                item["transcript_status"] in {"transcribed", "transcript_imported"}
                and bool(item["diarization"])
                and bool(card["decisions"])
                and bool(card["actions"])
                and bool(item["knowledge_item"])
                and bool(store.get_run_record(item["run_record"]["run_id"]))
            )
            results.append({
                "name": case["name"],
                "pass": passed,
                "speaker_count": card["speaker_count"],
                "voice_segment_count": len(item["segments"]),
                "engine": item["transcription"]["engine"],
                "run_id": item["run_record"]["run_id"],
                "failure_reason": "" if passed else "meeting_audio_pipeline_incomplete",
            })
        report = {
            "name": "meeting-audio-acceptance-v1",
            "case_count": len(results),
            "passed_count": sum(1 for item in results if item["pass"]),
            "failed_count": sum(1 for item in results if not item["pass"]),
            "pass_rate": round(sum(1 for item in results if item["pass"]) / max(1, len(results)), 4),
            "cases": results,
        }
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    report = run_suite(Path(args.out) if args.out else None)
    print(
        "Meeting audio acceptance: "
        f"{report['passed_count']}/{report['case_count']} passed "
        f"pass_rate={report['pass_rate']}"
    )
    return 0 if report["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
