"""Pinned arXiv captures. No credentials, external model, full-text fallbacks or hidden sources."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
import uuid
from scripts.research_domain_capture import Page
from services.research_watch import fingerprint
from services.research_learning_engine import normalized_pages

def digest(raw):return hashlib.sha256(raw).hexdigest()
def check_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or p.hostname!='arxiv.org' or p.username or p.password or p.query or p.fragment or p.port not in (None,443):raise ValueError('Only pinned public arXiv URLs are allowed')
    if not re.fullmatch(r'/(abs|pdf)/\d{4}\.\d{4,5}v\d+',p.path):raise ValueError('A pinned paper version is required')

def read_public(url,limit):
    check_url(url)
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            check_url(newurl);return super().redirect_request(req,fp,code,msg,headers,newurl)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),Redirect())
    with opener.open(urllib.request.Request(url,headers={'User-Agent':'ClawOS-ResearchTeaching/1.0'}),timeout=25) as response:
        raw=response.read(limit+1);final=response.url
    if len(raw)>limit:raise ValueError('Public paper capture exceeded its byte budget')
    check_url(final)
    return raw,final

def write(path,raw):
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');tmp.write_bytes(raw);tmp.replace(path)

def paper_source(spec,cache):
    version=spec['version']
    if not re.fullmatch(r'\d{4}\.\d{4,5}v\d+',version):raise ValueError('Pinned paper version invalid')
    cache=Path(cache).resolve();root=cache/version
    if not root.resolve().is_relative_to(cache):raise ValueError('Public source cache escapes the store')
    root.mkdir(parents=True,exist_ok=True)
    url='https://arxiv.org/pdf/'+version;meta_url='https://arxiv.org/abs/'+version
    stamp=root/'capture.json';cache_used=stamp.is_file()
    if cache_used:
        for name,limit in [('capture.json',20000),('paper.pdf',16_000_000),('metadata.html',4_000_000)]:
            path=root/name
            if not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size>limit:raise ValueError('Cached source path or size invalid')
        capture=json.loads(stamp.read_text(encoding='utf-8'));raw=(root/'paper.pdf').read_bytes();html=(root/'metadata.html').read_bytes()
        if digest(raw)!=capture['pdf_sha256'] or digest(html)!=capture['metadata_sha256'] or capture['version']!=version:raise ValueError('Cached public source integrity failure')
    else:
        html,meta_final=read_public(meta_url,4_000_000);time.sleep(3.1)
        raw,final=read_public(url,16_000_000);time.sleep(3.1)
        captured=datetime.now(timezone.utc).isoformat()
        capture=dict(version=version,pdf_sha256=digest(raw),metadata_sha256=digest(html),pdf_url=final,metadata_url=meta_final,
                     captured=captured,pdf_captured=captured,metadata_captured=captured,capture_mode='public_network_capture')
    if len(raw)>16_000_000 or len(html)>4_000_000 or not raw.startswith(b'%PDF'):raise ValueError('Captured source is not a bounded PDF')
    if capture['pdf_url']!=url or capture['metadata_url']!=meta_url:raise ValueError('Capture URL/version mismatch')
    if capture['capture_mode'] not in ('public_network_capture','verified_capture_replay'):raise ValueError('Unknown public capture provenance')
    for key in ('captured','pdf_captured','metadata_captured'):
        moment=datetime.fromisoformat(capture[key])
        if moment.tzinfo is None or moment>datetime.now(timezone.utc):raise ValueError('Public capture timestamp invalid')
    parser=Page();parser.feed(html.decode('utf-8'));meta=parser.meta
    page_text=' '.join(' '.join(parser.parts).split());match=re.search(r'arXiv:(\d{4}\.\d{4,5}v\d+)',page_text)
    title=meta.get('citation_title',[''])[0];abstract=re.sub(r'^Abstract:\s*','',' '.join(' '.join(parser.abstract).split()))
    norm=lambda t:re.sub(r'[^a-z0-9]','',t.lower())
    if not match or match[1]!=version or norm(title)!=norm(spec['title']) or len(abstract)<80:raise ValueError('Public metadata identity/abstract/version mismatch')
    import fitz
    with fitz.open(stream=raw,filetype='pdf') as pdf:
        if not 1<=len(pdf)<=100:raise ValueError('Paper page budget exceeded')
        pages=normalized_pages([page.get_text() for page in pdf])
    text='\n\n'.join(pages)
    title_tokens=set(re.findall(r'[a-z0-9]+',title.lower()));head=set(re.findall(r'[a-z0-9]+',text[:7000].lower()))
    if len(title_tokens&head)/max(1,len(title_tokens))<.8 or not 2000<=len(text)<=250000:raise ValueError('PDF title/text identity or size mismatch')
    if not cache_used:
        write(root/'paper.pdf',raw);write(root/'metadata.html',html);write(stamp,json.dumps(capture).encode())
    spans=[];offset=0
    for page in pages:spans.append([offset,offset+len(page)]);offset+=len(page)+2
    return dict(id=spec['id'],name=spec['name'],title=title,version=version,url=url,metadata_url=meta_url,
        authors=meta.get('citation_author',[]),date=spec['date'],category=spec['category'],abstract=abstract,
        text=text,page_spans=spans,raw_sha256=digest(raw),metadata_sha256=digest(html),text_sha256=digest(text.encode()),
        captured=capture['captured'],pdf_captured=capture['pdf_captured'],metadata_captured=capture['metadata_captured'],capture_mode=capture['capture_mode'],
        page_count=len(pages),cache_used=cache_used,source_text_fingerprint=fingerprint(text))
