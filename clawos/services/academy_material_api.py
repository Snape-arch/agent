"""HTTP adapter; shared model and material service are injected by the host."""
import asyncio
import json
import time
import uuid
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from services.academy_materials import model_json, digest
from services.runtime_records import RunRecord, now_iso


async def teaching_run(service, model, mid, action, data, learner, prompts):
    """Transport, role trace, evidence validation and persistence share one outcome."""
    doc=service.document(mid,learner)
    from services.academy_teaching_quality import AcademyTeachingQuality
    initial_bank=AcademyTeachingQuality(service,service.model_profile).bank(mid,learner)
    bank_id=initial_bank['id'] if initial_bank else None
    roles=[('reviewer' if i%2 else 'teacher') if action=='calibration-run' or len(prompts)==2 else 'tutor' if action=='tutor' else 'teacher' for i in range(len(prompts))]
    run=RunRecord(run_id='academy-teaching-'+uuid.uuid4().hex,run_type='academy_teaching',
        title=action,status='running',actor=learner,scenario='education',
        inputs=dict(material_id=mid,revision=doc['payload'].get('revision'),citation=data.get('citation'),
                    chapter=data.get('chapter'),response_id=data.get('response_id')),
        workflow=dict(mode='shared_router_role_prompts',roles=roles))
    service.store.save_run_record(run.to_dict())
    trace=[]
    started=time.perf_counter()
    try:
        replies=[]
        for index,prompt in enumerate(prompts):
            step=dict(role=roles[index],status='running',prompt_digest=digest(prompt))
            trace.append(step)
            try:
                reply=await asyncio.wait_for(model(prompt,[]),timeout=75)
            except Exception:
                step['status']='failed'
                raise HTTPException(502,'模型服务暂不可用或超时；原文与已保存草稿不受影响，未计为通过。')
            step.update(status='completed',response_digest=digest(reply))
            replies.append(reply)
        if service.document(mid,learner)['payload'].get('revision') != doc['payload'].get('revision'):
            raise ValueError('原文版本已变化，模型结果未保存，请重新请求')
        if action in ('chapter-review','calibration-run'):
            current_bank=AcademyTeachingQuality(service,service.model_profile).bank(mid,learner)
            if (current_bank['id'] if current_bank else None)!=bank_id:
                raise ValueError('教师量尺在评阅期间已变化，结果未保存，请重新评阅')
        if action=='calibration-run':
            from services.academy_teaching_quality import AcademyTeachingQuality
            result=AcademyTeachingQuality(service,service.model_profile).save_calibration(mid,data['bank_id'],[model_json(r) for r in replies],learner)
        elif action=='seminar':
            from services.academy_teaching_quality import AcademyTeachingQuality
            result=AcademyTeachingQuality(service,service.model_profile).save_seminar(mid,data.get('chapters'),model_json(replies[0]),learner)
        elif action=='chapter-review':
            result=service.save_chapter_review(mid,data.get('response_id'),[model_json(r) for r in replies],learner)
        elif action=='chapter-questions':
            result=service.save_chapter_questions(mid,data.get('chapter'),data.get('subject'),model_json(replies[0]),learner)
        elif action=='guide':
            result=service.save_guide(mid,data.get('citation'),model_json(replies[0]),learner)
        elif action=='tutor':
            reply=replies[0]['choices'][0]['message']['content']
            if not isinstance(reply,str) or not reply.strip():
                raise ValueError('导师没有返回有效建议')
            result=service.event(mid,'tutor',dict(citation=data.get('citation'),question=data['question'],answer=reply[:6000]))
        else:
            result=service.save_assessment(mid,data.get('citation'),data['answer'],[model_json(r) for r in replies],learner)
        run.status=result['data'].get('status','completed')
        run.outputs=dict(event_id=result['id'],evidence_validated=True,answer_verified=False)
        result['run_id']=run.run_id
        run.add_evidence('learning_material','Teaching result binds to this material revision',
            citation=data.get('citation') or mid,revision=doc['payload'].get('revision'))
        return result
    finally:
        if run.status=='running':
            run.status='failed'
            run.add_failure_case('teaching_incomplete','Model call or evidence validation did not complete',
                                 remediation='Saved work is preserved. Retry this action.')
        for step in trace:
            if step['status']=='running':
                step['status']='cancelled'
        run.completed_at=now_iso()
        run.metrics=dict(model_calls=len(trace),duration_ms=round((time.perf_counter()-started)*1000,2))
        run.workflow['trace']=trace
        service.store.save_run_record(run.to_dict())
        service.event(mid,'model_run',dict(run_id=run.run_id,action=action,status=run.status,
            citation=data.get('citation'),trace=trace,event_id=run.outputs.get('event_id'),
            boundary='同一共享模型路由的不同角色提示；引用校验不代表专家认证。'))


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

    @router.get('/{mid}/passport')
    async def passport(mid: str, learner_id: str='local-user'):
        try:
            value=service_factory().journey.passport(mid,learner_id)
            return Response(json.dumps(value,ensure_ascii=False,indent=2),media_type='application/json',
                headers={'Content-Disposition':f'attachment; filename="learning-passport-{mid}.json"'})
        except ValueError as exc:
            raise HTTPException(404,str(exc))

    @router.get('/{mid}/recalls/{attempt_id}')
    async def recall(mid: str, attempt_id: int, learner_id: str='local-user'):
        try:
            journey=service_factory().journey
            return journey._public(journey.attempt(mid,attempt_id,learner_id))
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
            if action in ('calibration-bank','seminar-response'):
                from services.academy_teaching_quality import AcademyTeachingQuality
                quality=AcademyTeachingQuality(service,service.model_profile)
                if action=='calibration-bank':return quality.import_bank(mid,data.get('bank'),learner)
                return quality.seminar_response(mid,data.get('seminar_id'),data.get('answers'),data.get('claims'),learner)
            if action=='journey-settings':
                return service.journey.settings(mid,data.get('minutes'),learner)
            if action=='recall-start':
                return service.journey.start(mid,data.get('chapter'),learner)
            if action=='recall-submit':
                return service.journey.submit(mid,data.get('attempt_id'),data.get('answers'),learner)
            if action=='recall-rate':
                return service.journey.rate(mid,data.get('attempt_id'),data.get('rating'),learner)
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
            if action not in ('guide','tutor','assess','chapter-questions','chapter-review','seminar','calibration-run'):
                raise ValueError('未知学习操作')
            # Build/validate inputs before calling the shared provider.
            if action=='calibration-run':
                from services.academy_teaching_quality import AcademyTeachingQuality
                bank,cases=AcademyTeachingQuality(service,service.model_profile).calibration_prompts(mid,learner)
                data['bank_id']=bank['id'];prompts=[row[2] for row in cases]
            elif action=='seminar':
                from services.academy_teaching_quality import AcademyTeachingQuality
                prompts=[AcademyTeachingQuality(service,service.model_profile).seminar_prompt(mid,data.get('chapters'),learner)]
            elif action=='chapter-review':
                prompts=[service.chapter_review_prompt(mid,data.get('response_id'),learner,critic=x) for x in (False,True)]
            elif action=='chapter-questions':
                prompts=[service.chapter_prompt(mid,data.get('chapter'),data.get('subject'),learner)]
            elif action=='guide':
                prompts=[service.guide_prompt(mid,cid,learner)]
            elif action=='tutor':
                prompts=[service.teaching_prompt(mid,cid,data.get('question'),learner)]
            else:
                prompts=[service.assessment_prompt(mid,cid,data.get('answer'),learner,critic=x) for x in (False,True)]
            return await teaching_run(service,model,mid,action,data,learner,prompts)
        except (ValueError,TypeError,KeyError,IndexError) as exc:
            raise HTTPException(400,str(exc))
    return router
