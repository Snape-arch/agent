"""Material-scoped study planning and retrieval practice, without mastery claims."""
from datetime import datetime, timedelta, timezone
import json


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class AcademyJourney:
    INTERVALS = (1, 3, 7, 14, 30)

    def __init__(self, materials):
        self.materials = materials
        self.store = materials.store
        with self.store._conn() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS academy_journey_settings (
                    material_id TEXT PRIMARY KEY REFERENCES academy_materials(id),
                    minutes INTEGER NOT NULL DEFAULT 20);
                CREATE TABLE IF NOT EXISTS academy_recall_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    material_id TEXT NOT NULL REFERENCES academy_materials(id),
                    chapter TEXT NOT NULL, revision TEXT NOT NULL,
                    question_event_id INTEGER NOT NULL, review_event_id INTEGER NOT NULL,
                    prompts TEXT NOT NULL, answers TEXT, rating TEXT,
                    stage INTEGER NOT NULL DEFAULT 0, due_at TEXT,
                    created_at TEXT NOT NULL, submitted_at TEXT, rated_at TEXT);
                CREATE INDEX IF NOT EXISTS academy_recall_scope_idx
                    ON academy_recall_attempts(material_id,chapter,review_event_id,id);
            ''')

    def state(self, doc, chapters, now=None):
        now = now or utc_now()
        mid = doc['id']
        with self.store._conn() as conn:
            setting = conn.execute('SELECT minutes FROM academy_journey_settings WHERE material_id=?', (mid,)).fetchone()
            attempts = [dict(r) for r in conn.execute('''SELECT * FROM academy_recall_attempts WHERE id IN (
                SELECT MAX(id) FROM academy_recall_attempts WHERE material_id=?
                GROUP BY chapter,review_event_id) ORDER BY id DESC''', (mid,))]
        minutes = setting['minutes'] if setting else 20
        queue = []
        for chapter in chapters:
            if chapter['status'] != 'passed' or not chapter.get('review_event_id'):
                continue
            attempt = next((a for a in attempts if a['chapter'] == chapter['id']
                            and a['review_event_id'] == chapter['review_event_id'] and a['revision'] == chapter['revision']), None)
            due = attempt['due_at'] if attempt and attempt['rating'] else (timestamp(chapter['reviewed_at']) + timedelta(days=1)).isoformat()
            # An unfinished recall remains resumable even before its scheduled date.
            pending = bool(attempt and not attempt['rating'])
            queue.append(dict(chapter=chapter['id'], title=chapter['title'], due_at=due,
                due=timestamp(due) <= now, pending=pending, attempt_id=attempt['id'] if pending else None,
                stage=attempt['stage'] if attempt else 0, rating=attempt['rating'] if attempt else None))
        queue.sort(key=lambda row: (not row['pending'], not row['due'], row['due_at'], row['chapter']))
        tasks = []
        for row in queue:
            if row['due'] or row['pending']:
                tasks.append(dict(kind='recall', chapter=row['chapter'], title=row['title'], minutes=5, reason='先闭卷回忆，再对照原文'))
        priorities = {'needs_revision': 0, 'in_progress': 1, 'submitted': 2, 'not_started': 3}
        for c in sorted(chapters, key=lambda c: priorities.get(c['status'], 9)):
            if c['status'] in priorities and not c['review_required']:
                tasks.append(dict(kind='chapter', chapter=c['id'], title=c['title'],
                    minutes=5 if c['status'] == 'submitted' else 15,
                    reason={'needs_revision':'修订薄弱维度', 'in_progress':'继续未完成作答',
                            'submitted':'检查已提交回答', 'not_started':'阅读原文并提出问题'}[c['status']]))
        selected, remaining = [], minutes
        for task in tasks:
            if remaining >= task['minutes']:
                selected.append(task)
                remaining -= task['minutes']
        return dict(minutes=minutes, tasks=selected, planned_minutes=minutes-remaining,
            review_queue=queue, due_count=sum(r['due'] or r['pending'] for r in queue),
            blocked_count=sum(c['status']=='needs_review' for c in chapters),
            boundary='复习间隔依据个人回忆自评安排；不会增加掌握度。日期按本地时区显示。')

    def settings(self, mid, minutes, learner='local-user'):
        self.materials.document(mid, learner)
        if type(minutes) is not int or minutes not in (20, 40, 60):
            raise ValueError('每日投入请选择 20、40 或 60 分钟')
        with self.store._conn() as conn:
            conn.execute('''INSERT INTO academy_journey_settings(material_id,minutes) VALUES (?,?)
                ON CONFLICT(material_id) DO UPDATE SET minutes=excluded.minutes''', (mid, minutes))
        return dict(saved=True, minutes=minutes)

    def start(self, mid, chapter_id, learner='local-user'):
        chapter = self.materials.chapter(mid, chapter_id, learner)
        if chapter['status'] != 'passed':
            raise ValueError('本章回答通过评阅后才能开始间隔复习')
        question = self.materials.question_event(mid, chapter_id, chapter['question_event_id'], learner)
        prompts = [q['question'] for q in question['data']['questions']]
        with self.store._lock, self.store._conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            latest = conn.execute('''SELECT * FROM academy_recall_attempts WHERE material_id=? AND chapter=?
                AND review_event_id=? ORDER BY id DESC LIMIT 1''', (mid, chapter_id, chapter['review_event_id'])).fetchone()
            if latest and not latest['rating']:
                return self._public(dict(latest))
            cursor = conn.execute('''INSERT INTO academy_recall_attempts
                (material_id,chapter,revision,question_event_id,review_event_id,prompts,stage,created_at)
                VALUES (?,?,?,?,?,?,?,?)''', (mid, chapter_id, chapter['revision'], question['id'],
                    chapter['review_event_id'], json.dumps(prompts, ensure_ascii=False), latest['stage'] if latest else 0, utc_now().isoformat()))
            row = dict(conn.execute('SELECT * FROM academy_recall_attempts WHERE id=?', (cursor.lastrowid,)).fetchone())
        return self._public(row)

    def attempt(self, mid, attempt_id, learner='local-user'):
        self.materials.document(mid, learner)
        if type(attempt_id) is not int:
            raise ValueError('请提供复习记录编号')
        with self.store._conn() as conn:
            row = conn.execute('SELECT * FROM academy_recall_attempts WHERE material_id=? AND id=?', (mid, attempt_id)).fetchone()
        if not row:
            raise ValueError('复习记录不存在')
        row = dict(row)
        chapter = self.materials.chapter(mid, row['chapter'], learner)
        if (chapter['revision'] != row['revision'] or chapter['question_event_id'] != row['question_event_id']
                or chapter['review_event_id'] != row['review_event_id'] or chapter['status'] != 'passed'):
            raise ValueError('原文或评阅版本已变化，请重新开始复习')
        return row

    def submit(self, mid, attempt_id, answers, learner='local-user'):
        if not isinstance(answers, list) or len(answers) != 3 or any(not isinstance(a, str) or not 10 <= len(a.strip()) <= 4000 for a in answers):
            raise ValueError('请独立回答三个问题，每题 10–4000 字')
        with self.store._lock:
            self.attempt(mid, attempt_id, learner)
            encoded = json.dumps(answers, ensure_ascii=False)
            with self.store._conn() as conn:
                conn.execute('BEGIN IMMEDIATE')
                row = conn.execute('SELECT answers FROM academy_recall_attempts WHERE id=?', (attempt_id,)).fetchone()
                if row['answers'] is not None and row['answers'] != encoded:
                    raise ValueError('已揭示原文的复习不能修改闭卷回答，请开始新一轮')
                conn.execute('''UPDATE academy_recall_attempts SET answers=?,submitted_at=COALESCE(submitted_at,?)
                    WHERE id=?''', (encoded, utc_now().isoformat(), attempt_id))
        return self._public(self.attempt(mid, attempt_id, learner))

    def rate(self, mid, attempt_id, rating, learner='local-user'):
        if rating not in ('again', 'partial', 'remembered'):
            raise ValueError('请选择忘记了、部分记得或能够解释')
        with self.store._lock:
            row = self.attempt(mid, attempt_id, learner)
            if row['answers'] is None:
                raise ValueError('先提交闭卷回答，再对照原文自评')
            with self.store._conn() as conn:
                conn.execute('BEGIN IMMEDIATE')
                row = dict(conn.execute('SELECT * FROM academy_recall_attempts WHERE id=?', (attempt_id,)).fetchone())
                if row['rating']:
                    if row['rating'] != rating:
                        raise ValueError('本次自评已保存，请开始新一轮复习')
                    return self._public(row)
                stage = min(row['stage'] + 1, len(self.INTERVALS)) if rating == 'remembered' else max(0, row['stage'] - 1) if rating == 'partial' else 0
                days = self.INTERVALS[max(0, stage-1)] if rating == 'remembered' else 1
                now = utc_now()
                conn.execute('UPDATE academy_recall_attempts SET rating=?,stage=?,due_at=?,rated_at=? WHERE id=?',
                             (rating, stage, (now+timedelta(days=days)).isoformat(), now.isoformat(), attempt_id))
                row = dict(conn.execute('SELECT * FROM academy_recall_attempts WHERE id=?', (attempt_id,)).fetchone())
        return self._public(row)

    @staticmethod
    def _public(row):
        return {**row, 'prompts': json.loads(row['prompts']),
                'answers': json.loads(row['answers']) if row['answers'] is not None else None}

    def passport(self, mid, learner='local-user'):
        state = self.materials.state(mid, learner)
        with self.store._conn() as conn:
            events = [dict(id=r['id'], kind=r['kind'], data=json.loads(r['payload']), created_at=r['created_at'])
                      for r in conn.execute('''SELECT * FROM academy_material_events WHERE material_id=?
                          AND kind IN ('chapter_questions','chapter_response','chapter_review','project','model_run') ORDER BY id''', (mid,))]
            recalls = [self._public(dict(r)) for r in conn.execute('SELECT * FROM academy_recall_attempts WHERE material_id=? ORDER BY id', (mid,))]
        doc = state['document']
        return dict(schema='clawos.learning-passport.v1', exported_at=utc_now().isoformat(),
            material=dict(id=mid, title=doc['title'], digest=doc['digest'], revision=doc['payload'].get('revision')),
            chapters=[{k:c[k] for k in ('id','title','citation','revision','status','question_event_id','review_event_id')} for c in state['chapters']],
            journey=state['journey'], evidence_events=events, recall_attempts=recalls,
            boundary='学习过程与证据记录，包含你的作答；不构成能力认证。仅导出当前学习材料。')
