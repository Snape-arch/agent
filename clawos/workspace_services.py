"""Compatibility facade and transaction boundary for workspace domains."""
from __future__ import annotations

from services.workspace.schema import WorkspaceSchema
from services.workspace.git import GitWorkspace
from services.workspace.learning import LearningWorkspace
from services.workspace.meetings import MeetingsWorkspace
from services.workspace.office import OfficeWorkspace
from services.workspace.rendering import ResearchReportRenderer
from services.workspace.reports import ReportsWorkspace
from services.workspace.research import ResearchWorkspace
from services.workspace.shared import WorkspaceValues
from services.workspace.templates import TemplatesWorkspace


class WorkspaceServices:
    """Compose independent workflows over the shared store and permissions."""

    def __init__(self, store, security_policy):
        self.store = store
        self.security = security_policy
        self.git = GitWorkspace(store, security_policy)
        self.learning = LearningWorkspace(store, security_policy)
        self.meetings = MeetingsWorkspace(store, security_policy)
        self.office = OfficeWorkspace(store, security_policy)
        self.rendering = ResearchReportRenderer()
        self.research = ResearchWorkspace(store, security_policy)
        self.templates = TemplatesWorkspace(store, security_policy)
        self.reports = ReportsWorkspace(store, security_policy, self.research, self.rendering)
        with self.store.transaction():
            self._init_db()
            self._ensure_builtin_templates()

    def _init_db(self):
        WorkspaceSchema(self.store).initialize()

    def create_spreadsheet(self, output_path, sheets=None, title=''):
        return self.office.create_spreadsheet(output_path, sheets, title)

    def edit_spreadsheet(self, file_path, updates=None, output_path=''):
        return self.office.edit_spreadsheet(file_path, updates, output_path)

    def create_presentation(self, output_path, title='', slides=None):
        return self.office.create_presentation(output_path, title, slides)

    def edit_presentation(self, file_path, replacements=None, output_path=''):
        return self.office.edit_presentation(file_path, replacements, output_path)

    def _record_office_artifact(self, artifact_type, action, title, path, metadata):
        return self.office._record_office_artifact(artifact_type, action, title, path, metadata)

    def create_meeting(self, title, meeting_date='', attendees=None, agenda=None):
        return self.meetings.create_meeting(title, meeting_date, attendees, agenda)

    def process_meeting_transcript(self, meeting_id, transcript, publish_memory=True):
        return self.meetings.process_meeting_transcript(meeting_id, transcript, publish_memory)

    def get_meeting(self, meeting_id, conn=None):
        return self.meetings.get_meeting(meeting_id, conn)

    @staticmethod
    def _extract_meeting_items(transcript):
        return MeetingsWorkspace._extract_meeting_items(transcript)

    def import_meeting_audio(self, audio_path, transcript_path='', transcript='', title='', meeting_id=None, output_dir=''):
        return self.meetings.import_meeting_audio(audio_path, transcript_path, transcript, title, meeting_id, output_dir)

    def draft_meeting_connectors(self, meeting_id, output_dir, calendar=True, email=True, recipients=None):
        return self.meetings.draft_meeting_connectors(meeting_id, output_dir, calendar, email, recipients)

    def _record_connector_draft(self, meeting_id, connector_type, path, metadata):
        return self.meetings._record_connector_draft(meeting_id, connector_type, path, metadata)

    def import_research_pdf(self, file_path, title=''):
        return self.research.import_research_pdf(file_path, title)

    def validate_citations(self, citations):
        return self.research.validate_citations(citations)

    def research_compare_matrix(self, document_ids=None, query_terms=None):
        return self.research.research_compare_matrix(document_ids, query_terms)

    def create_repro_workflow(self, title, question='', steps=None, output_path=''):
        return self.research.create_repro_workflow(title, question, steps, output_path)

    def generate_research_learning_analysis(self, document_id=None, file_path='', title='', output_dir='', formats=None, depth=5, question_count=50, report_style='journal'):
        return self.reports.generate_research_learning_analysis(document_id, file_path, title, output_dir, formats, depth, question_count, report_style)

    @staticmethod
    def _learning_report_document(document, metadata_reference='research_documents.metadata'):
        return ReportsWorkspace._learning_report_document(document, metadata_reference)

    def _resolve_research_document(self, document_id=None, file_path='', title=''):
        return self.reports._resolve_research_document(document_id, file_path, title)

    def _research_document_chunks(self, document_id):
        return self.reports._research_document_chunks(document_id)

    def _paper_outline(self, text):
        return self.reports._paper_outline(text)

    def _analysis_topics(self, outline, text, target_count):
        return self.reports._analysis_topics(outline, text, target_count)

    def _analysis_questions(self, topics, page_text, depth, question_count):
        return self.reports._analysis_questions(topics, page_text, depth, question_count)

    @staticmethod
    def _is_outline_noise(text):
        return ReportsWorkspace._is_outline_noise(text)

    def _best_evidence_for_topic(self, page_text, topic, fallback_page):
        return self.reports._best_evidence_for_topic(page_text, topic, fallback_page)

    def _evidence_answer(self, topic, evidence, level):
        return self.reports._evidence_answer(topic, evidence, level)

    def _paper_concepts(self, text, limit=12):
        return self.reports._paper_concepts(text, limit)

    def _paper_quality_insights(self, document, outline, questions, concepts):
        return self.reports._paper_quality_insights(document, outline, questions, concepts)

    def _render_learning_analysis_markdown(self, document, outline, questions, concepts, depth, report_style='journal'):
        return self.reports._render_learning_analysis_markdown(document, outline, questions, concepts, depth, report_style)

    def _render_styled_learning_analysis_markdown(self, document, outline, questions, concepts, depth, report_style):
        return self.reports._render_styled_learning_analysis_markdown(document, outline, questions, concepts, depth, report_style)

    def _one_sentence_summary(self, questions):
        return self.reports._one_sentence_summary(questions)

    def _write_learning_analysis_pdf(self, path, title, markdown):
        return self.rendering._write_learning_analysis_pdf(path, title, markdown)

    def _write_learning_analysis_typst_pdf(self, path, title, markdown):
        return self.rendering._write_learning_analysis_typst_pdf(path, title, markdown)

    @staticmethod
    def _markdown_to_typst(title, markdown):
        return ResearchReportRenderer._markdown_to_typst(title, markdown)

    def _write_learning_analysis_reportlab_pdf(self, path, title, markdown):
        return self.rendering._write_learning_analysis_reportlab_pdf(path, title, markdown)

    @staticmethod
    def _safe_filename(name):
        return WorkspaceValues._safe_filename(name)

    def search_research(self, query, limit=10):
        return self.research.search_research(query, limit)

    def create_learning_goal(self, title, description='', target_date='', topics=None):
        return self.learning.create_learning_goal(title, description, target_date, topics)

    def record_learning_review(self, item_id, score, evidence, notes=''):
        return self.learning.record_learning_review(item_id, score, evidence, notes)

    def get_learning_goal(self, goal_id, conn=None):
        return self.learning.get_learning_goal(goal_id, conn)

    def add_learning_dependency(self, goal_id, source_topic, target_topic, relation='depends_on', evidence=''):
        return self.learning.add_learning_dependency(goal_id, source_topic, target_topic, relation, evidence)

    def record_learning_mistake(self, item_id, prompt, wrong_answer, correct_answer, evidence):
        return self.learning.record_learning_mistake(item_id, prompt, wrong_answer, correct_answer, evidence)

    def learning_graph(self, goal_id):
        return self.learning.learning_graph(goal_id)

    def long_term_mastery(self, goal_id):
        return self.learning.long_term_mastery(goal_id)

    def git_snapshot(self, repo_path):
        return self.git.git_snapshot(repo_path)

    def prepare_commit_plan(self, repo_path, message, files=None):
        return self.git.prepare_commit_plan(repo_path, message, files)

    def create_git_change_request(self, repo_path, message, files=None, created_by='user'):
        return self.git.create_git_change_request(repo_path, message, files, created_by)

    def approve_git_change_request(self, request_id, approved_by='user'):
        return self.git.approve_git_change_request(request_id, approved_by)

    def rollback_git_change_request(self, request_id, actor_id='user'):
        return self.git.rollback_git_change_request(request_id, actor_id)

    @staticmethod
    def _normalize_git_files(repo, files):
        return GitWorkspace._normalize_git_files(repo, files)

    def _git_change_snapshot(self, repo, selected):
        return self.git._git_change_snapshot(repo, selected)

    def register_template(self, name, description, files, version=1):
        return self.templates.register_template(name, description, files, version)

    def list_templates(self):
        return self.templates.list_templates()

    def instantiate_template(self, name, target_path, parameters=None, version=None):
        return self.templates.instantiate_template(name, target_path, parameters, version)

    def _ensure_builtin_templates(self):
        return self.templates._ensure_builtin_templates()

    @staticmethod
    def _render_template(content, parameters):
        return TemplatesWorkspace._render_template(content, parameters)

    @staticmethod
    def _summarize_text(text):
        return WorkspaceValues._summarize_text(text)

    @staticmethod
    def _chunk_text(text, size=1200, overlap=150):
        return ResearchWorkspace._chunk_text(text, size, overlap)

    @staticmethod
    def _extract_pdf_text(path):
        return ResearchWorkspace._extract_pdf_text(path)

    @staticmethod
    def _file_hash(path):
        return WorkspaceValues._file_hash(path)

    @staticmethod
    def _git(repo, *args):
        return GitWorkspace._git(repo, *args)

    @staticmethod
    def _parse_speaker_turns(transcript):
        return MeetingsWorkspace._parse_speaker_turns(transcript)

    @staticmethod
    def _build_ics(meeting):
        return MeetingsWorkspace._build_ics(meeting)

    @staticmethod
    def _build_meeting_email(meeting, recipients):
        return MeetingsWorkspace._build_meeting_email(meeting, recipients)

    @staticmethod
    def _decode_record(row, json_keys):
        return WorkspaceValues._decode_record(row, json_keys)

    @staticmethod
    def _git_request_from_row(row):
        return GitWorkspace._git_request_from_row(row)

    @staticmethod
    def _template_from_row(row):
        return TemplatesWorkspace._template_from_row(row)
