"""Durable, owner-scoped subscriptions with transactional outbox and cited extracts."""
import asyncio
import hashlib
import json
import re
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

from services.research_watch_sources import SOURCE_INFO, WatchSources, clean, safe_url


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def fingerprint(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


def normalized(value):
    return re.sub(r'[^\w\u4e00-\u9fff]', '', unicodedata.normalize('NFKC', str(value)).casefold())


def doi(value):
    value = re.sub(r'^(https?://(dx\.)?doi\.org/|doi:\s*)', '', str(value or '').strip(), flags=re.I).lower()
    return value if re.fullmatch(r'10\.\d{4,9}/\S{1,500}', value) else ''


def classify(paper, directions):
    """Explainable multilabel matches. Never a claim of an authoritative taxonomy."""
    fields = {k: normalized(' '.join(paper[k]) if isinstance(paper[k], list) else paper[k])
              for k in ('title', 'abstract', 'categories')}
    matches = []
    for direction in directions:
        hits = [dict(term=term, field=field) for term in direction['terms']
                for field, text in fields.items() if normalized(term) and normalized(term) in text]
        if hits:
            matches.append(dict(name=direction['name'], evidence=hits, method='keyword.v1', review_required=True))
    return matches or [dict(name='待归类', evidence=[], method='keyword.v1', review_required=True)]


def summary(paper, snapshot_id):
    field = 'abstract' if paper.get('abstract') else 'title'
    text = paper[field]
    # Exact contiguous passage with reproducible offsets, not generated findings.
    quote = text[:900]
    return dict(text=quote, mode='source_extract', basis=field, full_text_reviewed=False,
                boundary='摘要摘录，未经全文或独立实验核验。' if field == 'abstract' else '来源缺少摘要，仅展示标题；不能据此判断方法与效果。',
                evidence=dict(snapshot_id=snapshot_id, field=field, start=0, end=len(quote), quote=quote,
                              source_url=paper['url'], content_sha256=fingerprint(paper)))


class ResearchWatch:
    def __init__(self, store, sources=None, clock=time.time, source_interval=3.1):
        self.store, self.sources, self.clock = store, sources or WatchSources(), clock
        self.source_interval = source_interval
        with store._conn() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS research_subscriptions(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,name TEXT NOT NULL,query TEXT NOT NULL,
                directions TEXT NOT NULL,sources TEXT NOT NULL,interval_hours INTEGER NOT NULL,
                enabled INTEGER NOT NULL,created REAL NOT NULL,version INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS research_watch_jobs(
                subscription_id TEXT NOT NULL,source TEXT NOT NULL,watermark REAL NOT NULL DEFAULT 0,
                window_start REAL NOT NULL DEFAULT 0,window_end REAL NOT NULL DEFAULT 0,cursor TEXT NOT NULL DEFAULT '',
                next_due REAL NOT NULL,token TEXT NOT NULL DEFAULT '',lease_until REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',last_success REAL NOT NULL DEFAULT 0,last_error TEXT NOT NULL DEFAULT '',
                scanned INTEGER NOT NULL DEFAULT 0,new_count INTEGER NOT NULL DEFAULT 0,pages INTEGER NOT NULL DEFAULT 0,
                last_page_hash TEXT NOT NULL DEFAULT '',PRIMARY KEY(subscription_id,source));
            CREATE TABLE IF NOT EXISTS research_watch_papers(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS research_watch_owner ON research_watch_papers(owner,updated);
            CREATE TABLE IF NOT EXISTS research_watch_aliases(
                owner TEXT NOT NULL,kind TEXT NOT NULL,value TEXT NOT NULL,paper_id TEXT NOT NULL,
                PRIMARY KEY(owner,kind,value,paper_id));
            CREATE INDEX IF NOT EXISTS research_watch_alias_lookup ON research_watch_aliases(owner,kind,value);
            CREATE TABLE IF NOT EXISTS research_watch_snapshots(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,paper_id TEXT NOT NULL,hash TEXT NOT NULL,
                captured REAL NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS research_watch_snapshot_lookup ON research_watch_snapshots(owner,paper_id,hash);
            CREATE TABLE IF NOT EXISTS research_watch_discoveries(
                subscription_id TEXT NOT NULL,paper_id TEXT NOT NULL,snapshot_id TEXT NOT NULL,
                discovered REAL NOT NULL,classification TEXT NOT NULL,PRIMARY KEY(subscription_id,paper_id));
            CREATE TABLE IF NOT EXISTS research_watch_digests(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,day TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,
                UNIQUE(owner,day));
            CREATE TABLE IF NOT EXISTS research_watch_digest_entries(
                digest_id TEXT NOT NULL,subscription_id TEXT NOT NULL,paper_id TEXT NOT NULL,snapshot_id TEXT NOT NULL,
                PRIMARY KEY(digest_id,subscription_id,paper_id));
            CREATE TABLE IF NOT EXISTS research_watch_notifications(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,digest_id TEXT NOT NULL,subscription_id TEXT NOT NULL,
                new_count INTEGER NOT NULL,created REAL NOT NULL,read_at REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS research_watch_collector_lock(
                id INTEGER PRIMARY KEY,token TEXT NOT NULL,lease_until REAL NOT NULL,next_request REAL NOT NULL);
            INSERT OR IGNORE INTO research_watch_collector_lock VALUES (1,'',0,0);
            ''')

    def create(self, owner, data):
        if not isinstance(data, dict) or set(data) - {'name', 'query', 'directions', 'sources', 'interval_hours'}:
            raise ValueError('订阅字段无效')
        name, query = data.get('name'), data.get('query')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError('方向名称应为 1–80 字')
        if not isinstance(query, str) or not 3 <= len(query.strip()) <= 240 or not re.search(r'\w', query):
            raise ValueError('检索词应为 3–240 字，建议使用英文关键词')
        interval = data.get('interval_hours', 6)
        if type(interval) is not int or interval not in (6, 12, 24, 48, 168):
            raise ValueError('采集间隔可选 6、12、24、48、168 小时')
        sources = data.get('sources', ['crossref', 'arxiv'])
        if not isinstance(sources, list) or not sources or len(sources) > 2 or any(s not in SOURCE_INFO for s in sources):
            raise ValueError('请选择 Crossref 或 arXiv')
        directions = data.get('directions')
        if not isinstance(directions, list) or not 1 <= len(directions) <= 12:
            raise ValueError('请设置 1–12 个归类方向')
        for d in directions:
            if not isinstance(d, dict) or set(d) != {'name', 'terms'} or not isinstance(d['name'], str) or not 1 <= len(d['name'].strip()) <= 60:
                raise ValueError('归类方向名称无效')
            if not isinstance(d['terms'], list) or not 1 <= len(d['terms']) <= 12 or any(not isinstance(t, str) or not 1 <= len(t.strip()) <= 80 or not normalized(t) for t in d['terms']):
                raise ValueError('每个方向需要 1–12 个关键词')
        sid, now = uuid.uuid4().hex, self.clock()
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT COUNT(*) FROM research_subscriptions WHERE owner=?', (owner,)).fetchone()[0] >= 20 or c.execute('SELECT COUNT(*) FROM research_subscriptions').fetchone()[0] >= 100:
                raise ValueError('订阅已达上限（每人 20，全站 100），请暂停或删除不需要的方向')
            c.execute('INSERT INTO research_subscriptions VALUES (?,?,?,?,?,?,?,?,?,1)',
                      (sid, owner, name.strip(), query.strip(), packed(directions), packed(sorted(set(sources))), interval, 1, now))
            for source in set(sources):
                c.execute('INSERT INTO research_watch_jobs(subscription_id,source,next_due) VALUES (?,?,?)', (sid, source, now))
        return {'id': sid}

    @staticmethod
    def owned(c, owner, sid):
        row = c.execute('SELECT * FROM research_subscriptions WHERE id=? AND owner=?', (sid, owner)).fetchone()
        if not row:
            raise LookupError('订阅不存在')
        return row

    def action(self, owner, sid, action):
        now = self.clock()
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            sub = self.owned(c, owner, sid)
            if action in ('pause', 'resume'):
                c.execute('UPDATE research_subscriptions SET enabled=?,version=version+1 WHERE id=?', (int(action == 'resume'), sid))
                c.execute("UPDATE research_watch_jobs SET token='',lease_until=0,status='pending',next_due=? WHERE subscription_id=?", (now, sid))
            elif action == 'collect':
                if not sub['enabled']:
                    raise ValueError('请先恢复订阅')
                # Manual requests do not bypass an active lease or source failure backoff.
                c.execute("UPDATE research_watch_jobs SET next_due=? WHERE subscription_id=? AND lease_until<=? AND last_error=''", (now, sid, now))
            elif action == 'delete':
                c.execute('DELETE FROM research_watch_jobs WHERE subscription_id=?', (sid,))
                c.execute('DELETE FROM research_subscriptions WHERE id=?', (sid,))
            else:
                raise ValueError('未知操作')
        return {'queued': action == 'collect', 'action': action}

    def claim(self):
        now, token = self.clock(), uuid.uuid4().hex
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            lock = c.execute('SELECT * FROM research_watch_collector_lock WHERE id=1').fetchone()
            if lock['lease_until'] > now or lock['next_request'] > now:
                return None
            row = c.execute('''SELECT j.*,s.owner,s.name,s.query,s.directions,s.interval_hours,s.version
                FROM research_watch_jobs j JOIN research_subscriptions s ON s.id=j.subscription_id
                WHERE s.enabled=1 AND j.next_due<=? AND j.lease_until<=? ORDER BY j.next_due,j.subscription_id,j.source LIMIT 1''', (now, now)).fetchone()
            if not row:
                return None
            job = dict(row)
            if not job['window_end']:
                job.update(window_start=max(0, job['watermark'] - 7*86400) if job['watermark'] else now-30*86400,
                           window_end=now, cursor='')
            job['token'] = token
            c.execute("UPDATE research_watch_jobs SET token=?,lease_until=?,window_start=?,window_end=?,status='collecting' WHERE subscription_id=? AND source=?",
                      (token, now+120, job['window_start'], job['window_end'], job['subscription_id'], job['source']))
            c.execute('UPDATE research_watch_collector_lock SET token=?,lease_until=?,next_request=? WHERE id=1', (token, now+120, now+self.source_interval))
            return job

    @staticmethod
    def _release_collector(c, job):
        c.execute("UPDATE research_watch_collector_lock SET token='',lease_until=0 WHERE id=1 AND token=?", (job['token'],))

    def _valid(self, c, job):
        return c.execute('''SELECT j.* FROM research_watch_jobs j JOIN research_subscriptions s ON s.id=j.subscription_id
            WHERE j.subscription_id=? AND j.source=? AND j.token=? AND j.lease_until>? AND s.enabled=1 AND s.version=?''',
                         (job['subscription_id'], job['source'], job['token'], self.clock(), job['version'])).fetchone()

    @staticmethod
    def paper(raw, source):
        from services.research_bibliography import metadata_fields,arxiv_parts
        title = clean(raw.get('title'), 1000)
        if not title:
            raise ValueError('来源记录缺少标题')
        ax,_ = arxiv_parts(raw.get('arxiv_id'))
        fields=metadata_fields(raw)
        return dict(title=title, doi=doi(raw.get('doi')), arxiv_id=ax,
                    authors=[clean(a, 150) for a in raw.get('authors', [])[:50]],
                    abstract=clean(raw.get('abstract')), published=clean(raw.get('published'), 40),
                    updated=clean(raw.get('updated'), 40), url=safe_url(raw.get('url')),
                    categories=[clean(t, 150) for t in raw.get('categories', [])[:20]],
                    source=source, source_id=clean(raw.get('source_id'), 600),**fields)

    def _ingest(self, c, job, raw):
        p, now, owner = self.paper(raw, job['source']), self.clock(), job['owner']
        aliases = [(k, p[k]) for k in ('doi', 'arxiv_id') if p[k]]
        if p['source_id']:
            aliases.append(('source_id', job['source'] + ':' + p['source_id']))
        # Title matching is conservative: require year and first author; conflicting DOIs stay separate.
        if p['authors'] and re.match(r'\d{4}', p['published']):
            aliases.append(('bibliographic', fingerprint([normalized(p['title']), p['published'][:4], normalized(p['authors'][0])])))
        candidates = []
        for kind, value in aliases:
            for row in c.execute('''SELECT p.* FROM research_watch_aliases a JOIN research_watch_papers p ON p.id=a.paper_id
                                  WHERE a.owner=? AND a.kind=? AND a.value=?''', (owner, kind, value)):
                previous = json.loads(row['payload'])
                if not (p['doi'] and previous.get('doi') and p['doi'] != previous['doi']):
                    candidates.append(row)
        pid = candidates[0]['id'] if candidates else uuid.uuid4().hex
        # A later DOI/arXiv record may bridge two earlier identities. Consolidate
        # memberships without changing the immutable evidence payloads/IDs.
        for other in dict.fromkeys(r['id'] for r in candidates if r['id'] != pid):
            c.execute('''INSERT OR IGNORE INTO research_watch_aliases SELECT owner,kind,value,? FROM research_watch_aliases WHERE paper_id=?''', (pid, other))
            c.execute('DELETE FROM research_watch_aliases WHERE paper_id=?', (other,))
            c.execute('''INSERT OR IGNORE INTO research_watch_discoveries SELECT subscription_id,?,snapshot_id,discovered,classification
                         FROM research_watch_discoveries WHERE paper_id=?''', (pid, other))
            c.execute('DELETE FROM research_watch_discoveries WHERE paper_id=?', (other,))
            c.execute('''INSERT OR IGNORE INTO research_watch_digest_entries SELECT digest_id,subscription_id,?,snapshot_id
                         FROM research_watch_digest_entries WHERE paper_id=?''', (pid, other))
            c.execute('DELETE FROM research_watch_digest_entries WHERE paper_id=?', (other,))
            c.execute('UPDATE research_watch_snapshots SET paper_id=? WHERE paper_id=?', (pid, other))
            c.execute('DELETE FROM research_watch_papers WHERE id=?', (other,))
        if candidates:
            previous = json.loads(candidates[0]['payload'])
            merged = dict(previous)
            for k, v in p.items():
                if v:
                    merged[k] = v
            c.execute('UPDATE research_watch_papers SET payload=?,updated=? WHERE id=?', (packed(merged), now, pid))
        else:
            c.execute('INSERT INTO research_watch_papers VALUES (?,?,?,?,?)', (pid, owner, packed(p), now, now))
        for kind, value in aliases:
            c.execute('INSERT OR IGNORE INTO research_watch_aliases VALUES (?,?,?,?)', (owner, kind, value, pid))
        h = fingerprint(p)
        snap = c.execute('SELECT id FROM research_watch_snapshots WHERE owner=? AND paper_id=? AND hash=?', (owner, pid, h)).fetchone()
        snapid = snap['id'] if snap else uuid.uuid4().hex
        if not snap:
            c.execute('INSERT INTO research_watch_snapshots VALUES (?,?,?,?,?,?)', (snapid, owner, pid, h, now, packed(p)))
        sid = job['subscription_id']
        if c.execute('SELECT 1 FROM research_watch_discoveries WHERE subscription_id=? AND paper_id=?', (sid, pid)).fetchone():
            return None
        classification = classify(p, json.loads(job['directions']))
        c.execute('INSERT INTO research_watch_discoveries VALUES (?,?,?,?,?)', (sid, pid, snapid, now, packed(classification)))
        return dict(paper_id=pid, snapshot_id=snapid)

    def commit_page(self, job, page):
        if not isinstance(page, dict) or not isinstance(page.get('rows'), list) or len(page['rows']) > 50 or not isinstance(page.get('complete'), bool) or not isinstance(page.get('cursor'), str) or len(page['cursor']) > 20000:
            raise ValueError('invalid source page')
        if not page['complete'] and not page['cursor']:
            raise ValueError('missing continuation cursor')
        now, new = self.clock(), []
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            current = self._valid(c, job)
            if not current:
                self._release_collector(c, job)
                return {'stale': True}
            page_hash = fingerprint(page['rows'])
            if page['rows'] and page_hash == current['last_page_hash'] and job['cursor']:
                raise ValueError('source repeated the previous page')
            for raw in page['rows']:
                found = self._ingest(c, job, raw)
                if found:
                    new.append(found)
            if new:
                day = datetime.fromtimestamp(now, timezone(timedelta(hours=8))).date().isoformat()
                c.execute('INSERT OR IGNORE INTO research_watch_digests VALUES (?,?,?,?,?)', (uuid.uuid4().hex, job['owner'], day, now, now))
                did = c.execute('SELECT id FROM research_watch_digests WHERE owner=? AND day=?', (job['owner'], day)).fetchone()['id']
                for item in new:
                    c.execute('INSERT OR IGNORE INTO research_watch_digest_entries VALUES (?,?,?,?)', (did, job['subscription_id'], item['paper_id'], item['snapshot_id']))
                c.execute('UPDATE research_watch_digests SET updated=? WHERE id=?', (now, did))
                c.execute('INSERT INTO research_watch_notifications VALUES (?,?,?,?,?,?,0)', (uuid.uuid4().hex, job['owner'], did, job['subscription_id'], len(new), now))
            complete = page['complete']
            c.execute('''UPDATE research_watch_jobs SET watermark=?,window_start=?,window_end=?,cursor=?,next_due=?,token='',lease_until=0,
                         status=?,last_success=?,last_error='',scanned=scanned+?,new_count=new_count+?,pages=pages+1,last_page_hash=?
                         WHERE subscription_id=? AND source=?''',
                      (job['window_end'] if complete else job['watermark'], 0 if complete else job['window_start'],
                       0 if complete else job['window_end'], '' if complete else page['cursor'],
                       now + (job['interval_hours']*3600 if complete else 60), 'idle' if complete else 'backlog', now,
                       len(page['rows']), len(new), '' if complete else page_hash, job['subscription_id'], job['source']))
            self._release_collector(c, job)
        return {'new_count': len(new), 'complete': complete, 'scanned': len(page['rows'])}

    def tick(self, limit=2):
        results = []
        for _ in range(max(1, min(limit, 2))):
            job = self.claim()
            if not job:
                break
            try:
                page = self.sources.page(job['source'], job['query'], job['window_start'], job['window_end'], job['cursor'])
                results.append(self.commit_page(job, page))
            except Exception as exc:
                # Do not persist exception messages, request URLs or headers.
                code = getattr(exc, 'code', None)
                category = f'HTTP_{code}' if isinstance(code, int) and 100 <= code <= 599 else type(exc).__name__
                with self.store._conn() as c:
                    c.execute('BEGIN IMMEDIATE')
                    if self._valid(c, job):
                        # Cursors can expire; restart the SAME window, never move the watermark on failure.
                        c.execute("UPDATE research_watch_jobs SET cursor='',last_page_hash='',status='error',last_error=?,token='',lease_until=0,next_due=? WHERE subscription_id=? AND source=?",
                                  (category, self.clock()+900, job['subscription_id'], job['source']))
                    self._release_collector(c, job)
                results.append({'error': category})
        return results

    def state(self, owner):
        with self.store._conn() as c:
            subs = []
            for row in c.execute('SELECT * FROM research_subscriptions WHERE owner=? ORDER BY created DESC LIMIT 20', (owner,)):
                sub = dict(row)
                sub['directions'], sub['sources'] = json.loads(sub['directions']), json.loads(sub['sources'])
                sub['jobs'] = [dict(j) for j in c.execute('''SELECT source,watermark,window_start,window_end,next_due,status,last_success,last_error,scanned,new_count,pages,lease_until
                    FROM research_watch_jobs WHERE subscription_id=? ORDER BY source''', (sub['id'],))]
                subs.append(sub)
            notifications = [dict(r) for r in c.execute('SELECT * FROM research_watch_notifications WHERE owner=? ORDER BY created DESC LIMIT 50', (owner,))]
            digests = [dict(r) for r in c.execute('''SELECT d.*,COUNT(DISTINCT e.paper_id) AS paper_count FROM research_watch_digests d
                LEFT JOIN research_watch_digest_entries e ON e.digest_id=d.id WHERE d.owner=? GROUP BY d.id ORDER BY d.day DESC LIMIT 30''', (owner,))]
            unread = c.execute('SELECT COUNT(*) FROM research_watch_notifications WHERE owner=? AND read_at=0', (owner,)).fetchone()[0]
        return dict(subscriptions=subs, notifications=notifications, unread=unread, digests=digests, sources=SOURCE_INFO,
                    server_time=self.clock(), timezone='Asia/Shanghai', policy=dict(default_interval_hours=6, bootstrap_days=30, overlap_days=7,
                    runtime='应用运行时自动检查；退出或休眠期间不会采集，恢复后续采。站内通知由页面轮询刷新。',
                    coverage='发现范围限所选来源、查询匹配及窗口；分页未完成显示积压，不代表已穷尽领域论文。',
                    summary='标题/摘要的可追溯摘录，不代表全文精读或系统综述；无外部消息发送。'))

    def feed(self, owner, sid='', offset=0, limit=30):
        with self.store._conn() as c:
            if sid:
                self.owned(c, owner, sid)
            rows = c.execute('''WITH entries AS (
                SELECT d.*,s.name AS subscription_name,x.payload,x.captured,
                ROW_NUMBER() OVER(PARTITION BY d.paper_id ORDER BY d.discovered,d.subscription_id) AS position
                FROM research_watch_discoveries d JOIN research_subscriptions s ON s.id=d.subscription_id
                JOIN research_watch_snapshots x ON x.id=d.snapshot_id WHERE s.owner=? AND (?='' OR s.id=?))
                SELECT * FROM entries WHERE position=1 ORDER BY discovered DESC,paper_id LIMIT ? OFFSET ?''', (owner, sid, sid, limit, offset)).fetchall()
            items = [self._entry(r) for r in rows]
            for item in items:
                item['subscriptions'] = [dict(r) for r in c.execute('''SELECT s.id,s.name FROM research_watch_discoveries d
                    JOIN research_subscriptions s ON s.id=d.subscription_id WHERE s.owner=? AND d.paper_id=?''', (owner, item['paper_id']))]
        return {'items': items, 'offset': offset, 'limit': limit}

    @staticmethod
    def _entry(row):
        p = json.loads(row['payload'])
        return dict(paper_id=row['paper_id'], subscription_id=row['subscription_id'], subscription_name=row['subscription_name'],
                    snapshot_id=row['snapshot_id'], paper=p, discovered=row['discovered'], captured=row['captured'],
                    classification=json.loads(row['classification']), summary=summary(p, row['snapshot_id']))

    def digest(self, owner, did, offset=0, limit=30):
        with self.store._conn() as c:
            digest = c.execute('SELECT * FROM research_watch_digests WHERE id=? AND owner=?', (did, owner)).fetchone()
            if not digest:
                raise LookupError('日报不存在')
            # Frozen discovery snapshots, not silently rewritten by later source metadata.
            rows = c.execute('''WITH entries AS (SELECT e.*,x.payload,x.captured,d.discovered,d.classification,COALESCE(s.name,'已删除订阅') AS subscription_name,
                ROW_NUMBER() OVER(PARTITION BY e.paper_id ORDER BY d.discovered,e.subscription_id) AS position
                FROM research_watch_digest_entries e JOIN research_watch_snapshots x ON x.id=e.snapshot_id
                JOIN research_watch_discoveries d ON d.subscription_id=e.subscription_id AND d.paper_id=e.paper_id
                LEFT JOIN research_subscriptions s ON s.id=e.subscription_id WHERE e.digest_id=?)
                SELECT * FROM entries WHERE position=1 ORDER BY discovered,paper_id LIMIT ? OFFSET ?''', (did, limit, offset)).fetchall()
            return dict(digest=dict(digest), items=[self._entry(r) for r in rows], offset=offset, limit=limit,
                        boundary='北京时间当日发现记录，随新增采集追加；不是当日发表论文全集。摘录与发现时的来源快照绑定。')

    def snapshot(self, owner, snapid):
        with self.store._conn() as c:
            row = c.execute('SELECT * FROM research_watch_snapshots WHERE id=? AND owner=?', (snapid, owner)).fetchone()
            if not row:
                raise LookupError('来源快照不存在')
            return dict(id=row['id'], captured=row['captured'], hash=row['hash'], paper=json.loads(row['payload']))

    def reclassify(self, owner, sid, pid, labels):
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            sub = self.owned(c, owner, sid)
            allowed = [d['name'] for d in json.loads(sub['directions'])] + ['待归类']
            if not isinstance(labels, list) or not 1 <= len(labels) <= 12 or any(not isinstance(v, str) or v not in allowed for v in labels):
                raise ValueError('请选择订阅中已有的方向')
            value = [dict(name=v, evidence=[], method='manual', review_required=False) for v in dict.fromkeys(labels)]
            if not c.execute('UPDATE research_watch_discoveries SET classification=? WHERE subscription_id=? AND paper_id=?', (packed(value), sid, pid)).rowcount:
                raise LookupError('发现记录不存在')
        return {'classification': value}

    def read(self, owner, nid):
        with self.store._conn() as c:
            if not c.execute('UPDATE research_watch_notifications SET read_at=? WHERE id=? AND owner=?', (self.clock(), nid, owner)).rowcount:
                raise LookupError('通知不存在')
        return {'read': True}


class ResearchWatchWorker:
    def __init__(self, service):
        self.service, self.task, self.stopping, self.last_error = service, None, False, ''

    def start(self):
        if not self.task or self.task.done():
            self.stopping = False
            self.task = asyncio.create_task(self.run())

    async def run(self):
        while not self.stopping:
            try:
                await asyncio.to_thread(self.service.tick)
                if not self.stopping:
                    from services.research_updates import ResearchUpdates
                    await asyncio.to_thread(lambda:ResearchUpdates(self.service).tick())
                self.last_error = ''
            except Exception as exc:
                self.last_error = type(exc).__name__
            if not self.stopping:
                await asyncio.sleep(15)

    async def close(self):
        self.stopping = True
        if self.task:
            # Await the bounded request/transaction; don't cancel a live native thread.
            await self.task
