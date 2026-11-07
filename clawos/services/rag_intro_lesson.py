"""Owner-scoped, resumable RAG lesson over the existing research and Vision services."""

import json
import re

from services import rag_intro_content as content
from services import vision_teaching_engine as vision
from services.research_learning import Conflict
from services.research_watch import fingerprint, packed


class RagIntroLesson:
    def __init__(self, journey):
        self.journey = journey
        self.store = journey.store
        with self.store._conn() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS research_rag_intro_attempts (
                id TEXT PRIMARY KEY, case_id TEXT NOT NULL, payload TEXT NOT NULL, hash TEXT NOT NULL
            )''')

    def _source(self, actor, cid):
        paper, case_hash = self.journey.paper(actor, cid, content.PAPER_ID)
        if paper['version'] != content.PAPER_VERSION or content.QUOTE not in paper['abstract']:
            raise ValueError('这份学习计划缺少本课对应的 DPR 固定版本作者摘要')
        source = {key: paper[key] for key in ('id', 'name', 'title', 'version', 'raw_sha256', 'page_count', 'metadata_url')}
        source.update(quote=content.QUOTE, page=1, quote_field='author_abstract',
                      abstract_sha256=fingerprint(paper['abstract']),
                      pdf_url=f'/api/vision/research/cases/{cid}/papers/{paper["id"]}/pdf')
        return source, case_hash

    @staticmethod
    def _protocol():
        return fingerprint(dict(version=content.VERSION, forms=content.FORMS, transfer=content.TRANSFER,
                                rubric=content.RUBRIC, experiment=vision.VERSION, fixture=vision.rag.VERSION))

    @staticmethod
    def _form(attempt, phase):
        first = attempt['pre_form']
        return first if phase == 'pre' else {'A': 'B', 'B': 'A'}[first]

    @staticmethod
    def _questions(form):
        return [dict(id=qid, prompt=prompt, options=options) for qid, prompt, options, _, _ in content.FORMS[form]]

    @classmethod
    def _score(cls, attempt, phase, answers):
        form = cls._form(attempt, phase)
        questions = content.FORMS[form]
        if not isinstance(answers, dict) or set(answers) != {q[0] for q in questions}:
            raise ValueError('请回答全部题目')
        rows = []
        for qid, prompt, options, correct, feedback in questions:
            choice = answers[qid]
            if type(choice) is not int or not 0 <= choice < len(options):
                raise ValueError('作答选项无效')
            rows.append(dict(id=qid, prompt=prompt, options=options, choice=choice, correct=correct,
                             passed=choice == correct, feedback=feedback))
        return dict(form=form, score=sum(row['passed'] for row in rows), total=len(rows), rows=rows)

    @staticmethod
    def _read(conn, cid, aid):
        if aid and not re.fullmatch(r'[a-f0-9]{32}', aid):
            raise ValueError('练习编号无效')
        if aid:
            row = conn.execute('SELECT * FROM research_rag_intro_attempts WHERE case_id=? AND id=?', (cid, aid)).fetchone()
            if row is None:
                raise LookupError('练习不存在或不属于当前计划')
        else:
            row = conn.execute('SELECT * FROM research_rag_intro_attempts WHERE case_id=? ORDER BY rowid DESC LIMIT 1', (cid,)).fetchone()
        if row is None:
            return None
        attempt = json.loads(row['payload'])
        if fingerprint(attempt) != row['hash']:
            raise ValueError('练习完整性校验失败')
        return attempt

    @classmethod
    def _view(cls, cid, case_hash, source, attempt):
        view = dict(case_id=cid, case_hash=case_hash, source_version=source['version'], attempt=None)
        if attempt is None:
            return view
        state = {key: attempt[key] for key in ('id', 'phase', 'revision')}
        phase = state['phase']
        if phase == 'done':
            state.update(result={key: attempt[key] for key in ('pre', 'post', 'transfer')}, rubric=attempt['rubric'])
        else:
            if attempt['case_hash'] != case_hash or attempt['protocol'] != cls._protocol():
                raise Conflict('课件或资料版本变化，无法继续这份练习')
            if phase in ('pre', 'post'):
                state['questions'] = cls._questions(cls._form(attempt, phase))
            if phase == 'guide':
                state['source'] = source
            if phase == 'lab':
                state.update(prediction=attempt['prediction'], experiment=attempt.get('experiment'))
            if phase == 'transfer':
                state['prompt'] = content.TRANSFER
        return dict(view, attempt=state)

    def state(self, actor, cid, aid=''):
        source, case_hash = self._source(actor, cid)
        with self.store._conn() as conn:
            attempt = self._read(conn, cid, aid)
        return self._view(cid, case_hash, source, attempt)

    def start(self, actor, cid, data):
        source, case_hash = self._source(actor, cid)
        if set(data) != {'attempt_id', 'case_hash'} or not isinstance(data['attempt_id'], str) or not re.fullmatch(r'[a-f0-9]{32}', data['attempt_id']):
            raise ValueError('练习请求字段无效')
        if data['case_hash'] != case_hash:
            raise Conflict('论文来源变化，请刷新')
        aid = data['attempt_id']
        # Check the real cached original before creating a new learning receipt.
        self.journey.pdf(actor, cid, content.PAPER_ID)
        with self.store.transaction() as conn:
            row = conn.execute('SELECT case_id FROM research_rag_intro_attempts WHERE id=?', (aid,)).fetchone()
            if row:
                if row['case_id'] != cid:
                    raise Conflict('练习编号已用于另一份计划')
                return self._view(cid, case_hash, source, self._read(conn, cid, aid))
            latest = self._read(conn, cid, '')
            if latest and latest['phase'] != 'done':
                raise Conflict('请先继续当前未完成的练习')
            count = conn.execute('SELECT COUNT(*) FROM research_rag_intro_attempts WHERE case_id=?', (cid,)).fetchone()[0]
            if count >= 100:
                raise Conflict('这份计划已保留 100 次练习')
            now = self.journey.watch.clock()
            attempt = dict(id=aid, case_id=cid, case_hash=case_hash, source=source, revision=0, phase='pre',
                           version=content.VERSION, protocol=self._protocol(), pre_form='AB'[count % 2], timestamps={'started': now})
            conn.execute('INSERT INTO research_rag_intro_attempts VALUES(?,?,?,?)', (aid, cid, packed(attempt), fingerprint(attempt)))
        return self._view(cid, case_hash, source, attempt)

    @staticmethod
    def _text(value):
        if not isinstance(value, str) or not 8 <= len(value.strip()) <= 1500:
            raise ValueError('请填写 8–1500 字的观察或解释')
        return value.strip()

    @staticmethod
    def _experiment():
        result = vision.execute('rag', True, 42)
        arms = [dict(config=arm['config'], rows=[row for row in arm['evidence']['rows']
                     if row['case_id'] in ('loan', 'missing')]) for arm in result['arms']]
        return dict(arms=arms, engine_version=result['engine_version'],
                    corpus_sha256=vision.rag.digest(result['fixture']), result_sha256=fingerprint(result),
                    execution=result['execution'], model_calls=result['model_calls'])

    def advance(self, actor, cid, aid, data):
        source, case_hash = self._source(actor, cid)
        if set(data) != {'revision', 'action', 'value'} or type(data['revision']) is not int or data['revision'] < 0:
            raise ValueError('步骤请求字段无效')
        action, value = data['action'], data['value']
        request_hash = fingerprint(data)
        with self.store.transaction() as conn:
            attempt = self._read(conn, cid, aid)
            if attempt.get('last_request') == request_hash:
                return self._view(cid, case_hash, source, attempt)
            if attempt['revision'] != data['revision'] or attempt['case_hash'] != case_hash or attempt['protocol'] != self._protocol():
                raise Conflict('练习步骤或来源已更新，请恢复已保存进度')
            phase = attempt['phase']
            if phase == 'pre' and action == 'submit':
                attempt.update(pre=self._score(attempt, phase, value), phase='guide')
            elif phase == 'guide' and action == 'predict':
                attempt.update(prediction=self._text(value), phase='lab')
            elif phase == 'lab' and action == 'run' and value is True and 'experiment' not in attempt:
                attempt['experiment'] = self._experiment()
            elif phase == 'lab' and action == 'observe' and 'experiment' in attempt:
                attempt.update(observation=self._text(value), phase='post')
            elif phase == 'post' and action == 'submit':
                attempt.update(post=self._score(attempt, phase, value), phase='transfer')
            elif phase == 'transfer' and action == 'submit':
                attempt.update(transfer=dict(prompt=content.TRANSFER, answer=self._text(value), review_status='pending'),
                               rubric=content.RUBRIC, phase='done')
            else:
                raise Conflict('请按课程序完成当前步骤')
            attempt['timestamps'][f'{phase}:{action}'] = self.journey.watch.clock()
            attempt.update(revision=attempt['revision']+1, last_request=request_hash)
            conn.execute('UPDATE research_rag_intro_attempts SET payload=?,hash=? WHERE id=?',
                         (packed(attempt), fingerprint(attempt), aid))
        return self._view(cid, case_hash, source, attempt)

    def export(self, actor, cid, aid, review=False):
        self.journey.case(actor, cid)
        with self.store._conn() as conn:
            attempt = self._read(conn, cid, aid)
        if attempt['phase'] != 'done':
            raise Conflict('完成后测和迁移题后才能导出')
        if review:
            receipt = {key: attempt[key] for key in ('id', 'version', 'protocol', 'transfer', 'rubric')}
        else:
            receipt = {key: value for key, value in attempt.items() if key != 'last_request'}
        receipt.update(teacher_verified=False, learning_effect_verified=False, mastery_updated=False, agent_reward=False)
        return dict(receipt=receipt, sha256=fingerprint(receipt))
