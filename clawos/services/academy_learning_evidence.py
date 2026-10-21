"""Frozen parallel-form, dual blind-rated observational learning studies.

Authenticated accounts are not independently verified people. No causal claim or
mastery update is derived from these records. Tests use explicitly synthetic data.
"""
import json
import random
import statistics
import uuid
from services.academy_teaching_quality import DIMS, RUBRIC


class AcademyLearningEvidence:
    def __init__(self,lab):self.lab=lab;self.store=lab.store

    def study(self,c,sid,uid,roles=None,live=True):
        row=c.execute('SELECT * FROM academy_learning_studies WHERE id=?',(sid,)).fetchone()
        if not row:raise ValueError('学习验证计划不存在')
        owner,role=self.lab.authorize(c,row['material_id'],uid,roles)
        value=dict(row);value['payload']=json.loads(row['payload'])
        revision=json.loads(c.execute('SELECT payload FROM academy_materials WHERE id=?',(row['material_id'],)).fetchone()['payload'])['revision']
        graph=c.execute('SELECT version FROM academy_book_graphs WHERE material_id=?',(row['material_id'],)).fetchone()
        value['stale']=revision!=row['revision'] or (graph['version'] if graph else 0)!=row['graph_version']
        if live and value['stale']:raise ValueError('教材或图谱已变化，原验证计划仅可查阅；请新建计划')
        return value,owner,role

    def create(self,mid,uid,value,revision,graph_version):
        if not isinstance(value,dict) or set(value)!={'title','chapter','forms','delay_days','min_pairs'}:raise ValueError('计划字段不完整')
        if not isinstance(value['title'],str) or not 4<=len(value['title'])<=120:raise ValueError('计划标题需4–120字符')
        if type(value['delay_days']) is not int or not 7<=value['delay_days']<=90:raise ValueError('延迟测间隔需7–90天')
        if type(value['min_pairs']) is not int or not 12<=value['min_pairs']<=500:raise ValueError('预先约定至少12个完整配对账户')
        forms=value['forms']
        if not isinstance(forms,list) or len(forms)!=3:raise ValueError('需三套平行题，每套概念、推理、迁移三题')
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');owner,_=self.lab.authorize(c,mid,uid,('owner','teacher'))
            doc=json.loads(c.execute('SELECT payload FROM academy_materials WHERE id=?',(mid,)).fetchone()['payload'])
            graph=c.execute('SELECT * FROM academy_book_graphs WHERE material_id=?',(mid,)).fetchone()
            if doc['revision']!=revision or type(graph_version) is not int or (graph['version'] if graph else 0)!=graph_version:raise ValueError('教材或图谱版本冲突')
            if graph and graph['revision']!=revision:raise ValueError('图谱对应旧教材，请重建后冻结计划')
            chapter=self.lab.materials.chapter(mid,value['chapter'],owner)
            seen=set()
            for form in forms:
                if not isinstance(form,list) or len(form)!=3:raise ValueError('每套需三个完整题目')
                for question,dim in zip(form,DIMS):
                    if not isinstance(question,dict) or set(question)!={'dimension','question','criterion','quote','reference_answer'} or question['dimension']!=dim:raise ValueError('题目字段或维度无效')
                    if any(not isinstance(question[k],str) or not 4<=len(question[k])<=2000 for k in ('question','criterion','quote','reference_answer')) or question['quote'] not in chapter['text']:raise ValueError('题目需完整量尺、参考答案和原文引用')
                    if not any(question['quote'] in block for block in chapter.get('source_texts',[chapter['text']])):raise ValueError('题目引用不能跨拼接片段伪造连续原句')
                    normalized=' '.join(question['question'].split()).casefold()
                    if normalized in seen:raise ValueError('平行题不可重复原题')
                    seen.add(normalized)
            sid=uuid.uuid4().hex
            payload=dict(value,rubric=RUBRIC,min_post_seconds=600,creator=uid,
                         form_equivalence_verified=False,causal_effect_verified=False)
            payload.update(graph_snapshot=dict(version=graph_version,revision=revision,**(json.loads(graph['payload']) if graph else dict(nodes=[],edges=[],covered_chapters=[]))),
                           directory_snapshot=self.lab.index(dict(id=mid,payload=doc),conn=c),
                           chapter_snapshot={key:chapter[key] for key in ('id','title','text','citation','revision','sources','source_texts') if key in chapter})
            c.execute('INSERT INTO academy_learning_studies VALUES (?,?,?,?,?,?)',(sid,mid,revision,graph_version,json.dumps(payload,ensure_ascii=False),self.lab.clock()))
        return dict(id=sid)

    def protocol(self,sid,uid):
        with self.store._conn() as c:
            study,_,_=self.study(c,sid,uid,('owner','teacher'),live=False)
            return dict(id=sid,revision=study['revision'],graph_version=study['graph_version'],stale=study['stale'],protocol=study['payload'],snapshot_complete=all(key in study['payload'] for key in ('graph_snapshot','directory_snapshot','chapter_snapshot')),boundary='只导出冻结计划及其教学来源，不包含学习者阶段映射或答卷；旧计划缺少的来源快照不追补、不冒充历史冻结证据。')

    def list(self,mid,uid):
        with self.store._conn() as c:
            self.lab.authorize(c,mid,uid)
            ids=[r['id'] for r in c.execute('SELECT id FROM academy_learning_studies WHERE material_id=? ORDER BY created DESC',(mid,))]
        return [self.view(sid,uid) for sid in ids]

    def view(self,sid,uid):
        with self.store._conn() as c:
            study,owner,role=self.study(c,sid,uid,live=False);p=study['payload']
            enrolled=c.execute('SELECT * FROM academy_study_enrollments WHERE study_id=? AND user_id=?',(sid,uid)).fetchone()
            attempts=[dict(r) for r in c.execute('SELECT id,phase,created FROM academy_study_attempts WHERE study_id=? AND user_id=?',(sid,uid))]
            result=dict(id=sid,title=p['title'],chapter=p['chapter'],delay_days=p['delay_days'],min_pairs=p['min_pairs'],stale=study['stale'],enrolled=bool(enrolled),attempts=attempts,role=role,
                        next_phase=None,eligible_at=None,questions=[],withdrawn=bool(enrolled and enrolled['withdrawn_at'] is not None),boundary='前后变化是观察记录；题组等值、真实人员独立性及平台因果效果尚未认证。')
            if enrolled and enrolled['withdrawn_at'] is None:
                by_phase={r['phase']:r for r in attempts}
                phase=next((x for x in ('pre','post','delayed') if x not in by_phase),None)
                result['next_phase']=phase
                if phase:
                    eligible=enrolled['created'] if phase=='pre' else by_phase['pre']['created']+p['min_post_seconds'] if phase=='post' else by_phase['post']['created']+p['delay_days']*86400
                    result['eligible_at']=eligible
                    if self.lab.clock()>=eligible and not study['stale']:
                        form=p['forms'][(enrolled['form_offset']+('pre','post','delayed').index(phase))%3]
                        # Answer key, teacher rubric and source quote remain private.
                        result['questions']=[dict(dimension=q['dimension'],question=q['question']) for q in form]
            return result

    def enroll(self,sid,uid):
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');self.study(c,sid,uid,('owner','learner'))
            count=c.execute('SELECT count(*) AS n FROM academy_study_enrollments WHERE study_id=?',(sid,)).fetchone()['n']
            c.execute('INSERT OR IGNORE INTO academy_study_enrollments(study_id,user_id,form_offset,created) VALUES (?,?,?,?)',(sid,uid,count%3,self.lab.clock()))
        return self.view(sid,uid)

    def withdraw(self,sid,uid,reason):
        if not isinstance(reason,str) or not 4<=len(reason)<=1000:raise ValueError('请简述退出原因')
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');self.study(c,sid,uid,('owner','learner'),live=False)
            row=c.execute('SELECT * FROM academy_study_enrollments WHERE study_id=? AND user_id=?',(sid,uid)).fetchone()
            if not row:raise ValueError('尚未报名')
            c.execute('UPDATE academy_study_enrollments SET withdrawn_at=?,withdrawal_reason=? WHERE study_id=? AND user_id=? AND withdrawn_at IS NULL',(self.lab.clock(),reason,sid,uid))
        return self.view(sid,uid)

    def answer(self,sid,uid,phase,answers,activity=''):
        if phase not in ('pre','post','delayed') or not isinstance(answers,list) or len(answers)!=3 or any(not isinstance(a,str) or not 4<=len(a)<=6000 for a in answers):raise ValueError('需三个实际回答')
        if not isinstance(activity,str) or len(activity)>3000 or (phase=='post' and len(activity.strip())<10):raise ValueError('后测请记录实际学习活动；活动描述本身不证明掌握')
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');study,_,_=self.study(c,sid,uid,('owner','learner'))
            # Reads on another connection observe committed attempts while this writer lock prevents races.
            view=self.view(sid,uid)
            if view['next_phase']!=phase or not view['questions']:raise ValueError('尚未到测量时间、未报名或已提交；回答不可覆盖')
            enrollment=c.execute('SELECT form_offset FROM academy_study_enrollments WHERE study_id=? AND user_id=?',(sid,uid)).fetchone()
            index=(enrollment['form_offset']+('pre','post','delayed').index(phase))%3
            c.execute('INSERT INTO academy_study_attempts VALUES (?,?,?,?,?,?)',(uuid.uuid4().hex,sid,uid,phase,json.dumps(dict(answers=answers,form=index,activity=activity),ensure_ascii=False),self.lab.clock()))
        return self.view(sid,uid)

    def packets(self,sid,uid,adjudication=False):
        with self.store._conn() as c:
            study,owner,_=self.study(c,sid,uid,('owner','teacher'));p=study['payload']
            chapter=p.get('chapter_snapshot') or self.lab.materials.chapter(study['material_id'],p['chapter'],owner)
            rows=c.execute('SELECT a.* FROM academy_study_attempts a WHERE study_id=? AND user_id!=? AND NOT EXISTS(SELECT 1 FROM academy_study_grades g WHERE g.attempt_id=a.id AND g.teacher_id=?) AND NOT EXISTS(SELECT 1 FROM academy_study_adjudications j WHERE j.attempt_id=a.id) ORDER BY a.id',(sid,uid,uid)).fetchall()
            results=[]
            for r in rows:
                grades=[json.loads(g['payload']) for g in c.execute('SELECT payload FROM academy_study_grades WHERE attempt_id=? ORDER BY teacher_id',(r['id'],))]
                disputed=len(grades)>=2 and any(g['scores']!=grades[0]['scores'] for g in grades[1:])
                if adjudication and not disputed:continue
                payload=dict(packet_id=r['id'],questions=p['forms'][json.loads(r['payload'])['form']],answers=json.loads(r['payload'])['answers'],source=chapter['text'],rubric=p['rubric'])
                if adjudication:payload.update(disputed_grades=grades,adjudication=True)
                results.append(payload)
            return results

    def grade(self,sid,uid,aid,scores,reason,quotes,adjudication=False):
        if not isinstance(scores,dict) or set(scores)!=set(DIMS) or any(type(v) is not int or v not in (0,1,2) for v in scores.values()):raise ValueError('三个维度各需0/1/2整数')
        if not isinstance(reason,str) or not 10<=len(reason)<=3000 or not isinstance(quotes,list) or len(quotes)!=3:raise ValueError('请填写评分依据和三个学生原句')
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');self.study(c,sid,uid,('owner','teacher'))
            row=c.execute('SELECT * FROM academy_study_attempts WHERE id=? AND study_id=?',(aid,sid)).fetchone()
            if not row or row['user_id']==uid:raise ValueError('不能评阅自己的回答或无效答卷')
            if c.execute('SELECT 1 FROM academy_study_adjudications WHERE attempt_id=?',(aid,)).fetchone():raise ValueError('仲裁已冻结，不再接收新增评分')
            answers=json.loads(row['payload'])['answers']
            if any(not isinstance(q,str) or (q and q not in a) or (scores[d]>0 and len(q)<4) for q,a,d in zip(quotes,answers,DIMS)):raise ValueError('正分须定位对应学生原句')
            if c.execute('SELECT 1 FROM academy_study_grades WHERE attempt_id=? AND teacher_id=?',(aid,uid)).fetchone():raise ValueError('盲评已提交，不可覆盖')
            payload=json.dumps(dict(scores=scores,reason=reason,quotes=quotes),ensure_ascii=False)
            if adjudication:
                rows=[json.loads(r['payload']) for r in c.execute('SELECT payload FROM academy_study_grades WHERE attempt_id=?',(aid,))]
                if len(rows)<2 or all(r['scores']==rows[0]['scores'] for r in rows[1:]):raise ValueError('只有双人盲评发生分歧的答卷可仲裁')
                c.execute('INSERT INTO academy_study_adjudications VALUES (?,?,?,?)',(aid,uid,payload,self.lab.clock()))
            else:c.execute('INSERT INTO academy_study_grades VALUES (?,?,?,?)',(aid,uid,payload,self.lab.clock()))
        return dict(saved=True)

    def report(self,sid,uid):
        with self.store._conn() as c:
            study,_,_=self.study(c,sid,uid,('owner','teacher'),live=False)
            enrollments=c.execute('SELECT user_id,withdrawn_at FROM academy_study_enrollments WHERE study_id=?',(sid,)).fetchall()
            attempts=c.execute('SELECT * FROM academy_study_attempts WHERE study_id=?',(sid,)).fetchall()
            grades={r['id']:[json.loads(g['payload']) for g in c.execute('SELECT payload FROM academy_study_grades WHERE attempt_id=? ORDER BY teacher_id',(r['id'],))] for r in attempts}
            adjudications={r['id']:c.execute('SELECT payload FROM academy_study_adjudications WHERE attempt_id=?',(r['id'],)).fetchone() for r in attempts}
        counts={x:0 for x in ('pre','post','delayed')};scores={};disputes=0;pending=0;resolved=0
        for r in attempts:
            counts[r['phase']]+=1;rows=grades[r['id']]
            if len(rows)<2:pending+=1;continue
            final=rows[0]['scores']
            if any(g['scores']!=final for g in rows[1:]):
                disputes+=1
                if not adjudications[r['id']]:continue
                final=json.loads(adjudications[r['id']]['payload'])['scores'];resolved+=1
            scores.setdefault(r['user_id'],{})[r['phase']]=sum(final.values())
        withdrawn={r['user_id'] for r in enrollments if r['withdrawn_at'] is not None}
        paired=[p for key,p in scores.items() if key not in withdrawn and set(p)==set(counts)]
        gains=[p['post']-p['pre'] for p in paired];retained=[p['delayed']-p['pre'] for p in paired]
        def estimate(values):
            if not values:return dict(mean=None,ci95=None,n=0)
            rng=random.Random(781);means=sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(2000)) if len(values)>1 else []
            return dict(mean=round(statistics.mean(values),4),ci95=[round(means[49],4),round(means[1949],4)] if means else None,n=len(values))
        p=study['payload'];complete=len(paired);minimum=p['min_pairs']
        return dict(enrolled=len(enrollments),withdrawn_accounts=len(withdrawn),submitted=counts,missing={k:len(enrollments)-v for k,v in counts.items()},pending_blind_review=pending,disputed_attempts=disputes,adjudicated_attempts=resolved,unresolved_disputes=disputes-resolved,
                    complete_paired_accounts=complete,min_pairs=minimum,post_gain=estimate(gains),delayed_gain=estimate(retained),stale=study['stale'],
                    status='stale' if study['stale'] else 'observed_change' if complete>=minimum and disputes==resolved else 'collecting',
                    identity_independence_verified=False,teacher_qualification_verified=False,form_equivalence_verified=False,causal_effect_verified=False,real_learning_effect_verified=False,
                    revision=study['revision'],graph_version=study['graph_version'],rubric=p['rubric'],
                    boundary='完整配对要求三阶段及至少两名不同账户盲评；分歧由未参与原评分的第三账户仲裁，否则暂不纳入。仲裁与原评分均保留，不可覆盖。置信区间按学习者配对重采样，仅描述完成者；缺测和退出单列。账户数不是独立真人认证，观察变化不能证明平台因果效果。')
