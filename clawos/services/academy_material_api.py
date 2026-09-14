"""HTTP adapter; shared model and material service are injected by the host."""
import asyncio
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from services.academy_materials import model_json


def materials_router(service_factory, model):
    router=APIRouter(prefix='/api/academy/learning/materials')

    @router.get('')
    async def index(learner_id: str='local-user'):
        return service_factory().state(learner=learner_id)

    @router.post('')
    async def upload(file: UploadFile=File(...), learner_id: str=Form('local-user'), title: str=Form('')):
        raw=await file.read(20*1024*1024+1)
        try:
            return await asyncio.to_thread(service_factory().upload,file.filename,raw,learner_id,title)
        except ValueError as exc:
            raise HTTPException(400,str(exc))
        finally:
            await file.close()

    @router.get('/{mid}')
    async def state(mid: str, learner_id: str='local-user'):
        try:
            return service_factory().state(mid,learner_id)
        except ValueError as exc:
            raise HTTPException(404,str(exc))

    @router.get('/{mid}/source')
    async def source(mid: str, learner_id: str='local-user'):
        try:
            service=service_factory()
            doc=service.document(mid,learner_id)
            return FileResponse(service.root/mid/doc['filename'],filename=doc['filename'],
                media_type='application/pdf' if doc['filename'].lower().endswith('.pdf') else 'application/octet-stream',
                content_disposition_type='inline' if doc['filename'].lower().endswith('.pdf') else 'attachment')
        except ValueError as exc:
            raise HTTPException(404,str(exc))

    @router.get('/{mid}/projects/{task_id}/export')
    async def export(mid: str, task_id: int, learner_id: str='local-user'):
        try:
            return Response(service_factory().export(mid,task_id,learner_id),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="learning-project-{task_id}.zip"'})
        except ValueError as exc:
            raise HTTPException(400,str(exc))

    @router.post('/{mid}/{action}')
    async def action(mid: str, action: str, request: Request):
        try:
            data=await request.json()
            if not isinstance(data,dict):
                raise ValueError('请求应为对象')
            service=service_factory()
            learner=str(data.get('learner_id') or 'local-user')
            cid=data.get('citation')
            service.document(mid,learner)
            if action in ('chapter-response','chapter-draft'):
                if type(data.get('question_event_id')) is not int:
                    raise ValueError('请提供当前诊断题版本')
                if action=='chapter-draft':
                    return service.chapter_draft(mid,data.get('chapter'),data.get('answers'),data.get('project'),data['question_event_id'],learner)
                return service.chapter_response(mid,data.get('chapter'),data.get('answers'),data.get('project'),learner,data['question_event_id'])
            if action=='search':
                from services.evidence_retrieval import retrieve
                doc=service.document(mid,learner)
                return dict(status='partial',answer_verified=False,evidence=retrieve(str(data.get('query') or ''),doc['payload'].get('passages',[]),5,doc['payload'].get('revision','')))
            if action=='retry':
                return await asyncio.to_thread(service.parse,mid,learner)
            if action=='diagnose':
                return service.diagnose(mid,data.get('answers'),data.get('goal'),learner)
            if action=='lesson':
                return service.lesson(mid,cid,learner)
            if action=='draft':
                service.passage(mid,cid,learner)
                return service.event(mid,'draft',dict(citation=cid,answer=str(data.get('answer') or '')[:6000]))
            if action=='project':
                return await asyncio.to_thread(service.project,mid,data.get('config'),data.get('cases'),learner)
            if action not in ('guide','tutor','assess','chapter-questions'):
                raise ValueError('未知学习操作')
            # Build/validate inputs before calling the shared provider.
            if action=='chapter-questions':
                prompts=[service.chapter_prompt(mid,data.get('chapter'),data.get('subject'),learner)]
            elif action=='guide':
                prompts=[service.guide_prompt(mid,cid,learner)]
            elif action=='tutor':
                prompts=[service.teaching_prompt(mid,cid,data.get('question'),learner)]
            else:
                prompts=[service.assessment_prompt(mid,cid,data.get('answer'),learner,critic=x) for x in (False,True)]
            try:
                replies=[]
                for prompt in prompts:
                    replies.append(await asyncio.wait_for(model(prompt,[]),timeout=75))
            except Exception:
                raise HTTPException(502,'模型服务暂不可用或超时；原文与已保存草稿不受影响，未计为通过。')
            if action=='chapter-questions':
                return service.save_chapter_questions(mid,data.get('chapter'),data.get('subject'),model_json(replies[0]),learner)
            if action=='guide':
                return service.save_guide(mid,cid,model_json(replies[0]),learner)
            if action=='tutor':
                reply=replies[0]['choices'][0]['message']['content']
                if not isinstance(reply,str) or not reply.strip():
                    raise ValueError('导师没有返回有效建议')
                return service.event(mid,'tutor',dict(citation=cid,question=data['question'],answer=reply[:6000]))
            return service.save_assessment(mid,cid,data['answer'],[model_json(r) for r in replies],learner)
        except (ValueError,TypeError,KeyError,IndexError) as exc:
            raise HTTPException(400,str(exc))
    return router
