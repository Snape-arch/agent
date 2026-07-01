from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import wave
from pathlib import Path
from typing import Any

from .artifact_storage import ArtifactStorage, safe_artifact_slug
from .runtime_records import RunRecord
from .workflow_engine import WorkflowEngine


SUPPORTED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}


def default_asr_model_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base).expanduser() / "ClawOS" / "asr_models"


class MeetingAudioService:
    """Local meeting-audio pipeline with optional ASR engines and deterministic fallback."""

    def __init__(self, store: Any, artifact_root: str | Path):
        self.store = store
        self.artifacts = ArtifactStorage(artifact_root)
        self.workflow_engine = WorkflowEngine()

    def process(
        self,
        *,
        audio_path: str | Path,
        transcript: str = "",
        transcript_path: str | Path = "",
        title: str = "",
        meeting_id: int | None = None,
        extract_items=None,
        summarize=None,
    ) -> dict[str, Any]:
        audio = Path(audio_path).expanduser().resolve()
        if audio.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES or not audio.is_file():
            raise ValueError("a readable local audio file is required")
        started = time.perf_counter()
        segments = self.detect_voice_segments(audio)
        transcript_text, transcript_meta = self.transcribe(audio, transcript=transcript, transcript_path=transcript_path)
        transcript_meta["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        transcript_status = self._transcript_status(transcript_text, transcript_meta)
        diarization = self.diarize(transcript_text, segments)
        decisions, risks, actions = extract_items(transcript_text) if extract_items else ([], [], [])
        summary = summarize(transcript_text) if summarize else self.simple_summary(transcript_text)
        meeting_card = self.build_meeting_card(
            title=title or audio.stem,
            summary=summary,
            decisions=decisions,
            risks=risks,
            actions=actions,
            diarization=diarization,
            transcript_status=transcript_status,
            engine=transcript_meta["engine"],
        )
        slug = safe_artifact_slug(title or audio.stem)
        card_artifact = self.artifacts.write_markdown(
            f"{slug}/meeting_card.md",
            f"{title or audio.stem} Meeting Card",
            [
                ("Summary", meeting_card["summary"] or "No summary"),
                ("Decisions", meeting_card["decisions"]),
                ("Action Items", [
                    f"{item.get('owner') or 'unassigned'} | {item.get('description')} | {item.get('due_date') or 'no due date'}"
                    for item in meeting_card["actions"]
                ]),
                ("Risks", meeting_card["risks"]),
                ("Speaker Turns", [f"{turn.get('speaker')}: {turn.get('text')}" for turn in diarization[:24]]),
            ],
        )
        transcript_artifact = self.artifacts.write_json(
            f"{slug}/transcript.json",
            {
                "audio_path": str(audio),
                "transcript": transcript_text,
                "segments": segments,
                "diarization": diarization,
                "transcription": transcript_meta,
            },
        )
        workflow = self.workflow_engine.gate_rework_until_done(
            workflow_id=f"meeting-audio-{safe_artifact_slug(str(meeting_id or slug))}",
            name="meeting_audio_to_card",
            gate_statuses=[{
                "name": "transcript_available",
                "status": "pass" if transcript_text.strip() else "blocked",
                "score": 100 if transcript_text.strip() else 0,
                "failures": [] if transcript_text.strip() else ["No local ASR engine or transcript was available."],
            }],
            artifact_saves=[card_artifact, transcript_artifact],
        )
        run = RunRecord(
            run_id=f"meeting-audio-{safe_artifact_slug(str(meeting_id or slug))}",
            run_type="meeting_audio",
            title=title or audio.stem,
            status="pass" if transcript_text.strip() else "blocked",
            actor="meeting-audio-service",
            scenario="meeting",
            inputs={"audio_path": str(audio), "transcript_path": str(transcript_path or "")},
            outputs={"meeting_card": meeting_card, "transcription": transcript_meta},
            metrics={
                "voice_segment_count": len(segments),
                "speaker_count": len({turn.get("speaker") for turn in diarization if turn.get("speaker")}),
                "transcript_chars": len(transcript_text),
                "latency_ms": transcript_meta.get("latency_ms", 0),
            },
            workflow={"state_machine": workflow},
            tags=["meeting", "audio", "asr", transcript_meta["engine"]],
        )
        run.add_artifact("meeting_card", "Structured meeting card", card_artifact["path"], storage=card_artifact)
        run.add_artifact("transcript_json", "Transcript and diarization JSON", transcript_artifact["path"], storage=transcript_artifact)
        run.add_evidence("meeting_audio", summary or title or audio.stem, citation=card_artifact["path"], score=1.0 if transcript_text.strip() else 0.0)
        if not transcript_text.strip():
            run.add_failure_case(
                "meeting_audio_transcription_unavailable",
                "No transcript text and no local faster-whisper/whisper.cpp/whisper CLI engine was available.",
                severity="high",
                input_summary=str(audio),
                remediation="Install faster-whisper or whisper.cpp, or provide a sidecar transcript.",
            )
        run_record = self.store.save_run_record(run.to_dict()) if self.store else run.to_dict()
        knowledge_item = None
        if transcript_text.strip() and self.store:
            knowledge_item = self.store.add_knowledge(
                title=f"{title or audio.stem} meeting card",
                content=json.dumps(meeting_card, ensure_ascii=False, indent=2),
                category="meeting",
                source=card_artifact["path"],
                tags=["meeting", "audio", "artifact", "evidence"],
                confidence=0.84,
            )
        return {
            "transcript": transcript_text,
            "transcript_status": transcript_status,
            "transcription": transcript_meta,
            "segments": segments,
            "diarization": diarization,
            "meeting_card": meeting_card,
            "artifacts": {"meeting_card": card_artifact, "transcript": transcript_artifact},
            "run_record": run_record,
            "knowledge_item": knowledge_item,
        }

    def transcribe(self, audio: Path, *, transcript: str = "", transcript_path: str | Path = "") -> tuple[str, dict[str, Any]]:
        if transcript:
            return str(transcript), {"engine": "provided_transcript", "available": True}
        if transcript_path:
            path = Path(transcript_path).expanduser().resolve()
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="replace"), {"engine": "sidecar_transcript", "available": True, "path": str(path)}
        faster = self._transcribe_faster_whisper(audio)
        if faster[0]:
            return faster
        cli = self._transcribe_whisper_cli(audio)
        if cli[0]:
            return cli
        return "", {"engine": "none", "available": False, "attempted": ["faster-whisper", "whisper.cpp", "whisper"]}

    @staticmethod
    def _transcript_status(transcript_text: str, transcript_meta: dict[str, Any]) -> str:
        if not str(transcript_text or "").strip():
            return "audio_registered_requires_transcription"
        if transcript_meta.get("engine") in {"provided_transcript", "sidecar_transcript"}:
            return "transcript_imported"
        return "transcribed"

    def _transcribe_faster_whisper(self, audio: Path) -> tuple[str, dict[str, Any]]:
        try:
            from faster_whisper import WhisperModel
        except Exception:
            return "", {"engine": "faster-whisper", "available": False}
        model_name = os.environ.get("CLAWOS_ASR_MODEL", "small").strip() or "small"
        cache_dir = os.environ.get("CLAWOS_ASR_MODEL_DIR", str(default_asr_model_dir())).strip()
        model_kwargs = {
            "device": os.environ.get("CLAWOS_ASR_DEVICE", "cpu").strip() or "cpu",
            "compute_type": os.environ.get("CLAWOS_ASR_COMPUTE_TYPE", "int8").strip() or "int8",
        }
        if cache_dir:
            Path(cache_dir).expanduser().mkdir(parents=True, exist_ok=True)
            model_kwargs["download_root"] = str(Path(cache_dir).expanduser().resolve())
        try:
            model = WhisperModel(model_name, **model_kwargs)
            segments, info = model.transcribe(str(audio), vad_filter=True)
            lines = self._format_asr_segments(segments)
            vad_retry = False
            if not "\n".join(lines).strip():
                segments, info = model.transcribe(str(audio), vad_filter=False)
                lines = self._format_asr_segments(segments)
                vad_retry = True
            return "\n".join(lines), {
                "engine": "faster-whisper",
                "available": True,
                "model": model_name,
                "language": getattr(info, "language", ""),
                "device": model_kwargs["device"],
                "compute_type": model_kwargs["compute_type"],
                "model_cache": str(Path(cache_dir).expanduser().resolve()) if cache_dir else "",
                "vad_retry_without_filter": vad_retry,
            }
        except Exception as exc:
            return "", {"engine": "faster-whisper", "available": True, "model": model_name, "error": str(exc)[:300]}

    @staticmethod
    def _format_asr_segments(segments: Any) -> list[str]:
        lines = []
        for index, segment in enumerate(segments, 1):
            text = str(getattr(segment, "text", "") or "").strip()
            if text:
                lines.append(f"[{segment.start:.2f}-{segment.end:.2f}] Speaker {((index - 1) % 2) + 1}: {text}")
        return lines

    def _transcribe_whisper_cli(self, audio: Path) -> tuple[str, dict[str, Any]]:
        candidates = [
            shutil.which("whisper-cli"),
            shutil.which("whisper"),
            shutil.which("main"),
        ]
        binary = next((item for item in candidates if item), "")
        if not binary:
            return "", {"engine": "whisper.cpp", "available": False}
        try:
            if Path(binary).name.lower().startswith("whisper"):
                proc = subprocess.run([binary, str(audio), "--output_format", "txt"], capture_output=True, text=True, timeout=180)
            else:
                proc = subprocess.run([binary, "-f", str(audio), "-otxt"], capture_output=True, text=True, timeout=180)
            text = (proc.stdout or "").strip()
            if proc.returncode != 0:
                return "", {"engine": "whisper_cli", "available": True, "binary": binary, "error": (proc.stderr or "")[:300]}
            return text, {"engine": "whisper_cli", "available": True, "binary": binary}
        except Exception as exc:
            return "", {"engine": "whisper_cli", "available": True, "binary": binary, "error": str(exc)[:300]}

    def detect_voice_segments(self, audio: Path, *, silence_threshold: int = 500, min_voice_ms: int = 250) -> list[dict[str, Any]]:
        if audio.suffix.lower() != ".wav":
            return [{"start": 0.0, "end": 0.0, "kind": "unknown_format", "source": audio.suffix.lower()}]
        try:
            with wave.open(str(audio), "rb") as handle:
                channels = handle.getnchannels()
                width = handle.getsampwidth()
                rate = handle.getframerate()
                frames = handle.readframes(handle.getnframes())
            if width != 2 or rate <= 0:
                return [{"start": 0.0, "end": 0.0, "kind": "unsupported_wav", "sample_width": width, "sample_rate": rate}]
            samples = []
            step = max(1, channels)
            for index in range(0, len(frames), 2 * step):
                sample = int.from_bytes(frames[index:index + 2], "little", signed=True)
                samples.append(abs(sample))
            window = max(1, int(rate * 0.1))
            min_windows = max(1, int(min_voice_ms / 100))
            segments, active_start, active_windows = [], None, 0
            for offset in range(0, len(samples), window):
                chunk = samples[offset:offset + window]
                energy = sum(chunk) / max(1, len(chunk))
                is_voice = energy >= silence_threshold
                t = offset / rate
                if is_voice and active_start is None:
                    active_start = t
                    active_windows = 1
                elif is_voice:
                    active_windows += 1
                elif active_start is not None:
                    end = offset / rate
                    if active_windows >= min_windows:
                        segments.append({"start": round(active_start, 2), "end": round(end, 2), "kind": "voice"})
                    active_start = None
                    active_windows = 0
            if active_start is not None:
                segments.append({"start": round(active_start, 2), "end": round(len(samples) / rate, 2), "kind": "voice"})
            return segments or [{"start": 0.0, "end": round(len(samples) / rate, 2), "kind": "silence_or_low_energy"}]
        except Exception as exc:
            return [{"start": 0.0, "end": 0.0, "kind": "vad_error", "error": str(exc)[:120]}]

    def diarize(self, transcript: str, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        turns = []
        pattern = re.compile(r"^(?:\[(?P<time>[^\]]+)\]\s*)?(?P<speaker>[^:\n：]{1,40})[:：]\s*(?P<text>.+)$")
        for line in str(transcript or "").splitlines():
            match = pattern.match(line.strip())
            if match:
                speaker = match.group("speaker").strip()
                if speaker.lower() not in {"decision", "risk", "action"} and speaker not in {"决定", "风险", "行动项", "待办"}:
                    turns.append({"time": match.group("time") or "", "speaker": speaker, "text": match.group("text").strip(), "method": "label"})
        if turns:
            return turns
        sentences = [item.strip() for item in re.split(r"(?<=[。！？.!?])\s+|[\r\n]+", str(transcript or "")) if item.strip()]
        for index, text in enumerate(sentences):
            segment = segments[index] if index < len(segments) else {}
            turns.append({
                "time": f"{segment.get('start', '')}-{segment.get('end', '')}".strip("-"),
                "speaker": f"Speaker {index % 2 + 1}",
                "text": text,
                "method": "heuristic_segment_alternation",
            })
        return turns

    @staticmethod
    def simple_summary(transcript: str) -> str:
        for line in str(transcript or "").splitlines():
            cleaned = re.sub(r"^(?:[^:：]{1,40}[:：]\s*)", "", line).strip()
            if cleaned:
                return cleaned[:240]
        return ""

    @staticmethod
    def build_meeting_card(title, summary, decisions, risks, actions, diarization, transcript_status, engine) -> dict[str, Any]:
        return {
            "title": title,
            "summary": summary,
            "decisions": decisions,
            "actions": actions,
            "risks": risks,
            "owners": sorted({item.get("owner") for item in actions if item.get("owner")}),
            "due_dates": sorted({item.get("due_date") for item in actions if item.get("due_date")}),
            "speaker_count": len({turn.get("speaker") for turn in diarization if turn.get("speaker")}),
            "transcript_status": transcript_status,
            "transcription_engine": engine,
        }
