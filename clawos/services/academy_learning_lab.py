"""Material-scoped teaching identities and durable education workbench state."""
import json
import secrets
import time
import uuid
from fastapi import HTTPException
from services.collaboration import Collaboration, digest
from services.academy_teaching_quality import AcademyTeachingQuality
from services.textbook_learning_graph import TextbookLearningGraph


class AcademyLearningLab:
    def __init__(self, materials, clock=time.time):
        self.materials=materials;self.store=materials.store;self.clock=clock
        self.identities=Collaboration(self.store)
        with self.store._conn() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS academy_lab_grants(material_id TEXT,user_id TEXT,role TEXT,PRIMARY KEY(material_id,user_id));
            CREATE TABLE IF NOT EXISTS academy_lab_invites(hash TEXT PRIMARY KEY,material_id TEXT,role TEXT,expires REAL,used INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS academy_book_graphs(material_id TEXT PRIMARY KEY,revision TEXT,version INTEGER,payload TEXT,actor TEXT);
            CREATE TABLE IF NOT EXISTS academy_book_indexes(material_id TEXT PRIMARY KEY,revision TEXT,version INTEGER,payload TEXT,actor TEXT);
            CREATE TABLE IF NOT EXISTS academy_book_graph_history(material_id TEXT,version INTEGER,revision TEXT,payload TEXT,actor TEXT,recorded_at REAL,PRIMARY KEY(material_id,version));
            CREATE TABLE IF NOT EXISTS academy_book_index_history(material_id TEXT,version INTEGER,revision TEXT,payload TEXT,actor TEXT,recorded_at REAL,PRIMARY KEY(material_id,version));
            CREATE TABLE IF NOT EXISTS academy_teacher_drafts(material_id TEXT PRIMARY KEY,revision TEXT,version INTEGER,payload TEXT,actor TEXT);
            CREATE TABLE IF NOT EXISTS academy_learning_studies(id TEXT PRIMARY KEY,material_id TEXT,revision TEXT,graph_version INTEGER,payload TEXT,created REAL);
            CREATE TABLE IF NOT EXISTS academy_study_enrollments(study_id TEXT,user_id TEXT,form_offset INTEGER,created REAL,PRIMARY KEY(study_id,user_id));
            CREATE TABLE IF NOT EXISTS academy_study_attempts(id TEXT PRIMARY KEY,study_id TEXT,user_id TEXT,phase TEXT,payload TEXT,created REAL,UNIQUE(study_id,user_id,phase));
            CREATE TABLE IF NOT EXISTS academy_study_grades(attempt_id TEXT,teacher_id TEXT,payload TEXT,created REAL,PRIMARY KEY(attempt_id,teacher_id));
            CREATE TABLE IF NOT EXISTS academy_study_adjudications(attempt_id TEXT PRIMARY KEY,arbiter_id TEXT,payload TEXT,created REAL);
            ''')
            columns={r['name'] for r in c.execute('PRAGMA table_info(academy_study_enrollments)')}
            if 'withdrawn_at' not in columns:c.execute('ALTER TABLE academy_study_enrollments ADD COLUMN withdrawn_at REAL')
            if 'withdrawal_reason' not in columns:c.execute("ALTER TABLE academy_study_enrollments ADD COLUMN withdrawal_reason TEXT NOT NULL DEFAULT ''")
            draft_columns={r['name'] for r in c.execute('PRAGMA table_info(academy_teacher_drafts)')}
            if 'index_version' not in draft_columns:c.execute('ALTER TABLE academy_teacher_drafts ADD COLUMN index_version INTEGER NOT NULL DEFAULT 0')
            invite_columns={r['name'] for r in c.execute('PRAGMA table_info(academy_lab_invites)')}
            if 'target_uid' not in invite_columns:c.execute('ALTER TABLE academy_lab_invites ADD COLUMN target_uid TEXT')
        self.graph=TextbookLearningGraph(self)
        from services.academy_learning_evidence import AcademyLearningEvidence
        self.evidence=AcademyLearningEvidence(self)

    def authorize(self,c,mid,uid,roles=None):
        if uid!='local-user' and not c.execute('SELECT 1 FROM collaboration_sessions WHERE user_id=? AND expires>?',(uid,time.time())).fetchone():
            raise HTTPException(401,'会话已失效')
        row=c.execute('SELECT learner,status FROM academy_materials WHERE id=?',(mid,)).fetchone()
        if not row:raise HTTPException(404,'教材不存在')
        grant=c.execute('SELECT role FROM academy_lab_grants WHERE material_id=? AND user_id=?',(mid,uid)).fetchone()
        role='owner' if row['learner']==uid else grant['role'] if grant else None
        if not role or (roles and role not in roles):raise HTTPException(403,'没有此教材的对应权限')
        if row['status']!='ready':raise ValueError('请先完成教材解析与复核')
        return row['learner'],role

    def books(self,uid):
        with self.store._conn() as c:
            rows=c.execute('SELECT DISTINCT m.id,m.title FROM academy_materials m LEFT JOIN academy_lab_grants g ON g.material_id=m.id WHERE m.status=\'ready\' AND (m.learner=? OR g.user_id=?) ORDER BY m.created_at DESC',(uid,uid)).fetchall()
            return [dict(r,role=self.authorize(c,r['id'],uid)[1]) for r in rows]

    def invite(self,mid,uid,role,target_uid=None):
        if role not in ('teacher','learner'):raise ValueError('请选择教师或学习者')
        code=secrets.token_urlsafe(32);expires=time.time()+86400
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');self.authorize(c,mid,uid,('owner',))
            if target_uid is not None:
                if not isinstance(target_uid,str):raise ValueError('续期身份无效')
                grant=c.execute('SELECT role FROM academy_lab_grants WHERE material_id=? AND user_id=?',(mid,target_uid)).fetchone()
                if not grant or grant['role']!=role:raise ValueError('只能为本教材现有成员续发同权限邀请')
            c.execute('INSERT INTO academy_lab_invites(hash,material_id,role,expires,target_uid) VALUES (?,?,?,?,?)',(digest(code),mid,role,expires,target_uid))
        return dict(code=code,expires=expires,role=role,identity_bound=target_uid is not None)

    def join(self,code,name,existing_uid=None):
        if not isinstance(code,str) or not 20<=len(code)<=100 or not isinstance(name,str) or not 1<=len(name.strip())<=80:raise ValueError('邀请码或姓名无效')
        uid=existing_uid or uuid.uuid4().hex;token=secrets.token_urlsafe(32)
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute('SELECT * FROM academy_lab_invites WHERE hash=? AND used=0 AND expires>?',(digest(code),time.time())).fetchone()
            if not r:raise ValueError('邀请已使用或过期')
            if existing_uid and not c.execute('SELECT 1 FROM collaboration_sessions WHERE user_id=? AND expires>?',(uid,time.time())).fetchone():raise HTTPException(401,'现有会话已失效')
            if r['target_uid']:
                if existing_uid and existing_uid!=r['target_uid']:raise ValueError('续期邀请绑定其他成员，请先退出当前会话')
                grant=c.execute('SELECT role FROM academy_lab_grants WHERE material_id=? AND user_id=?',(r['material_id'],r['target_uid'])).fetchone()
                if not grant or grant['role']!=r['role']:raise ValueError('续期邀请已失效，权限已撤销或变化')
                uid=r['target_uid']
            c.execute('UPDATE academy_lab_invites SET used=1 WHERE hash=?',(digest(code),))
            if not existing_uid and not r['target_uid']:c.execute('INSERT INTO collaboration_users VALUES (?,?)',(uid,name.strip()))
            c.execute('INSERT INTO collaboration_sessions VALUES (?,?,?)',(digest(token),uid,int(time.time())+86400*7))
            c.execute('INSERT INTO academy_lab_grants VALUES (?,?,?) ON CONFLICT(material_id,user_id) DO UPDATE SET role=excluded.role',(r['material_id'],uid,r['role']))
        return dict(user_id=uid,material_id=r['material_id'],role=r['role']),token

    def revoke(self,mid,uid,target):
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');self.authorize(c,mid,uid,('owner',))
            c.execute('DELETE FROM academy_lab_grants WHERE material_id=? AND user_id=?',(mid,target))
        return dict(revoked=True)

    def index(self,document,conn=None):
        from services.textbook_learning_graph import book_index
        def query(c):return c.execute('SELECT * FROM academy_book_indexes WHERE material_id=?',(document['id'],)).fetchone()
        if conn is None:
            with self.store._conn() as c:row=query(c)
        else:row=query(conn)
        current=document['payload']['revision']
        value=json.loads(row['payload']) if row and row['revision']==current else book_index(document)
        starts=[dict(citation=c['sources'][0]['citation'],offset=c['sources'][0]['start'],title=c['title']) for c in value['chapters']]
        if starts:starts[0]['offset']=0
        return dict(value,version=row['version'] if row else 0,manual=bool(row and row['revision']==current),stale=bool(row and row['revision']!=current),starts=starts)

    def passage(self,mid,uid,citation):
        with self.store._conn() as c:owner,_=self.authorize(c,mid,uid)
        passages=self.materials.document(mid,owner)['payload']['passages']
        value=next((p for p in passages if p['id']==citation),None)
        if not value:raise ValueError('原文片段不存在')
        return dict(citation=value['id'],text=value['text'],page=value.get('page'),review_required=bool(value.get('review_required')))

    def preserve(self,c,kind,mid,row):
        if kind not in ('graph','index'):raise ValueError('未知教育版本类型')
        if row is not None:
            c.execute(f'INSERT OR IGNORE INTO academy_book_{kind}_history VALUES (?,?,?,?,?,?)',(mid,row['version'],row['revision'],row['payload'],row['actor'],self.clock()))

    def history(self,mid,uid):
        with self.store._conn() as c:
            self.authorize(c,mid,uid,('owner','teacher'))
            def rows(kind):
                result=[]
                for row in c.execute(f'SELECT * FROM academy_book_{kind}_history WHERE material_id=? ORDER BY version',(mid,)):
                    result.append(dict(version=row['version'],revision=row['revision'],graph=json.loads(row['payload']),actor=row['actor'],recorded_at=row['recorded_at']))
                return result
            return dict(graphs=rows('graph'),directories=rows('index'),boundary='仅记录本功能启用后保存或被替换的版本；recorded_at为归档时间，不虚构早期创作时间。')

    def save_index(self,mid,uid,starts,version,revision):
        if not isinstance(starts,list) or not 1<=len(starts)<=300 or type(version) is not int:raise ValueError('目录需1–300个有序章节起点及整数版本')
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');self.authorize(c,mid,uid,('owner','teacher'))
            row=c.execute('SELECT * FROM academy_materials WHERE id=?',(mid,)).fetchone();doc=dict(row,payload=json.loads(row['payload']))
            if doc['payload']['revision']!=revision:raise ValueError('教材版本已变化')
            old=c.execute('SELECT * FROM academy_book_indexes WHERE material_id=?',(mid,)).fetchone()
            if (old['version'] if old else 0)!=version:raise ValueError('目录版本冲突')
            passages=doc['payload']['passages'];by_id={p['id']:(i,p) for i,p in enumerate(passages)};points=[]
            for start in starts:
                if not isinstance(start,dict) or set(start)!={'citation','offset','title'} or start['citation'] not in by_id or not isinstance(start['title'],str) or not 2<=len(start['title'])<=120:raise ValueError('章节标题与起点无效')
                i,p=by_id[start['citation']];offset=start['offset']
                if type(offset) is not int or not 0<=offset<len(p['text']):raise ValueError('章节起点超出原文范围')
                point=(i,offset)
                if points and point<=points[-1]:raise ValueError('章节起点必须按原文顺序排列且不可重复')
                points.append(point)
            if points[0]!=(0,0):raise ValueError('第一个章节必须从首片段的0位置开始，避免漏掉正文')
            chapters=[]
            for k,(left,start) in enumerate(zip(points,starts)):
                right=points[k+1] if k+1<len(points) else (len(passages)-1,len(passages[-1]['text']))
                spans=[];review=False
                for i in range(left[0],right[0]+1):
                    p=passages[i];begin=left[1] if i==left[0] else 0;end=right[1] if i==right[0] else len(p['text'])
                    if end<=begin:continue
                    spans.append(dict(citation=p['id'],start=begin,end=end,page=p.get('page'),source_url=p['source_url']));review|=bool(p.get('review_required'))
                chapters.append(dict(id=f'ch{k+1:04}',title=start['title'],sources=spans,review_required=review,heading_detected=False))
            value=dict(chapters=chapters,revision=revision,heading_count=0,boundary='人工目录覆盖全部已解析片段；相邻分片可能保留原解析重叠。目录修订会清空旧图谱并使旧测量计划失效。')
            self.preserve(c,'index',mid,old)
            c.execute('INSERT INTO academy_book_indexes VALUES (?,?,?,?,?) ON CONFLICT(material_id) DO UPDATE SET revision=excluded.revision,version=excluded.version,payload=excluded.payload,actor=excluded.actor',(mid,revision,version+1,json.dumps(value,ensure_ascii=False),uid))
            self.preserve(c,'index',mid,c.execute('SELECT * FROM academy_book_indexes WHERE material_id=?',(mid,)).fetchone())
            c.execute('UPDATE academy_teacher_drafts SET version=version+1 WHERE material_id=?',(mid,))
            old_graph=c.execute('SELECT * FROM academy_book_graphs WHERE material_id=?',(mid,)).fetchone()
            self.preserve(c,'graph',mid,old_graph)
            empty=json.dumps(dict(nodes=[],edges=[],covered_chapters=[]))
            c.execute('INSERT INTO academy_book_graphs VALUES (?,?,?,?,?) ON CONFLICT(material_id) DO UPDATE SET revision=excluded.revision,version=excluded.version,payload=excluded.payload,actor=excluded.actor',(mid,revision,(old_graph['version'] if old_graph else 0)+1,empty,uid))
            self.preserve(c,'graph',mid,c.execute('SELECT * FROM academy_book_graphs WHERE material_id=?',(mid,)).fetchone())
        return self.graph.state(mid,uid)

    def state(self,mid,uid):
        with self.store._conn() as c:
            owner,role=self.authorize(c,mid,uid)
            members=[dict(r) for r in c.execute('SELECT g.user_id,g.role,u.name FROM academy_lab_grants g JOIN collaboration_users u ON u.id=g.user_id WHERE material_id=?',(mid,))] if role=='owner' else []
        doc=self.materials.document(mid,owner)
        # Never expose teacher labels, answer keys or study identities to learners.
        data=dict(graph=self.graph.state(mid,uid),studies=self.evidence.list(mid,uid),members=members,
                  identity_independence_verified=False,teacher_qualification_verified=False)
        if role in ('owner','teacher'):
            chapters=data['graph']['index']['chapters']
            data['chapters']=[self.materials.chapter(mid,'book:'+chapter['id'],owner) for chapter in chapters if not chapter['review_required'] and sum(s['end']-s['start'] for s in chapter['sources'])<=40000]
            data['teaching_chapters_excluded']=len(chapters)-len(data['chapters'])
            data['calibration']=AcademyTeachingQuality(self.materials,self.materials.model_profile).status(mid,owner)
            data['teacher_draft']=self.draft(mid,uid)
        return data

    def draft(self,mid,uid):
        with self.store._conn() as c:
            owner,_=self.authorize(c,mid,uid,('owner','teacher'))
            row=c.execute('SELECT * FROM academy_teacher_drafts WHERE material_id=?',(mid,)).fetchone()
        revision=self.materials.document(mid,owner)['payload']['revision']
        index_version=self.index(self.materials.document(mid,owner))['version']
        valid=bool(row and row['revision']==revision and row['index_version']==index_version)
        return dict(version=row['version'] if row else 0,revision=revision,
                    value=json.loads(row['payload']) if valid else dict(cases=[]),
                    stale=bool(row and not valid))

    def save_draft(self,mid,uid,value,version,revision):
        if not isinstance(value,dict) or set(value)-{'cases','teacher','reviewed_at','human_reviewed'} or not isinstance(value.get('cases'),list) or len(value['cases'])>60 or len(json.dumps(value))>600000:raise ValueError('教师草稿无效')
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');owner,_=self.authorize(c,mid,uid,('owner','teacher'))
            doc=c.execute('SELECT payload FROM academy_materials WHERE id=?',(mid,)).fetchone()
            if json.loads(doc['payload'])['revision']!=revision:raise ValueError('教材版本已变化')
            index=c.execute('SELECT version FROM academy_book_indexes WHERE material_id=? AND revision=?',(mid,revision)).fetchone()
            index_version=index['version'] if index else 0
            old=c.execute('SELECT version FROM academy_teacher_drafts WHERE material_id=?',(mid,)).fetchone()
            if type(version) is not int or version!=(old['version'] if old else 0):raise ValueError('教师草稿版本冲突')
            c.execute('INSERT INTO academy_teacher_drafts(material_id,revision,version,payload,actor,index_version) VALUES (?,?,?,?,?,?) ON CONFLICT(material_id) DO UPDATE SET revision=excluded.revision,version=excluded.version,payload=excluded.payload,actor=excluded.actor,index_version=excluded.index_version',(mid,revision,version+1,json.dumps(value,ensure_ascii=False),uid,index_version))
        return self.draft(mid,uid)

    def freeze_bank(self,mid,uid,version):
        # ACL, draft snapshot, validation and bank insertion share the writer lock.
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');owner,_=self.authorize(c,mid,uid,('owner','teacher'))
            row=c.execute('SELECT * FROM academy_teacher_drafts WHERE material_id=?',(mid,)).fetchone()
            if not row or row['version']!=version:raise ValueError('教师草稿版本冲突')
            current=json.loads(c.execute('SELECT payload FROM academy_materials WHERE id=?',(mid,)).fetchone()['payload'])['revision']
            if row['revision']!=current:raise ValueError('教材版本已变化')
            index=c.execute('SELECT version FROM academy_book_indexes WHERE material_id=? AND revision=?',(mid,current)).fetchone()
            if row['index_version']!=(index['version'] if index else 0):raise ValueError('目录版本已变化，教师草稿需重新复核')
            result=AcademyTeachingQuality(self.materials,self.materials.model_profile).import_bank(mid,json.loads(row['payload']),owner,conn=c)
            result['data'].update(authenticated_actor=uid,teacher_qualification_verified=False,identity_independence_verified=False)
            c.execute('UPDATE academy_material_events SET payload=? WHERE id=?',(json.dumps(result['data'],ensure_ascii=False),result['id']))
        return dict(event_id=result['id'],actor=uid,identity_independence_verified=False)
