"""Bounded public excerpt capture; mechanical verification is not human review."""
import argparse
from datetime import datetime,timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_review_examples import SOURCES,candidate_suite


class Text(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.skip=0;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.skip+=1
        if tag in ('p','div','br','h1','h2','h3','blockquote'):self.parts.append(' ')
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.skip=max(0,self.skip-1)
        if tag in ('p','div','blockquote'):self.parts.append(' ')
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--capture-public',action='store_true',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=a.output.resolve()
    if root.exists():raise SystemExit('Use a new output directory')
    root.mkdir(parents=True);records=[]
    allowed={'arxiv.org','journals.plos.org','essd.copernicus.org','report.ipcc.ch'}
    from urllib.parse import urlsplit
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            target=urlsplit(newurl)
            if target.scheme!='https' or target.hostname not in allowed:raise ValueError('untrusted redirect')
            return super().redirect_request(req,fp,code,msg,headers,newurl)
    for sid,(_,_,url,_,quote) in SOURCES.items():
        r=dict(id=sid,url=url,captured=datetime.now(timezone.utc).isoformat(),verified=False)
        try:
            request=urllib.request.Request(url,headers={'User-Agent':'ClawOS-PublicLiteratureReview/1.0','Accept':'text/html'})
            with urllib.request.build_opener(Redirect()).open(request,timeout=20) as response:raw=response.read(4000001)
            if len(raw)>4000000:raise ValueError('source too large')
            (root/(sid+'.html')).write_bytes(raw);parser=Text();parser.feed(raw.decode('utf-8'))
            text=' '.join(''.join(parser.parts).split());start=text.find(quote)
            (root/(sid+'.text')).write_text(text,encoding='utf-8')
            r.update(raw_sha256=hashlib.sha256(raw).hexdigest(),text_sha256=hashlib.sha256(text.encode()).hexdigest(),fragment_sha256=hashlib.sha256(quote.encode()).hexdigest(),start=start,end=start+len(quote),verified=start>=0)
            if start<0:r['error']='excerpt_not_found'
        except Exception as exc:r.update(error=type(exc).__name__,http_status=getattr(exc,'code',None))
        records.append(r);print(json.dumps(r),flush=True);time.sleep(3.1)
    result=dict(all_excerpts_verified=all(r['verified'] for r in records),verified=sum(r['verified'] for r in records),total=len(records),records=records,
        candidate_suite_hash=hashlib.sha256(json.dumps(candidate_suite(),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        independent_human_reviews=0,real_model_evaluation=False,boundary='Public source/excerpt existence verification only. Proposed labels remain unreviewed, never expert gold or model quality acceptance.')
    (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='records'}),flush=True)
    if not result['all_excerpts_verified']:raise SystemExit(1)


if __name__=='__main__':main()
