"""Bounded public metadata collectors. No PDF downloads or model calls."""
import html
import json
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from services.research_bibliography import RELATIONS,identifier_doi,arxiv_parts


SOURCE_INFO = {
    'crossref': dict(name='Crossref', mode='indexed_updates',
                     delay='出版商提交及来源索引存在延迟，无固定发现时限。',
                     boundary='按索引更新时间采集；索引更新也可能只是引用数或元数据变化。'),
    'arxiv': dict(name='arXiv', mode='new_submissions',
                  delay='投稿、公告与 API 索引之间存在延迟，无固定发现时限。',
                  boundary='按首次投稿时间发现新论文；不保证发现窗口外旧论文的新修订。'),
}


def clean(value, limit=16000):
    # Numeric comparisons in author abstracts (e.g. "<50k ... >1m") are
    # evidence, not markup. Require a syntactically plausible tag name.
    tags = r'</?[A-Za-z][A-Za-z0-9:._-]*(?:\s+[^<>]*?)?\s*/?>'
    return re.sub(r'\s+', ' ', html.unescape(re.sub(tags, ' ', str(value or '')))).strip()[:limit]


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def safe_url(value):
    value = str(value or '')[:2000]
    parsed = urllib.parse.urlsplit(value)
    return value if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password else ''


def date_parts(value):
    parts = (value or {}).get('date-parts', [[]])[0]
    return '-'.join(str(p).zfill(4 if i == 0 else 2) for i, p in enumerate(parts)) if parts else ''


def crossref_links(item):
    references=item.get('reference') or []
    if not isinstance(references,list):raise ValueError('invalid Crossref references')
    relations=[]
    for kind,values in (item.get('relation') or {}).items():
        if kind not in RELATIONS:continue
        for value in values:
            identifier=value.get('id','');base,version=arxiv_parts(identifier)
            target_doi=identifier_doi(identifier) if value.get('id-type')=='doi' else ''
            if target_doi or base:relations.append(dict(kind=kind,doi=target_doi,arxiv_id=base+('v'+str(version) if version else '') if base else '',asserted_by=value.get('asserted-by','')))
    reported=item.get('reference-count')
    return dict(references=[dict(doi=r.get('DOI',''),key=r.get('key',''),unstructured=clean(r.get('unstructured'),1200)) for r in references[:500]],
        references_available='reference' in item or reported==0,reference_count_reported=reported,
        references_truncated=len(references)>500 or type(reported) is int and reported>len(references),
        relations=relations[:100],relations_truncated=len(relations)>100,publication_type=item.get('type',''),journal_ref='')


