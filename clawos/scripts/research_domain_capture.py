"""Capture a fixed public reading corpus. Never modifies the application database."""
import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.meta = {}; self.parts = []; self.skip = 0; self.abstract = []; self.in_abstract = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style'): self.skip += 1
        if tag == 'blockquote' and 'abstract' in a.get('class', '').split(): self.in_abstract = True
        if tag == 'meta':
            self.meta.setdefault(a.get('name', ''), []).append(a.get('content', ''))

    def handle_endtag(self, tag):
        if tag in ('script', 'style'): self.skip = max(0, self.skip - 1)
        if tag == 'blockquote': self.in_abstract = False

    def handle_data(self, data):
        if not self.skip: self.parts.append(data)
        if self.in_abstract: self.abstract.append(data)


def capture(url):
    # Some anonymous Springer public pages use their official identity-provider
    # redirect even for open articles. No cookie jar, user session or credentials.
    allowed = {'arxiv.org', 'link.springer.com', 'link.springernature.com', 'idp.springer.com', 'openreview.net', 'api.crossref.org', 'dl.acm.org'}
    def check(value):
        p = urllib.parse.urlsplit(value)
        if p.scheme != 'https' or p.hostname not in allowed or p.username or p.password:
            raise ValueError('untrusted public source')
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            check(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    check(url)
    request = urllib.request.Request(url, headers={'User-Agent': 'ClawOS-DomainReading/1.0'})
    with urllib.request.build_opener(Redirect()).open(request, timeout=20) as response:
        raw = response.read(4_000_001)
        final = response.url
    if len(raw) > 4_000_000: raise ValueError('public source too large')
    parser = Page(); parser.feed(raw.decode('utf-8'))
    text = ' '.join(' '.join(parser.parts).split())
    return raw, text, parser, final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=['primary', 'surveys', 'supplements', 'publications'], required=True)
    parser.add_argument('--replay', type=Path, help='Reparse previously captured HTML after verifying its recorded SHA; no network')
    a = parser.parse_args()
    if a.output.exists(): raise SystemExit('Use a new evidence directory; previous captures are immutable')
    pack = json.loads(a.pack.read_text(encoding='utf-8'))
    if a.phase == 'publications':
        targets = [(d['id'] + '-publication', 'https://api.crossref.org/works/' + urllib.parse.quote(d['survey']['doi'], safe='')) for d in pack['domains']]
    elif a.phase == 'surveys': targets = [(d['id'] + '-survey', d['survey']['url']) for d in pack['domains']]
    else: targets = [(p['id'], 'https://arxiv.org/abs/' + p.get('version', p['arxiv_id'])) for d in pack['domains'] for p in d['papers' if a.phase == 'primary' else 'supplements']]
    a.output.mkdir(parents=True)
    records = []
    old = {r['id']: r for r in json.loads((a.replay / 'captures.json').read_text(encoding='utf-8'))['records']} if a.replay else {}
    for sid, url in targets:
        entry = dict(id=sid, url=url, captured=datetime.now(timezone.utc).isoformat(), verified=False)
        try:
            if a.replay:
                prior = old[sid]; raw = (a.replay / (sid + '.html')).read_bytes()
                if hashlib.sha256(raw).hexdigest() != prior['raw_sha256']: raise ValueError('capture hash mismatch')
                page = Page(); page.feed(raw.decode('utf-8')); text = ' '.join(' '.join(page.parts).split()); final = prior['final_url']
                entry.update(captured=prior['captured'], reparsed=datetime.now(timezone.utc).isoformat())
            else: raw, text, page, final = capture(url)
            meta = page.meta
            (a.output / (sid + '.html')).write_bytes(raw)
            (a.output / (sid + '.text')).write_text(text, encoding='utf-8')
            entry.update(verified=True, final_url=final, raw_sha256=hashlib.sha256(raw).hexdigest(),
                         text_sha256=hashlib.sha256(text.encode()).hexdigest(), meta=meta)
            if a.phase == 'publications':
                m = json.loads(raw)['message']
                entry['publication'] = {k: m.get(k) for k in ('DOI', 'title', 'container-title', 'published', 'type')}
                if m['DOI'].lower() != urllib.parse.unquote(url.split('/works/')[1]).lower(): raise ValueError('publication DOI mismatch')
            elif a.phase != 'surveys':
                title = meta.get('citation_title', [''])[0]
                abstract = re.sub(r'^Abstract:\s*', '', ' '.join(' '.join(page.abstract).split()))
                # The generic description meta tag is NOT the author abstract.
                version = re.search(r'arXiv:(\d{4}\.\d{4,5}v\d+)', text)
                if not title or not abstract or not version: raise ValueError('missing explicit title/abstract/version')
                entry['paper'] = dict(source='arxiv', title=title, abstract=abstract,
                    arxiv_id=version[1], source_id=version[1], doi=meta.get('citation_doi', [''])[0],
                    authors=meta.get('citation_author', []), published=meta.get('citation_date', [''])[0].replace('/', '-'),
                    updated=meta.get('citation_online_date', [''])[0].replace('/', '-'), url=final, categories=[],
                    references=[], references_available=False, journal_ref=meta.get('citation_journal_title', [''])[0])
        except Exception as exc:
            entry.update(verified=False, error=type(exc).__name__, http_status=getattr(exc, 'code', None))
        records.append(entry)
        (a.output / 'captures.json').write_text(json.dumps(dict(phase=a.phase, records=records), ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(dict(id=sid, verified=entry['verified'], title=entry.get('paper', {}).get('title'), error=entry.get('error'))), flush=True)
        if not a.replay: time.sleep(3.1)
    if not all(r['verified'] for r in records): raise SystemExit(1)


if __name__ == '__main__': main()
