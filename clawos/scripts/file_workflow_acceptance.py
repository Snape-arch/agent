"""Isolated, model-free HTTP acceptance with an actual synthetic paper PDF."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


async def run(root):
    root.mkdir(parents=True,exist_ok=True)
    os.environ['CLAWOS_MEMORY_DB']=str(root/'learning.db')
    os.environ['CLAWOS_OUTPUT_DIR']=str(root/'output')
    import httpx
    import clawos_server as server
    from memoryos.memory_store import MemoryStore
    from memoryos.document_ingestion import ingest_file
    from workspace_services import WorkspaceServices
    from security.policy import ToolSecurityPolicy
    from reportlab.pdfgen import canvas
    store=MemoryStore(str(root/'learning.db'))
    server.g_memory_store=store
    server.OUTPUT_ROOT=root/'output'
    server.UPLOAD_DIR=root/'uploads'
    server.g_workspace_services=WorkspaceServices(store,ToolSecurityPolicy([root]))
    server.g_security_policy=ToolSecurityPolicy([root])
    source=root/'synthetic-evidence-paper.pdf'
    pdf=canvas.Canvas(str(source))
    for heading,lines in [
        ('Abstract',['Synthetic test fixture; this is not a published research result.',
                     'We evaluate a citation verifier using a blinded annotation protocol.']),
        ('Methodology',['We use 200 English claims and three independent annotators.',
                        'The evaluation compares a verifier with a retrieval-only baseline.']),
        ('Experiments and Results',['We find citation accuracy is 85 percent on the 200-claim dataset.',
                                    'The result applies only to English claims under the blinded protocol.']),
        ('Limitations',['However, this synthetic evaluation is limited to English claims.',
                        'We cannot infer performance on unseen languages or real users.'])]:
        pdf.setFont('Helvetica-Bold',16);pdf.drawString(55,775,heading)
        pdf.setFont('Helvetica',11)
        for i,line in enumerate(lines):pdf.drawString(55,735-i*24,line)
        pdf.showPage()
    pdf.save()
    document=ingest_file(store,server.UPLOAD_DIR,source,title='合成论文验收：证据与实验条件',category='research')
    if not store.conversation_history('acceptance-history')['total']:
        for i in range(112):
            store.add_message('acceptance-history','user' if i%2==0 else 'assistant',
                              'archive-only-needle '+('完整记录 '*650) if i==0 else f'历史验收记录 {i}')
    checks=[]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='http://127.0.0.1') as client:
        async def get(path):
            response=await client.get(path);response.raise_for_status();return response.json()
        history=await get('/api/history/acceptance-history?limit=17')
        assert history['has_more'] and history['total']==112
        exported=await get('/api/history/acceptance-history/export?format=json')
        assert exported['count']==112 and len(exported['messages'][0]['content'])>2000
        found=await get('/api/sessions?q=archive-only-needle')
        assert any(row['session_id']=='acceptance-history' for row in found['sessions'])
        checks.append('full_archived_history_paging_search_export')
        payload=dict(library_document_id=document['id'],output_dir=str(root/'reports'),model_assisted=False,
                     formats=['markdown','pdf'],question_count=12,depth=3)
        only_json=await client.post('/api/workspace/research/learning-analysis',json=dict(payload,formats=['json']))
        only_json.raise_for_status();assert {r['format'] for r in only_json.json()['artifacts']}=={'json'}
        checks.append('json_only_format_is_delivered')
        response=await client.post('/api/workspace/research/learning-analysis',json=payload)
        response.raise_for_status();first=response.json()
        artifacts=first['artifacts'];assert {r['format'] for r in artifacts}=={'md','pdf','json'}
        checks.append('actual_grounded_markdown_pdf_json')
        before={item['id']:item['sha256'] for item in artifacts}
        response=await client.post('/api/workspace/research/learning-analysis',json=payload)
        response.raise_for_status();second=response.json()
        assert first['report']['markdown_path'] != second['report']['markdown_path']
        for item in artifacts:
            download=await client.get(item['download_url']);download.raise_for_status()
            assert hashlib.sha256(download.content).hexdigest()==before[item['id']]
        checks.append('regeneration_preserves_previous_artifact_downloads')
        status=await get(f"/api/academy/paper/status?document_id={document['id']}")
        assert status['report']['analysis']['source_digest']==second['analysis']['source_digest']
        assert len(status['report']['artifacts'])==3
        checks.append('report_analysis_and_downloads_survive_reload')
        json_report=await client.get(next(r['download_url'] for r in second['artifacts'] if r['format']=='json'))
        assert json_report.json()['source_index']
        # Preseed a synthetic published policy to exercise the real HTTP rollback
        # boundary. This does not bypass or certify production promotion gates.
        target='acceptance-policy'
        store.set_runtime_policy('prompt_policy',target,{'system':'base'})
        def published_fixture():
            run=store.create_self_evolution_run('Synthetic ownership fixture','prompt_policy',target,
                                               {'system':'base'},{'system':'candidate'})
            store.update_self_evolution_run(run['id'],status='canary',publish_decision='canary')
            return store.publish_self_evolution_run(run['id'])
        run=published_fixture();rollback_url=f"/api/self-evolution/runs/{run['id']}/rollback"
        assert (await client.post(rollback_url,json={'confirmed':False})).status_code==409
        restored=await client.post(rollback_url,json={'confirmed':True});restored.raise_for_status()
        assert store.get_runtime_policy('prompt_policy',target)['payload']=={'system':'base'}
        run=published_fixture();store.set_runtime_policy('prompt_policy',target,{'system':'newer'})
        refused=await client.post(f"/api/self-evolution/runs/{run['id']}/rollback",json={'confirmed':True})
        assert refused.status_code==409 and store.get_runtime_policy('prompt_policy',target)['payload']=={'system':'newer'}
        board=await get('/api/self-evolution/board')
        assert not board['enterprise_ready'] and next(r for r in board['runs'] if r['id']==run['id'])['effective_stage']=='superseded'
        checks.append('actual_policy_rollback_confirmation_and_newer_policy_protection')
    import fitz
    report=fitz.open(second['report']['pdf_path'])
    pages=[]
    for i,page in enumerate(report):
        name=root/f'report-page-{i+1}.png'
        page.get_pixmap(matrix=fitz.Matrix(1.3,1.3)).save(name)
        pages.append(str(name))
    assert len(report)>=1
    checks.append('actual_pdf_rendered')
    summary=dict(checks=checks,document_id=document['id'],report=second['report'],artifacts=second['artifacts'],
                 pdf_pages=len(report),rendered_pages=pages,models_enabled=False,synthetic_fixture=True)
    (root/'acceptance.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(checks=checks,document_id=document['id'],pdf_pages=len(report),out=str(root)),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True)
    args=parser.parse_args();asyncio.run(run(Path(args.out).resolve()))