class WatchSources:
    """At most one request at a time, >=3 seconds between starts, across instances."""
    lock = threading.Lock()
    last_request = 0.0

    def __init__(self, transport=None):
        self.transport = transport or self._request

    @classmethod
    def _request(cls, url):
        allowed = {'api.crossref.org', 'export.arxiv.org'}

        class Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                target = urllib.parse.urlsplit(newurl)
                if target.scheme != 'https' or target.hostname not in allowed:
                    raise ValueError('untrusted source redirect')
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        with cls.lock:
            delay = 3.1 - (time.monotonic() - cls.last_request)
            if delay > 0:
                time.sleep(delay)
            cls.last_request = time.monotonic()
            req = urllib.request.Request(url, headers={'User-Agent': 'ClawOS-ResearchWatch/1.0', 'Accept': 'application/json, application/atom+xml'})
            with urllib.request.build_opener(Redirect()).open(req, timeout=20) as response:
                raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise ValueError('source response too large')
            return raw

    def lookup(self,source,identifier):
        if source=='crossref':
            value=identifier_doi(identifier)
            if not value:raise ValueError('valid DOI required')
            raw=json.loads(self.transport('https://api.crossref.org/works/'+urllib.parse.quote(value,safe='')))['message']
            records=self._crossref_rows([raw])
            if identifier_doi(records[0]['doi'])!=value:raise ValueError('Crossref identifier mismatch')
            return records[0]
        if source!='arxiv':raise ValueError('unsupported source')
        base,version=arxiv_parts(identifier)
        if not base:raise ValueError('valid arXiv identifier required')
        exact=base+('v'+str(version) if version else '')
        root=ET.fromstring(self.transport('https://export.arxiv.org/api/query?'+urllib.parse.urlencode(dict(id_list=exact))))
        rows=self._arxiv_rows(root)
        if len(rows)!=1:raise ValueError('arxiv lookup returned unexpected records')
        got,got_version=arxiv_parts(rows[0]['arxiv_id'])
        if got!=base or version and got_version!=version:raise ValueError('arxiv version mismatch')
        return rows[0]

    @staticmethod
    def _crossref_rows(items):
        rows=[]
        for item in items:
            rows.append(dict(title=clean((item.get('title') or [''])[0],1000),doi=item.get('DOI',''),
                authors=[clean(' '.join([a.get('given',''),a.get('family','')]),150) for a in item.get('author',[])[:50]],
                abstract=clean(item.get('abstract')),published=date_parts(item.get('published')),updated=(item.get('indexed') or {}).get('date-time',''),
                url=safe_url(item.get('URL')),categories=[clean(x,150) for x in item.get('subject',[])[:20]],source='crossref',source_id=item.get('DOI',''),arxiv_id='',**crossref_links(item)))
        return rows

    @staticmethod
    def _arxiv_rows(root):
        atom,ax='{http://www.w3.org/2005/Atom}','{http://arxiv.org/schemas/atom}'
        rows=[]
        for entry in root.findall(atom+'entry'):
            identifier=entry.findtext(atom+'id','')
            if '/api/errors' in identifier:raise ValueError('arxiv query rejected')
            rows.append(dict(title=clean(entry.findtext(atom+'title'),1000),doi=entry.findtext(ax+'doi',''),arxiv_id=identifier.split('/abs/')[-1],source_id=identifier,
                authors=[clean(a.findtext(atom+'name'),150) for a in entry.findall(atom+'author')[:50]],abstract=clean(entry.findtext(atom+'summary')),
                published=entry.findtext(atom+'published',''),updated=entry.findtext(atom+'updated',''),url=safe_url(identifier.replace('http:','https:',1)),
                categories=[clean(c.get('term'),150) for c in entry.findall(atom+'category')[:20]],source='arxiv',publication_type='preprint',journal_ref=clean(entry.findtext(ax+'journal_ref'),1000),
                references=[],references_available=False,reference_count_reported=None,relations=[]))
        return rows

    def page(self, source, query, start, end, cursor='', size=50):
        if source not in SOURCE_INFO:
            raise ValueError('unsupported source')
        size = max(1, min(50, int(size)))
        if source == 'crossref':
            params = {'query.bibliographic': query, 'rows': size, 'cursor': cursor or '*',
                      'filter': f'from-index-date:{iso(start).removesuffix("Z")},until-index-date:{iso(end).removesuffix("Z")}'}
            message = json.loads(self.transport('https://api.crossref.org/works?' + urllib.parse.urlencode(params)))['message']
            items = message.get('items')
            if not isinstance(items, list):
                raise ValueError('invalid source response')
            rows = self._crossref_rows(items)
            more = len(items) == size
            next_cursor = message.get('next-cursor', '') if more else ''
            if more and not next_cursor:
                raise ValueError('source cursor is missing')
            return dict(rows=rows, cursor=next_cursor, complete=not more)

        # Literal topic text, not arbitrary arXiv query syntax. English terms are recommended.
        terms = re.findall(r'[\w-]+', query, flags=re.UNICODE)[:16]
        topic = ' AND '.join('all:' + term for term in terms)
        def stamp(t):
            return datetime.fromtimestamp(t, timezone.utc).strftime('%Y%m%d%H%M')
        params = {'search_query': f'({topic}) AND submittedDate:[{stamp(start)} TO {stamp(end)}]',
                  'start': int(cursor or 0), 'max_results': size, 'sortBy': 'submittedDate', 'sortOrder': 'ascending'}
        root = ET.fromstring(self.transport('https://export.arxiv.org/api/query?' + urllib.parse.urlencode(params)))
        atom, ax, os = '{http://www.w3.org/2005/Atom}', '{http://arxiv.org/schemas/atom}', '{http://a9.com/-/spec/opensearch/1.1/}'
        total_text = root.findtext(os + 'totalResults')
        if total_text is None:
            raise ValueError('invalid arxiv feed')
        rows = self._arxiv_rows(root)
        offset = int(cursor or 0) + len(rows)
        complete = offset >= int(total_text)
        if not rows and not complete:
            raise ValueError('arxiv paging stalled')
        return dict(rows=rows, cursor='' if complete else str(offset), complete=complete)
