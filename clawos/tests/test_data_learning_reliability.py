import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from memoryos.services.retrieval import BM25Index
from services.maintenance_service import MaintenanceService
from services.academy_materials import AcademyMaterials


class DataLearningReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = MemoryStore(str(self.root / 'memory.db'))
        self.ops = MaintenanceService(store=self.store, db_path=self.root/'memory.db', base_dir=self.root, config={})

    def test_context_retention_is_per_session(self):
        self.store.save_context_snapshot('other', task='keep me')
        for n in range(25):
            self.store.save_context_snapshot('active', task=str(n))
        self.assertEqual(self.store.get_latest_context('other')['task_description'], 'keep me')
        with self.store._conn() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM context_snapshots WHERE session_id='active'").fetchone()[0], 20)

    def test_chinese_bm25_matches_question_with_different_sentence_boundaries(self):
        index = BM25Index()
        index.add('useful', '检索系统必须在证据充分时才能回答，否则应拒答。')
        index.add('noise', '本周天气温暖，活动安排在周五。')
        hits = index.search('为什么证据不足时要拒答？')
        self.assertEqual(hits[0]['doc_id'], 'useful')
        self.assertEqual(index.search('completely unrelated'), [])

    def test_backups_unique_verified_and_preserve_learning_tables(self):
        service = AcademyMaterials(self.store, self.root/'materials')
        state = service.upload('book.txt', b'Evidence supports conclusions.')
        service.event(state['document']['id'], 'draft', {'answer':'original'})
        one, two = self.ops.backup_database(), self.ops.backup_database()
        self.assertNotEqual(one['path'], two['path'])
        self.assertEqual(one['integrity'], 'ok')
        with closing(sqlite3.connect(one['path'])) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM academy_material_events').fetchone()[0], 1)
        self.assertEqual(self.ops.database_health()['counts']['academy_materials'], 1)

    def test_restore_reads_wal_and_updates_existing_connection(self):
        other = MemoryStore(str(self.root/'source.db'))
        keeper = sqlite3.connect(other._db_path)
        self.addCleanup(keeper.close)
        keeper.execute('PRAGMA journal_mode=WAL')
        keeper.execute('PRAGMA wal_autocheckpoint=0')
        other.add_message('restored', 'user', 'committed WAL value')
        self.store.add_message('discarded', 'user', 'before restore')
        live = sqlite3.connect(self.store._db_path)
        self.addCleanup(live.close)
        self.assertEqual(live.execute('SELECT COUNT(*) FROM conversations').fetchone()[0], 1)
        result = self.ops.restore_database(other._db_path, confirm=True)
        self.assertTrue(result['ok'])
        self.assertEqual(live.execute('SELECT content FROM conversations').fetchone()[0], 'committed WAL value')
        self.assertEqual(self.store.get_session_messages('discarded'), [])
        with closing(sqlite3.connect(result['pre_restore_backup']['path'])) as c:
            self.assertEqual(c.execute('SELECT content FROM conversations').fetchone()[0], 'before restore')

    def test_failed_migration_and_invalid_database_leave_live_data_intact(self):
        self.store.add_message('live', 'user', 'must survive')
        backup = self.ops.backup_database()
        with patch.object(MaintenanceService, 'apply_migrations', side_effect=RuntimeError('migration failed')):
            with self.assertRaises(RuntimeError):
                self.ops.restore_database(backup['path'], confirm=True)
        self.assertEqual(self.store.get_session_messages('live')[0]['content'], 'must survive')
        empty = self.root/'unrelated.db'
        with closing(sqlite3.connect(empty)) as c:
            c.execute('CREATE TABLE unrelated(id INTEGER)')
        with self.assertRaises(ValueError):
            self.ops.restore_database(str(empty), confirm=True)
        with self.assertRaises(ValueError):
            self.ops.restore_database(self.store._db_path, confirm=True)

    def material(self):
        service = AcademyMaterials(self.store, self.root/'materials')
        state = service.upload('book.txt', b'Evidence supports conclusions. Missing evidence requires refusal.')
        mid = state['document']['id']; chapter = state['chapters'][0]
        questions = {'questions':[dict(dimension=d,question='Explain why evidence matters.',quote='Evidence supports conclusions.',criterion='Explain the condition and its implication.') for d in ('concept','reasoning','transfer')]}
        q = service.save_chapter_questions(mid, chapter['id'], 'research', questions)
        return service, mid, chapter, questions, q

    def test_old_question_version_remains_addressable_after_200_events(self):
        service, mid, chapter, questions, first = self.material()
        service.save_chapter_questions(mid, chapter['id'], 'research', questions)
        for i in range(205):
            service.event(mid, 'tutor', {'citation':'another','answer':str(i)})
        saved = service.chapter_draft(mid, chapter['id'], ['', '', ''], dict.fromkeys(('question','method','result','reflection','quote'), ''), first['id'])
        self.assertEqual(saved['data']['question_event_id'], first['id'])
        with self.assertRaises(ValueError):
            service.question_event(mid, chapter['id'], first['id'], 'other-person')

    def test_progress_remediation_and_resubmission_do_not_reuse_old_pass(self):
        service, mid, chapter, questions, q = self.material()
        project = dict(question='What supports answers?',method='Check the source.',result='Evidence is required.',reflection='More tests are needed.',quote='Evidence supports conclusions.')
        answers = ['Evidence must support the conclusion.'] * 3
        submit = service.chapter_response(mid, chapter['id'], answers, project, question_event_id=q['id'])
        judge = dict(dimensions={d:dict(score=2,reason='Explains evidence conditions.',student_quote='Evidence must support',source_quote='Evidence supports conclusions.',next_step='Try a case with no evidence.') for d in ('concept','reasoning','transfer')})
        weak = copy.deepcopy(judge); weak['dimensions']['reasoning']['score'] = 1
        service.save_chapter_review(mid, submit['id'], [weak,weak])
        state = service.state(mid)
        self.assertEqual(state['learning_plan']['counts']['needs_revision'], 1)
        self.assertEqual(state['chapters'][0]['remediation'][0]['dimension'], 'reasoning')
        service.event(mid, 'draft', dict(citation=chapter['citation'], answer='Current explanation draft'))
        service.event(mid, 'assessment', dict(citation='unrelated passage', answer='Unrelated weakness'))
        tutor = json.loads(service.teaching_prompt(mid, chapter['citation'], 'How can I explain this condition?')[1]['content'])
        self.assertTrue(tutor['remediation'])
        self.assertIn('Current explanation draft', json.dumps(tutor))
        self.assertNotIn('Unrelated weakness', json.dumps(tutor))
        service.save_chapter_review(mid, submit['id'], [judge,judge])
        self.assertEqual(service.state(mid)['learning_plan']['counts']['passed'], 1)
        service.chapter_response(mid, chapter['id'], answers, project, question_event_id=q['id'])
        self.assertEqual(service.state(mid)['chapters'][0]['status'], 'submitted')
        current = service.save_chapter_questions(mid, chapter['id'], 'research', questions)
        self.assertEqual(service.state(mid)['chapters'][0]['status'], 'in_progress')
        latest = service.chapter_response(mid, chapter['id'], answers, project, question_event_id=current['id'])
        service.save_chapter_review(mid, latest['id'], [judge,judge])
        # Late work on an older question must not evict the active version's state.
        older = service.chapter_response(mid, chapter['id'], answers, project, question_event_id=q['id'])
        service.save_chapter_review(mid, older['id'], [weak,weak])
        for i in range(205):
            service.event(mid, 'tutor', dict(citation='elsewhere', answer=str(i)))
        self.assertEqual(service.state(mid)['chapters'][0]['status'], 'passed')


if __name__ == '__main__':
    unittest.main()
