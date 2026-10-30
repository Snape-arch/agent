"""Explicit, rate-bounded metadata refresh for an already owned paper."""
import json
import uuid
from services.research_watch import fingerprint
from services.research_bibliography import source_records


class ResearchMetadata:
    def __init__(self,watch):
        self.watch,self.store=watch,watch.store
        with self.store._conn() as c:c.execute('''CREATE TABLE IF NOT EXISTS research_metadata_refreshes(
            id TEXT PRIMARY KEY,owner TEXT NOT NULL,created REAL NOT NULL,source TEXT NOT NULL,status TEXT NOT NULL,error TEXT NOT NULL)''')

    @staticmethod
    def owned(c,owner,pid):
        row=c.execute('SELECT * FROM research_watch_papers WHERE owner=? AND id=?',(owner,pid)).fetchone()
        if not row:raise LookupError('论文不存在')
        sub=c.execute('''SELECT s.* FROM research_subscriptions s JOIN research_watch_discoveries d ON s.id=d.subscription_id
            WHERE s.owner=? AND d.paper_id=? ORDER BY s.id LIMIT 1''',(owner,pid)).fetchone()
        if not sub:raise LookupError('该论文已不属于当前订阅')
        return row,sub

    def get(self,owner,pid):
        with self.store._conn() as c:
            self.owned(c,owner,pid)
            rows=c.execute('SELECT * FROM research_watch_snapshots WHERE owner=? AND paper_id=? ORDER BY captured DESC,id',(owner,pid)).fetchall()
            return dict(paper_id=pid,**source_records(rows))

    def refresh(self,owner,pid,data):
        if not isinstance(data,dict) or set(data)-{'source','version'}:raise ValueError('刷新字段无效')
        source,version=data.get('source'),data.get('version')
        if source not in ('crossref','arxiv'):raise ValueError('请选择Crossref或arXiv')
        if version is not None and (type(version) is not int or not 1<=version<=9999 or source!='arxiv'):raise ValueError('版本需为1–9999的arXiv版本号，空白表示最新')
        now=self.watch.clock();token=uuid.uuid4().hex
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');paper,sub=self.owned(c,owner,pid);p=json.loads(paper['payload'])
            identifier=p.get('doi') if source=='crossref' else p.get('arxiv_id')
            if not identifier:raise ValueError('论文尚无此来源的稳定标识，不能凭标题猜测')
            if source=='arxiv' and version:identifier+='v'+str(version)
            lock=c.execute('SELECT * FROM research_watch_collector_lock WHERE id=1').fetchone()
            if lock['lease_until']>now or lock['next_request']>now:raise ValueError('来源采集正在运行或间隔未到，请稍后重试')
            if c.execute('SELECT COUNT(*) FROM research_metadata_refreshes WHERE owner=? AND created>?',(owner,now-3600)).fetchone()[0]>=20:raise ValueError('每人每小时最多20次元数据刷新')
            c.execute('INSERT INTO research_metadata_refreshes VALUES (?,?,?,?,?,?)',(token,owner,now,source,'running',''))
            c.execute('UPDATE research_watch_collector_lock SET token=?,lease_until=?,next_request=? WHERE id=1',(token,now+120,now+max(3.1,self.watch.source_interval)))
        try:
            raw=self.watch.sources.lookup(source,identifier)
            with self.store._conn() as c:
                c.execute('BEGIN IMMEDIATE');_,sub=self.owned(c,owner,pid)
                lock=c.execute('SELECT * FROM research_watch_collector_lock WHERE id=1').fetchone()
                if lock['token']!=token or lock['lease_until']<=self.watch.clock():raise ValueError('刷新租约已失效，结果未写入')
                self.watch._ingest(c,dict(owner=owner,source=source,subscription_id=sub['id'],directions=sub['directions']),raw)
                sha=fingerprint(self.watch.paper(raw,source))
                result=c.execute('SELECT id,paper_id FROM research_watch_snapshots WHERE owner=? AND hash=? ORDER BY captured DESC LIMIT 1',(owner,sha)).fetchone()
                c.execute("UPDATE research_metadata_refreshes SET status='completed' WHERE id=?",(token,))
                return dict(paper_id=result['paper_id'],snapshot_id=result['id'],source=source,
                    boundary='元数据快照已保存，未重写旧日报/综述。重新生成综述后纳入引用与版本记录。')
        except Exception as exc:
            with self.store._conn() as c:c.execute("UPDATE research_metadata_refreshes SET status='failed',error=? WHERE id=?",(type(exc).__name__,token))
            raise
        finally:
            with self.store._conn() as c:self.watch._release_collector(c,dict(token=token))
