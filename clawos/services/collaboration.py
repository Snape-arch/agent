"""Server-issued identities, document ACLs, anchored comments and presence.

Local owner is trusted only on a direct loopback connection. Forwarded headers
are never identity. Remote users join a single-use invitation and get an opaque,
revocable HttpOnly session; neither learner_id nor claimed user_id grants access.
"""
import hashlib
import json
import secrets
import time
import uuid
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

ROLES = {'viewer': 1, 'commenter': 2, 'editor': 3, 'owner': 4}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def direct_owner(request):
    return bool(request.client and request.client.host in ('127.0.0.1','::1')
        and not request.headers.get('authorization') and not request.cookies.get('clawos_session')
        and not any(request.headers.get(k) for k in ('forwarded','x-forwarded-for','x-real-ip')))


class Collaboration:
    def __init__(self, store):
        self.store = store
        with store._conn() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS collaboration_users(id TEXT PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS collaboration_sessions(hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS collaboration_grants(document_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, PRIMARY KEY(document_id,user_id));
            CREATE TABLE IF NOT EXISTS collaboration_invites(hash TEXT PRIMARY KEY, document_id TEXT NOT NULL, role TEXT NOT NULL, expires INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS collaboration_comments(id TEXT PRIMARY KEY, document_id TEXT NOT NULL, user_id TEXT NOT NULL, block_id TEXT NOT NULL, version INTEGER NOT NULL, text TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT (datetime('now')));
            CREATE TABLE IF NOT EXISTS collaboration_presence(document_id TEXT NOT NULL, user_id TEXT NOT NULL, seen INTEGER NOT NULL, block_id TEXT NOT NULL DEFAULT '', PRIMARY KEY(document_id,user_id));
            CREATE TABLE IF NOT EXISTS collaboration_cursors(document_id TEXT NOT NULL,user_id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(document_id,user_id));
            CREATE TABLE IF NOT EXISTS collaboration_audit(id INTEGER PRIMARY KEY, document_id TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')));
            INSERT OR IGNORE INTO collaboration_users VALUES ('local-user','本机所有者');
            ''')

    def identity(self, request):
        token = request.headers.get('authorization', '')
        token = token[7:] if token.startswith('Bearer ') else request.cookies.get('clawos_session', '')
        if token:
            with self.store._conn() as c:
                row = c.execute('SELECT u.id,u.name FROM collaboration_sessions s JOIN collaboration_users u ON u.id=s.user_id WHERE s.hash=? AND s.expires>?', (digest(token), int(time.time()))).fetchone()
            if not row:
                raise HTTPException(401, '会话已过期或撤销，请重新加入协作。')
            return dict(row)
        if direct_owner(request):
            return dict(id='local-user', name='本机所有者')
        raise HTTPException(401, '需要协作会话；前端指定的身份不作为授权依据。')

    def role(self, nid, uid, conn=None):
        def query(c):
            row = c.execute('SELECT learner FROM academy_documents WHERE id=?', (nid,)).fetchone()
            if not row:
                raise HTTPException(404, '文档不存在')
            if uid == row['learner']:
                return 'owner'
            grant = c.execute('SELECT role FROM collaboration_grants WHERE document_id=? AND user_id=?', (nid, uid)).fetchone()
            if not grant:
                raise HTTPException(403, '没有此文档的访问权限')
            return grant['role']
        if conn is not None:
            return query(conn)
        with self.store._conn() as c:
            return query(c)

    def require(self, nid, uid, minimum='viewer', conn=None):
        role = self.role(nid, uid, conn)
        if ROLES[role] < ROLES[minimum]:
            raise HTTPException(403, '此操作需要 '+minimum+' 权限')
        return role

    @staticmethod
    def audit(c, nid, uid, action, detail):
        c.execute('INSERT INTO collaboration_audit(document_id,actor,action,detail) VALUES (?,?,?,?)', (nid, uid, action, json.dumps(detail, ensure_ascii=False)))

    def invite(self, nid, uid, role):
        if role not in ('viewer', 'commenter', 'editor'):
            raise HTTPException(400, '邀请角色无效')
        code = secrets.token_urlsafe(32)
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            self.require(nid, uid, 'owner', c)
            expires = int(time.time())+86400
            c.execute('INSERT INTO collaboration_invites(hash,document_id,role,expires) VALUES (?,?,?,?)', (digest(code), nid, role, expires))
            self.audit(c, nid, uid, 'invite', dict(role=role))
        return dict(code=code, expires=expires, role=role, boundary='单次加入，24 小时有效；请私下提供给指定协作者。')

    def join(self, code, name):
        if not isinstance(code, str) or not 20 <= len(code) <= 100 or not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise HTTPException(400, '请输入有效邀请码和显示名称')
        uid = uuid.uuid4().hex
        token = secrets.token_urlsafe(32)
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM collaboration_invites WHERE hash=? AND used=0 AND expires>?', (digest(code), int(time.time()))).fetchone()
            if not row:
                raise HTTPException(403, '邀请已失效或已被使用')
            # A deleted source document must not yield a usable grant.
            if not c.execute('SELECT 1 FROM academy_documents WHERE id=?', (row['document_id'],)).fetchone():
                raise HTTPException(404, '邀请文档不存在')
            c.execute('UPDATE collaboration_invites SET used=1 WHERE hash=?', (digest(code),))
            c.execute('INSERT INTO collaboration_users VALUES (?,?)', (uid, name.strip()))
            c.execute('INSERT INTO collaboration_sessions VALUES (?,?,?)', (digest(token), uid, int(time.time())+604800))
            c.execute('INSERT INTO collaboration_grants VALUES (?,?,?)', (row['document_id'], uid, row['role']))
            self.audit(c, row['document_id'], uid, 'join', dict(role=row['role']))
        return token, dict(id=uid, name=name.strip(), document_id=row['document_id'], role=row['role'])

    def state(self, nid, uid):
        with self.store._conn() as c:
            role = self.require(nid, uid, conn=c)
            version = c.execute('SELECT version FROM academy_documents WHERE id=?', (nid,)).fetchone()['version']
            comments = [dict(r) for r in c.execute('SELECT m.*,u.name FROM collaboration_comments m JOIN collaboration_users u ON u.id=m.user_id WHERE m.document_id=? ORDER BY m.created_at,m.id', (nid,))]
            online = [dict(r) for r in c.execute('SELECT p.user_id,u.name,p.block_id FROM collaboration_presence p JOIN collaboration_users u ON u.id=p.user_id WHERE p.document_id=? AND p.seen>?', (nid, int(time.time())-35))]
            # Owner also appears in the member list, allowing the UI to identify it.
            members = [dict(r) for r in c.execute("SELECT g.user_id,u.name,g.role FROM collaboration_grants g JOIN collaboration_users u ON u.id=g.user_id WHERE g.document_id=? UNION SELECT d.learner,u.name,'owner' FROM academy_documents d JOIN collaboration_users u ON u.id=d.learner WHERE d.id=?", (nid, nid))]
            audit = [dict(r) for r in c.execute('SELECT actor,action,detail,created_at FROM collaboration_audit WHERE document_id=? ORDER BY id DESC LIMIT 50', (nid,))] if role == 'owner' else []
        return dict(viewer_id=uid, role=role, version=version, comments=comments, online=online, members=members, audit=audit)

    def cursors(self,nid,uid):
        with self.store._conn() as c:
            self.require(nid,uid,conn=c)
            online=[dict(r) for r in c.execute('SELECT p.user_id,u.name,x.payload FROM collaboration_presence p JOIN collaboration_users u ON u.id=p.user_id JOIN collaboration_cursors x ON x.document_id=p.document_id AND x.user_id=p.user_id WHERE p.document_id=? AND p.seen>?',(nid,int(time.time())-35))]
        return dict(cursors=[dict(user_id=r['user_id'],name=r['name'],**json.loads(r['payload'])) for r in online])

    def presence(self,nid,uid,data):
        from .document_cursor import heartbeat
        return heartbeat(self,nid,uid,data)

    def revoke(self, nid, uid, target):
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            self.require(nid, uid, 'owner', c)
            c.execute('DELETE FROM collaboration_grants WHERE document_id=? AND user_id=?', (nid, target))
            c.execute('DELETE FROM collaboration_presence WHERE document_id=? AND user_id=?', (nid, target))
            # Outstanding invitations must be revocable too.
            c.execute('UPDATE collaboration_invites SET used=1 WHERE document_id=?', (nid,))
            self.audit(c, nid, uid, 'revoke', dict(user_id=target))
        return dict(revoked=True)

    def comment(self, nid, uid, data):
        text = data.get('text')
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
            raise HTTPException(400, '评论需要 1–2000 字')
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            self.require(nid, uid, 'commenter', c)
            row = c.execute('SELECT version,payload FROM academy_documents WHERE id=?', (nid,)).fetchone()
            if data.get('version') != row['version']:
                raise HTTPException(409, '文档版本已变化，请重新定位评论')
            bid = data.get('block_id', '')
            if bid and bid not in {b['id'] for b in json.loads(row['payload'])['blocks']}:
                raise HTTPException(400, '评论锚点不在当前文档')
            cid = uuid.uuid4().hex
            c.execute('INSERT INTO collaboration_comments(id,document_id,user_id,block_id,version,text) VALUES (?,?,?,?,?,?)', (cid, nid, uid, bid, row['version'], text.strip()))
            self.audit(c, nid, uid, 'comment', dict(comment_id=cid, version=row['version']))
        return dict(id=cid)


class AuthorizedDocuments:
    """Adapter for the existing document API; all ownership is server-derived."""
    def __init__(self, documents, access, uid):
        self.documents, self.access, self.uid = documents, access, uid

    def owner(self, nid, minimum='viewer'):
        self.access.require(nid, self.uid, minimum)
        with self.documents.store._conn() as c:
            return c.execute('SELECT learner FROM academy_documents WHERE id=?', (nid,)).fetchone()['learner']

    def index(self, learner=None):
        with self.documents.store._conn() as c:
            rows = c.execute('SELECT d.id,d.version,d.updated_at,d.payload,d.learner,g.role FROM academy_documents d LEFT JOIN collaboration_grants g ON g.document_id=d.id AND g.user_id=? WHERE d.learner=? OR g.user_id=? ORDER BY d.updated_at DESC', (self.uid, self.uid, self.uid)).fetchall()
        return dict(documents=[dict(id=r['id'], version=r['version'], updated_at=r['updated_at'], title=json.loads(r['payload'])['title'], role='owner' if r['learner']==self.uid else r['role']) for r in rows])

    def get(self, nid, learner=None):
        result = self.documents.get(nid, self.owner(nid))
        result['role'] = self.access.role(nid, self.uid)
        return result

    def save(self, value, nid=None, learner=None):
        if not nid and self.uid != 'local-user':
            raise HTTPException(403, '邀请会话仅可访问已授权文档')
        owner = self.owner(nid, 'editor') if nid else self.uid
        callback = lambda c: (self.access.require(nid, self.uid, 'editor', c), self.access.audit(c, nid, self.uid, 'edit', dict(version=value.get('version')))) if nid else None
        result = self.documents.save(value, nid, owner, authorize=callback)
        result['role'] = self.access.role(result['id'], self.uid)
        return result

    def history(self, nid, learner=None):
        return self.documents.history(nid, self.owner(nid))

    def markdown(self, doc):
        return self.documents.markdown(doc)


def collaboration_router(factory):
    from starlette.concurrency import run_in_threadpool
    router = APIRouter(prefix='/api/collaboration')
    def invoke(request,name,nid,data):
        s=factory();return getattr(s,name)(nid,s.identity(request)['id'],data)
    @router.get('/me')
    def me(request: Request):
        return factory().identity(request)
    @router.post('/join')
    async def join(request: Request):
        d = await request.json()
        token, user = await run_in_threadpool(lambda:factory().join(d.get('code'), d.get('name')))
        response = JSONResponse(user)
        response.set_cookie('clawos_session', token, max_age=604800, httponly=True, samesite='strict', secure=request.url.scheme=='https')
        return response
    @router.post('/logout')
    def logout(request: Request):
        authorization=request.headers.get('authorization','')
        token = authorization[7:] if authorization.startswith('Bearer ') else request.cookies.get('clawos_session', '')
        with factory().store._conn() as c:
            c.execute('DELETE FROM collaboration_sessions WHERE hash=?', (digest(token),))
        response = JSONResponse(dict(logged_out=True)); response.delete_cookie('clawos_session')
        return response
    @router.get('/documents/{nid}')
    def state(nid: str, request: Request):
        s=factory(); return s.state(nid, s.identity(request)['id'])
    @router.post('/documents/{nid}/invite')
    async def invite(nid: str, request: Request):
        d=await request.json();return await run_in_threadpool(invoke,request,'invite',nid,d.get('role'))
    @router.post('/documents/{nid}/revoke')
    async def revoke(nid: str, request: Request):
        d=await request.json();return await run_in_threadpool(invoke,request,'revoke',nid,d.get('user_id',''))
    @router.post('/documents/{nid}/comments')
    async def comment(nid: str, request: Request):
        return await run_in_threadpool(invoke,request,'comment',nid,await request.json())
    @router.post('/documents/{nid}/comments/{cid}/resolve')
    def resolve(nid: str, cid: str, request: Request):
        s=factory(); uid=s.identity(request)['id']
        with s.store._conn() as c:
            c.execute('BEGIN IMMEDIATE'); role=s.require(nid, uid, 'commenter', c)
            row=c.execute('SELECT user_id FROM collaboration_comments WHERE id=? AND document_id=?', (cid,nid)).fetchone()
            if not row: raise HTTPException(404, '评论不存在')
            if role!='owner' and row['user_id']!=uid: raise HTTPException(403, '仅作者或所有者可解决此评论')
            c.execute('UPDATE collaboration_comments SET resolved=1 WHERE id=?', (cid,));s.audit(c,nid,uid,'resolve',dict(comment_id=cid))
        return dict(resolved=True)
    @router.post('/documents/{nid}/presence')
    async def presence(nid: str, request: Request):
        d=await request.json();return await run_in_threadpool(heartbeat,nid,request,d)
    def heartbeat(nid,request,d):
        s=factory();uid=s.identity(request)['id']
        return s.presence(nid,uid,d)
    return router
