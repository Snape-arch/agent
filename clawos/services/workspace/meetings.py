"""Meetings workflows and their domain dependencies."""
from __future__ import annotations
import json
import re
import shutil
from datetime import datetime, timezone
from services.meeting_audio_service import MeetingAudioService
from services.workspace.shared import WorkspaceValues


class MeetingsWorkspace:
    """Workspace meetings responsibilities."""

    def __init__(self, store, security):
        self.store = store
        self.security = security

    def create_meeting(self, title, meeting_date="", attendees=None, agenda=None):
        with self.store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO meetings (title, meeting_date, attendees, agenda)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(title), str(meeting_date or ""),
                    json.dumps(attendees or [], ensure_ascii=False),
                    json.dumps(agenda or [], ensure_ascii=False),
                ),
            )
            return self.get_meeting(int(cursor.lastrowid), conn=c)


    def process_meeting_transcript(self, meeting_id, transcript, publish_memory=True):
        decisions, risks, actions = self._extract_meeting_items(transcript)
        summary = WorkspaceValues._summarize_text(transcript)
        with self.store._conn() as c:
            c.execute(
                """
                UPDATE meetings
                SET transcript=?, summary=?, decisions=?, risks=?,
                    status='completed', updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    str(transcript), summary,
                    json.dumps(decisions, ensure_ascii=False),
                    json.dumps(risks, ensure_ascii=False),
                    int(meeting_id),
                ),
            )
            c.execute("DELETE FROM meeting_actions WHERE meeting_id=?", (int(meeting_id),))
            for action in actions:
                c.execute(
                    """
                    INSERT INTO meeting_actions
                        (meeting_id, description, owner, due_date, evidence)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        int(meeting_id), action["description"], action["owner"],
                        action["due_date"], action["evidence"],
                    ),
                )
            meeting = self.get_meeting(meeting_id, conn=c)
        if publish_memory:
            self.store.upsert_memory(
                "experience",
                f"meeting:{meeting_id}",
                summary or meeting["title"],
                category="meeting",
                source="meeting_workflow",
                confidence=0.8,
                evidence=[{
                    "evidence_type": "meeting_transcript",
                    "source_ref": f"meeting:{meeting_id}",
                    "excerpt": transcript[:1000],
                }],
            )
        return meeting


    def get_meeting(self, meeting_id, conn=None):
        def fetch(c):
            row = c.execute("SELECT * FROM meetings WHERE id=?", (int(meeting_id),)).fetchone()
            if not row:
                return None
            item = dict(row)
            for key in ("attendees", "agenda", "decisions", "risks"):
                item[key] = json.loads(item.get(key) or "[]")
            actions = c.execute(
                "SELECT * FROM meeting_actions WHERE meeting_id=? ORDER BY id",
                (int(meeting_id),),
            ).fetchall()
            audio = c.execute(
                "SELECT * FROM meeting_audio_assets WHERE meeting_id=? ORDER BY id",
                (int(meeting_id),),
            ).fetchall()
            drafts = c.execute(
                "SELECT * FROM meeting_connector_drafts WHERE meeting_id=? ORDER BY id",
                (int(meeting_id),),
            ).fetchall()
            item["actions"] = [dict(action) for action in actions]
            item["audio_assets"] = [WorkspaceValues._decode_record(row, ("diarization", "metadata")) for row in audio]
            item["connector_drafts"] = [WorkspaceValues._decode_record(row, ("metadata",)) for row in drafts]
            return item
        if conn is not None:
            return fetch(conn)
        with self.store._conn() as c:
            return fetch(c)


    @staticmethod
    def _extract_meeting_items(transcript):
        decisions, risks, actions = [], [], []
        for raw in str(transcript or "").splitlines():
            line = raw.strip(" -*\t")
            if not line:
                continue
            speaker_line = re.match(r"^(?:\[[^\]]+\]\s*)?[^:：]{1,40}[:：]\s*(.+)$", line)
            if speaker_line:
                inner = speaker_line.group(1).strip()
                if re.match(r"^(decision|risk|action|决定|决议|风险|行动项|待办)\s*[:：]", inner, re.I):
                    line = inner
            lower = line.lower()
            if re.match(r"^(decision|决定|决议)\s*[:：]", lower):
                decisions.append(re.split(r"[:：]", line, maxsplit=1)[1].strip())
            elif re.match(r"^(risk|风险)\s*[:：]", lower):
                risks.append(re.split(r"[:：]", line, maxsplit=1)[1].strip())
            elif re.match(r"^(action|行动项|待办)\s*[:：]", lower):
                content = re.split(r"[:：]", line, maxsplit=1)[1].strip()
                parts = [part.strip() for part in re.split(r"\s*\|\s*", content)]
                actions.append({
                    "description": parts[1] if len(parts) > 1 else parts[0],
                    "owner": parts[0] if len(parts) > 1 else "",
                    "due_date": parts[2] if len(parts) > 2 else "",
                    "evidence": line,
                })
        return decisions, risks, actions


    def import_meeting_audio(self, audio_path, transcript_path="", transcript="", title="", meeting_id=None, output_dir=""):
        audio = self.security.resolve_path(audio_path)
        if audio.suffix.lower() not in {".wav", ".mp3", ".m4a", ".flac", ".ogg"} or not audio.is_file():
            raise ValueError("a readable local audio file is required")
        if transcript_path:
            path = self.security.resolve_path(transcript_path)
            if path.suffix.lower() not in {".txt", ".md", ".srt", ".vtt"} or not path.is_file():
                raise ValueError("transcript_path must point to a readable text transcript")
            transcript_file = str(path)
        else:
            transcript_file = ""
        if meeting_id:
            meeting = self.get_meeting(meeting_id)
            if not meeting:
                raise ValueError("meeting not found")
        else:
            meeting = self.create_meeting(title or audio.stem)
        artifact_root = self.security.resolve_path(output_dir) if output_dir else audio.parent / "clawos_meeting_artifacts"
        audio_result = MeetingAudioService(self.store, artifact_root).process(
            audio_path=audio,
            transcript=transcript,
            transcript_path=transcript_path,
            title=title or audio.stem,
            meeting_id=int(meeting["id"]),
            extract_items=self._extract_meeting_items,
            summarize=WorkspaceValues._summarize_text,
        )
        transcript_text = audio_result["transcript"]
        diarization = audio_result["diarization"]
        status = audio_result["transcript_status"]
        with self.store._conn() as c:
            c.execute(
                """
                INSERT INTO meeting_audio_assets
                    (meeting_id, audio_path, transcript_path, transcript_status, diarization, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(meeting["id"]), str(audio), transcript_file, status,
                    json.dumps(diarization, ensure_ascii=False),
                    json.dumps({
                        "size_bytes": audio.stat().st_size,
                        "speaker_count": len({turn["speaker"] for turn in diarization}),
                        "transcription_engine": audio_result["transcription"]["engine"],
                        "voice_segment_count": len(audio_result["segments"]),
                        "meeting_card": audio_result["artifacts"]["meeting_card"]["path"],
                        "run_id": audio_result["run_record"]["run_id"],
                    }, ensure_ascii=False),
                ),
            )
        if transcript_text.strip():
            meeting = self.process_meeting_transcript(meeting["id"], transcript_text, publish_memory=False)
            with self.store._conn() as c:
                c.execute("UPDATE meetings SET status='needs_review' WHERE id=?", (meeting["id"],))
        return {
            "meeting": self.get_meeting(meeting["id"]),
            "audio_path": str(audio),
            "transcript_status": status,
            "transcript": transcript_text,
            "transcription": audio_result["transcription"],
            "segments": audio_result["segments"],
            "diarization": diarization,
            "meeting_card": audio_result["meeting_card"],
            "artifacts": audio_result["artifacts"],
            "run_record": audio_result["run_record"],
            "knowledge_item": audio_result["knowledge_item"],
            "capabilities": {
                "audio_registered": True,
                "sidecar_transcript_supported": True,
                "vad_silence_splitting": True,
                "speaker_separation": "label_or_heuristic",
                "local_whisper": shutil.which("whisper") is not None or shutil.which("whisper-cli") is not None,
            },
        }


    def draft_meeting_connectors(self, meeting_id, output_dir, calendar=True, email=True, recipients=None):
        meeting = self.get_meeting(meeting_id)
        if not meeting:
            raise ValueError("meeting not found")
        out = self.security.resolve_path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        created = []
        if calendar:
            ics = out / f"meeting-{meeting_id}.ics"
            ics.write_text(self._build_ics(meeting), encoding="utf-8")
            created.append(self._record_connector_draft(meeting_id, "calendar_ics", ics, {"recipients": recipients or []}))
        if email:
            eml = out / f"meeting-{meeting_id}-followup.eml"
            eml.write_text(self._build_meeting_email(meeting, recipients or []), encoding="utf-8")
            created.append(self._record_connector_draft(meeting_id, "email_eml", eml, {"recipients": recipients or []}))
        return {"meeting_id": int(meeting_id), "drafts": created, "sent": False}


    def _record_connector_draft(self, meeting_id, connector_type, path, metadata):
        with self.store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO meeting_connector_drafts
                    (meeting_id, connector_type, draft_path, metadata)
                VALUES (?, ?, ?, ?)
                """,
                (int(meeting_id), connector_type, str(path), json.dumps(metadata, ensure_ascii=False)),
            )
            row = c.execute(
                "SELECT * FROM meeting_connector_drafts WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
            return WorkspaceValues._decode_record(row, ("metadata",))


    @staticmethod
    def _parse_speaker_turns(transcript):
        turns = []
        pattern = re.compile(r"^(?:\[(?P<time>[^\]]+)\]\s*)?(?P<speaker>[^:：\n]{1,40})[:：]\s*(?P<text>.+)$")
        for line in str(transcript or "").splitlines():
            match = pattern.match(line.strip())
            if match:
                speaker = match.group("speaker").strip()
                if speaker.lower() not in {"decision", "risk", "action"} and speaker not in {"决定", "风险", "行动项", "待办"}:
                    turns.append({
                        "time": match.group("time") or "",
                        "speaker": speaker,
                        "text": match.group("text").strip(),
                    })
        return turns


    @staticmethod
    def _build_ics(meeting):
        uid = f"clawos-meeting-{meeting['id']}@local"
        date = re.sub(r"[^0-9]", "", meeting.get("meeting_date") or "")[:8] or datetime.now(timezone.utc).strftime("%Y%m%d")
        return "\n".join([
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//ClawOS//Meeting Draft//CN",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART;VALUE=DATE:{date}",
            f"SUMMARY:{meeting['title']}",
            f"DESCRIPTION:{meeting.get('summary','')}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ])


    @staticmethod
    def _build_meeting_email(meeting, recipients):
        actions = "\n".join(
            f"- {a['description']} ({a.get('owner') or 'unassigned'}, {a.get('due_date') or 'no due date'})"
            for a in meeting.get("actions", [])
        ) or "- No action items"
        return "\n".join([
            f"To: {', '.join(recipients)}",
            f"Subject: Meeting follow-up: {meeting['title']}",
            "",
            meeting.get("summary") or meeting["title"],
            "",
            "Actions:",
            actions,
            "",
        ])
