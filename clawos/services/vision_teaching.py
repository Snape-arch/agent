"""Immutable experiment evidence and append-only reflections, separate from mastery."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import threading
import uuid

from services.academy_curriculum import LESSONS
from services import vision_teaching_engine as engine


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def implementation_hashes():
    # Git's Windows checkout policy must not change an implementation identity.
    return {p.name:hashlib.sha256(p.read_text(encoding='utf-8').replace('\r\n','\n').replace('\r','\n').encode()).hexdigest()
            for p in (Path(engine.__file__), Path(engine.rag.__file__), Path(__file__))}


class Conflict(ValueError):pass


class VisionTeaching:
    def __init__(self, path, lab=None):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lab = lab; self.lock = threading.RLock()
        with self.connect() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS teaching_reports(
                    id TEXT PRIMARY KEY, actor TEXT NOT NULL, request_id TEXT NOT NULL,
                    input_hash TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL,
                    hash TEXT NOT NULL, UNIQUE(actor,request_id));
                CREATE TABLE IF NOT EXISTS teaching_reflections(
                    report_id TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL,
                    hash TEXT NOT NULL, PRIMARY KEY(report_id,version));
                CREATE TABLE IF NOT EXISTS teaching_visualizations(
                    id TEXT PRIMARY KEY, actor TEXT NOT NULL, report_id TEXT NOT NULL,
                    request_id TEXT NOT NULL, input_hash TEXT NOT NULL, payload TEXT NOT NULL,
                    hash TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(actor,request_id));
            ''')

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=15); c.row_factory = sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    @staticmethod
    def catalog():
        by_id = {l['id']:l for l in LESSONS}
        return dict(version=engine.VERSION, templates=[dict(t, lesson_snapshot=by_id[t['lesson']]) for t in engine.TEMPLATES],
                    boundary='小规模合成资料上的真实 CPU 机制实验；不自动更新掌握度或学习效果评测。')

    @contextmanager
    def binding(self, value, actor):
        if value is None:
            yield None; return
        if not self.lab or not isinstance(value, dict) or set(value) != {'material_id','node_id','revision','graph_version'}:
            raise ValueError('教材关联字段不完整')
        if any(not isinstance(value[k],str) or not 1 <= len(value[k]) <= 200 for k in ('material_id','node_id','revision')) or type(value['graph_version']) is not int:
            raise ValueError('教材关联编号无效')
        lab = self.lab()
        # Keep the teaching source stable through result persistence, even though
        # reports live in a separate DB. Graph writers must acquire this DB lock.
        with lab.store._conn() as c:
            c.execute('BEGIN IMMEDIATE'); lab.authorize(c, value['material_id'], actor)
            doc = c.execute('SELECT title,payload FROM academy_materials WHERE id=?',(value['material_id'],)).fetchone()
            doc_payload = json.loads(doc['payload'])
            row = c.execute('SELECT * FROM academy_book_graphs WHERE material_id=?',(value['material_id'],)).fetchone()
            if not row or row['revision'] != doc_payload['revision'] or value['revision'] != row['revision'] or value['graph_version'] != row['version']:
                raise Conflict('教材或图谱版本已变化，请重新选择知识点；本次未保存')
            node = next((n for n in json.loads(row['payload'])['nodes'] if n['id'] == value['node_id']),None)
            if not node:raise ValueError('知识点不存在')
            yield dict(value, book_title=doc['title'], node=node, association='user_selected_not_semantically_verified')

    def create(self, actor, data):
        fields = {'request_id','template','value','seed','hypothesis','binding'}
        if not isinstance(data,dict) or set(data) != fields:raise ValueError('实验请求字段不完整')
        if not isinstance(data['request_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',data['request_id']):raise ValueError('请求编号无效')
        if not isinstance(data['hypothesis'],str) or not 10 <= len(data['hypothesis'].strip()) <= 2000:raise ValueError('实验前预测需 10–2000 字符')
        engine.config(data['template'],data['value'],data['seed'])
        input_hash = digest(data)
        with self.lock:
            with self.connect() as c:
                existing = c.execute('SELECT id,input_hash FROM teaching_reports WHERE actor=? AND request_id=?',(actor,data['request_id'])).fetchone()
            if existing:
                if existing['input_hash'] != input_hash:raise Conflict('请求编号已用于另一配置')
                return self.get(actor, existing['id'])
            with self.binding(data['binding'],actor) as snapshot:
                before = snapshot
            result = engine.execute(data['template'], data['value'], data['seed'])
            lesson = next(l for l in LESSONS if l['id'] == result['template']['lesson'])
            rid = uuid.uuid4().hex; created = datetime.now(timezone.utc).isoformat()
            payload = dict(schema='clawos.teaching-experiment.v1', id=rid, created=created,
                           hypothesis=data['hypothesis'].strip(), binding=before, lesson=lesson,
                           request=data, source_hashes=implementation_hashes(), result=result,
                           runtime=dict(python=sys.version.split()[0],implementation=sys.implementation.name))
            with self.binding(data['binding'],actor) as current:
                if digest(before) != digest(current):raise Conflict('知识点来源发生变化，结果未保存')
                with self.connect() as c:
                    c.execute('BEGIN IMMEDIATE')
                    # Also prevents duplicate results across service instances.
                    existing = c.execute('SELECT id,input_hash FROM teaching_reports WHERE actor=? AND request_id=?',(actor,data['request_id'])).fetchone()
                    if existing:
                        if existing['input_hash'] != input_hash:raise Conflict('请求编号已用于另一配置')
                        rid = existing['id']
                    else:c.execute('INSERT INTO teaching_reports VALUES (?,?,?,?,?,?,?)',
                                   (rid,actor,data['request_id'],input_hash,created,encode(payload),digest(payload)))
            return self.get(actor,rid)

    def get(self, actor, rid):
        with self.connect() as c:
            row = c.execute('SELECT * FROM teaching_reports WHERE id=? AND actor=?',(rid,actor)).fetchone()
            if not row:raise LookupError('实验记录不存在')
            payload = json.loads(row['payload'])
            if digest(payload) != row['hash']:raise ValueError('实验记录完整性校验失败')
            reflections = []
            for r in c.execute('SELECT * FROM teaching_reflections WHERE report_id=? ORDER BY version',(rid,)):
                value = json.loads(r['payload'])
                if digest(value) != r['hash']:raise ValueError('反思记录完整性校验失败')
                reflections.append(value)
        return dict(report=payload, hash=row['hash'], reflections=reflections, reflection_version=len(reflections),
                    learning_record=dict(lesson=payload['lesson']['id'], status='reflected' if reflections else 'experiment_recorded',
                                         mastery_updated=False, learning_effect_verified=False))

    def history(self, actor, page=1, template=None):
        if type(page) is not int or not 1 <= page <= 10000:raise ValueError('页码无效')
        if template is not None and template not in {t['id'] for t in engine.TEMPLATES}:raise ValueError('模板无效')
        with self.connect() as c:
            where='actor=?';args=[actor]
            if template is not None:where+=' AND json_extract(payload,\'$.result.template.id\')=?';args.append(template)
            total=c.execute('SELECT COUNT(*) FROM teaching_reports WHERE '+where,args).fetchone()[0]
            rows=c.execute('SELECT id,created,payload,hash FROM teaching_reports WHERE '+where+' ORDER BY created DESC,id DESC LIMIT 20 OFFSET ?',(*args,(page-1)*20)).fetchall()
            items=[]
            for r in rows:
                p=json.loads(r['payload'])
                if digest(p)!=r['hash']:raise ValueError('实验记录完整性校验失败')
                versions=c.execute('SELECT COUNT(*) FROM teaching_reflections WHERE report_id=?',(r['id'],)).fetchone()[0]
                items.append(dict(id=r['id'],created=r['created'],template=p['result']['template']['id'],title=p['result']['template']['title'],
                                  lesson=p['lesson']['id'],binding=p['binding'],reflections=versions))
            return dict(items=items,page=page,total=total,has_more=page*20<total)

    def reflect(self, actor, rid, data):
        if not isinstance(data,dict) or set(data) != {'version','report_hash','observation','explanation','limitation'}:raise ValueError('反思字段不完整')
        if type(data['version']) is not int or data['version'] < 0:raise ValueError('反思版本无效')
        if any(not isinstance(data[k],str) or not 10 <= len(data[k].strip()) <= 3000 for k in ('observation','explanation','limitation')):
            raise ValueError('观察、解释与局限各需 10–3000 字符')
        with self.lock, self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            record=self.get(actor,rid)
            if record['hash'] != data['report_hash'] or record['reflection_version'] != data['version']:raise Conflict('报告或反思版本冲突，请重新打开记录')
            value=dict(data,created=datetime.now(timezone.utc).isoformat(),version=data['version']+1,
                       source='learner_self_report',teacher_verified=False)
            c.execute('INSERT INTO teaching_reflections VALUES (?,?,?,?)',(rid,value['version'],encode(value),digest(value)))
        return self.get(actor,rid)

    @staticmethod
    def validate_visual_state(record, state):
        if not isinstance(state,dict) or type(state.get('arm')) is not int or state['arm'] not in (0,1):
            raise ValueError('视图需选择已有的基线或对照')
        result=record['report']['result'];arm=result['arms'][state['arm']];template=result['template']['id']
        if template=='rag':
            if set(state)!={'kind','arm','case_id'} or state['kind']!='rag-source' or state['case_id'] not in {r['case_id'] for r in arm['evidence']['rows']}:
                raise ValueError('来源视图需选择本实验的已有问题')
        elif template=='peft':
            if set(state)!={'kind','arm','matrix','row','column'} or state['kind']!='low-rank' or state['matrix'] not in ('a','b','update','total'):
                raise ValueError('低秩视图类型无效')
            a=arm['evidence']['adapter_a'];b=arm['evidence']['adapter_b']
            rows,columns=(len(a),len(a[0])) if state['matrix']=='a' else (len(b),len(b[0])) if state['matrix']=='b' else (len(b),len(a[0]))
            if type(state['row']) is not int or type(state['column']) is not int or not 0<=state['row']<rows or not 0<=state['column']<columns:
                raise ValueError('矩阵元素位置超出已保存矩阵')
        elif template=='diffusion':
            if set(state)!={'kind','arm','frame'} or state['kind']!='diffusion-timeline' or type(state['frame']) is not int or not 0<=state['frame']<len(arm['curve']):
                raise ValueError('采样视图只能选择本实验保存的步骤')
        else:raise ValueError('当前实验没有受支持的教学可视化')
        return dict(state)

    def save_visualization(self, actor, rid, data):
        if not isinstance(data,dict) or set(data)!={'name','state','report_hash','request_id'}:raise ValueError('可视化保存字段不完整')
        if not isinstance(data['name'],str) or not 1<=len(data['name'].strip())<=120:raise ValueError('视图名称需1–120字符')
        if not isinstance(data['request_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',data['request_id']):raise ValueError('请求编号无效')
        record=self.get(actor,rid)
        if data['report_hash']!=record['hash']:raise Conflict('实验来源摘要冲突，未保存视图')
        state=self.validate_visual_state(record,data['state']);input_hash=digest(dict(data,report_id=rid))
        with self.lock,self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM teaching_visualizations WHERE actor=? AND request_id=?',(actor,data['request_id'])).fetchone()
            if old:
                if old['input_hash']!=input_hash:raise Conflict('请求编号已用于另一视图')
                return self._visual_value(old)
            if c.execute('SELECT COUNT(*) FROM teaching_visualizations WHERE actor=? AND report_id=?',(actor,rid)).fetchone()[0]>=200:
                raise ValueError('每份实验最多保存200个观察视图')
            vid=uuid.uuid4().hex;created=datetime.now(timezone.utc).isoformat()
            value=dict(schema='clawos.teaching-visualization.v1',id=vid,report_id=rid,report_hash=record['hash'],
                       name=data['name'].strip(),state=state,created=created,visibility='owner_only')
            c.execute('INSERT INTO teaching_visualizations VALUES (?,?,?,?,?,?,?,?)',
                      (vid,actor,rid,data['request_id'],input_hash,encode(value),digest(value),created))
        return value

    @staticmethod
    def _visual_value(row):
        value=json.loads(row['payload'])
        if digest(value)!=row['hash']:raise ValueError('可视化视图完整性校验失败')
        return value

    def visualization(self, actor, vid):
        with self.connect() as c:row=c.execute('SELECT * FROM teaching_visualizations WHERE id=? AND actor=?',(vid,actor)).fetchone()
        if not row:raise LookupError('视图不存在')
        value=self._visual_value(row);record=self.get(actor,value['report_id'])
        if record['hash']!=value['report_hash']:raise Conflict('视图对应的实验来源摘要不一致')
        self.validate_visual_state(record,value['state'])
        return dict(view=value,record=record)

    def visualizations(self, actor, rid, page=1):
        self.get(actor,rid)
        if type(page) is not int or not 1<=page<=10000:raise ValueError('页码无效')
        with self.connect() as c:
            total=c.execute('SELECT COUNT(*) FROM teaching_visualizations WHERE actor=? AND report_id=?',(actor,rid)).fetchone()[0]
            rows=c.execute('SELECT * FROM teaching_visualizations WHERE actor=? AND report_id=? ORDER BY created DESC,id DESC LIMIT 20 OFFSET ?',
                           (actor,rid,(page-1)*20)).fetchall()
        return dict(items=[self._visual_value(r) for r in rows],page=page,total=total,has_more=page*20<total)

    @staticmethod
    def markdown(record):
        p=record['report'];r=p['result'];lines=[f"# {r['template']['title']}",f"记录：{p['id']} · {p['created']}",
            f"课程：{p['lesson']['title']}",f"报告 SHA256：{record['hash']}", '## 实验前预测', p['hypothesis'],
            '## 基线与对照', f"只改动 {r['template']['variable']}，主指标：{r['template']['unit']}。"]
        for label,arm in zip(('基线','对照'),r['arms']):lines.append(f"- {label}：{encode(arm['config'])}；结果 {arm['metric']:.8g}")
        lines += ['## 适用范围',r['boundary'],'执行类型：真实 CPU / 合成教学样本。论文复现、教师审核与学习效果均未认证。']
        if p['binding']:lines += ['## 教材关联',encode(p['binding'])]
        for ref in record['reflections']:
            lines += [f"## 学习反思 · 第 {ref['version']} 版（本人记录）",'观察：'+ref['observation'],'解释：'+ref['explanation'],'局限：'+ref['limitation']]
        lines += ['## 完整依据与复跑输入','下载配套 JSON 可查看逐项结果、配置、样本及实现指纹。']
        return '\n\n'.join(lines)+'\n'
