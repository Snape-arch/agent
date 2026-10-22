"""Authenticated education workbench; model suggestions never confirm graph edges."""
import asyncio
import json
import time
import uuid
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from services.academy_curriculum import LESSONS, TRACKS, RESOURCES, track_nodes
from services.academy_materials import digest
from services.academy_teaching_quality import AcademyTeachingQuality
from services.runtime_records import RunRecord, now_iso
from services.academy_model_contracts import graph_contract,review_contract,options


def strict_reply(reply):
    raw=reply['choices'][0]['message']['content']
    if not isinstance(raw,str) or len(raw)>600000:raise ValueError('模型输出为空或过大')
    def pairs(rows):
        result={}
        for key,value in rows:
            if key in result:raise ValueError('模型JSON包含重复字段')
            result[key]=value
        return result
    def constant(value):raise ValueError('模型JSON包含非有限数值')
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
    if not isinstance(value,dict):raise ValueError('模型需返回JSON对象')
    return value


def lab_router(factory,model,*,clock=time.perf_counter):
    router=APIRouter(prefix='/api/academy/learning/lab')

    def actor(request):return factory().identities.identity(request)['id']

    async def body(request):
        origin=request.headers.get('origin')
        if request.headers.get('sec-fetch-site')=='cross-site' or (origin and (urlsplit(origin).netloc!=request.url.netloc or urlsplit(origin).scheme!=request.url.scheme)):raise HTTPException(403,'拒绝跨站写入')
        if len(await request.body())>1024*1024:raise HTTPException(413,'请求超过1MB')
        try:value=await request.json()
        except ValueError:raise HTTPException(400,'请求需为JSON')
        if not isinstance(value,dict):raise HTTPException(400,'请求需为对象')
        return value

    async def call(fn,*args,**kwargs):
        try:return await asyncio.to_thread(fn,*args,**kwargs)
        except (ValueError,TypeError,KeyError,IndexError) as exc:raise HTTPException(400,str(exc))

    @router.get('/catalog')
    async def catalog(request:Request):
        actor(request)
        return dict(lessons=LESSONS,tracks=[dict(t,nodes=track_nodes(t)) for t in TRACKS],resources=RESOURCES,checked_at='2026-10-11')

    @router.get('/books')
    async def books(request:Request):return await call(factory().books,actor(request))

    @router.post('/join')
    async def join(request:Request):
        data=await body(request)
        existing_uid=actor(request) if request.headers.get('authorization') or request.cookies.get('clawos_session') else None
        result,token=await call(factory().join,data.get('code'),data.get('name'),existing_uid)
        response=JSONResponse(result)
        response.set_cookie('clawos_session',token,max_age=86400*7,httponly=True,samesite='strict',secure=request.url.scheme=='https')
        return response

    @router.post('/logout')
    async def logout(request:Request):
        await body(request)
        token=request.headers.get('authorization','')
        token=token[7:] if token.startswith('Bearer ') else request.cookies.get('clawos_session','')
        if token:
            def remove():
                from services.collaboration import digest as token_digest
                with factory().store._conn() as c:c.execute('DELETE FROM collaboration_sessions WHERE hash=?',(token_digest(token),))
            await call(remove)
        response=JSONResponse(dict(signed_out=True));response.delete_cookie('clawos_session')
        return response

    @router.get('/books/{mid}')
    async def state(mid:str,request:Request):return await call(factory().state,mid,actor(request))

    @router.get('/books/{mid}/route')
    async def route(mid:str,goal:str,request:Request):return await call(factory().graph.route,mid,actor(request),goal)

    @router.get('/books/{mid}/passage')
    async def passage(mid:str,citation:str,request:Request):return await call(factory().passage,mid,actor(request),citation)

    @router.get('/books/{mid}/history')
    async def history(mid:str,request:Request):return await call(factory().history,mid,actor(request))

    async def model_action(lab,mid,uid,action,data):
        with lab.store._conn() as c:owner,_=lab.authorize(c,mid,uid,('owner','teacher'))
        quality=AcademyTeachingQuality(lab.materials,lab.materials.model_profile)
        if action=='graph-propose':
            snapshot,prompt=await call(lab.graph.prompt,mid,uid,data.get('chapters'))
            prompts=[prompt];bank=None
        else:
            bank,items=await call(quality.calibration_prompts,mid,owner)
            prompts=[row[2] for row in items];snapshot=None
        revision=lab.materials.document(mid,owner)['payload']['revision']
        run=RunRecord(run_id='academy-lab-'+uuid.uuid4().hex,run_type='academy_teaching',title=action,status='running',actor=uid,scenario='education',inputs=dict(material_id=mid,revision=revision),workflow=dict(mode='shared_router_role_prompts',trace=[]))
        lab.store.save_run_record(run.to_dict());started=clock();replies=[]
        try:
            for index,prompt in enumerate(prompts):
                request_options=options(graph_contract(snapshot) if snapshot else review_contract(),'academy_graph' if snapshot else 'academy_review')
                messages=prompt
                # One bounded repair for a graph contract failure. CAS/ACL/save
                # failures are outside this loop and never retried or overwritten.
                for attempt in range(2 if snapshot else 1):
                    step=dict(role='graph_proposer' if snapshot else 'reviewer' if index%2 else 'teacher',prompt_digest=digest(messages),options_digest=digest(request_options),attempt=attempt+1,status='running')
                    run.workflow['trace'].append(step)
                    call_started=clock()
                    try:
                        reply=await asyncio.wait_for(model(messages,[],**request_options),180)
                        step.update(response_digest=digest(reply),model=reply.get('clawos_model',{}),elapsed_ms=round((clock()-call_started)*1000,2))
                        # A suspended machine may resume the response callback
                        # before asyncio's expired timer. Reject that late result.
                        if clock()-call_started>180:raise TimeoutError()
                    except Exception as exc:
                        code='timeout' if isinstance(exc,TimeoutError) else str(exc) if str(exc) in ('incomplete_output','timeout','provider_http_400','content_filtered','empty_final_answer','network_error') else 'transport_error'
                        step.update(status='failed',failure_code=code)
                        raise HTTPException(502,'模型输出达到限额，未保存；请减少所选章节后重试' if code=='incomplete_output' else '模型未完成或不支持结构化输出；已保存资料保留，本次不计为通过')
                    step.update(response_digest=digest(reply),model=reply.get('clawos_model',{}),status='received')
                    try:
                        value=strict_reply(reply)
                        if snapshot:await call(lab.graph.validate_proposal,mid,uid,snapshot,value)
                    except (ValueError,TypeError,KeyError,IndexError,HTTPException) as exc:
                        if isinstance(exc,HTTPException) and exc.status_code!=400:raise
                        step.update(status='contract_rejected',validation_error=str(getattr(exc,'detail',exc))[:500])
                        if not snapshot or attempt:raise HTTPException(400,'模型输出未通过原文或结构校验；图谱未修改：'+step['validation_error'])
                        raw=reply['choices'][0]['message'].get('content','')
                        messages=prompt+[dict(role='assistant',content=raw[:24000]),dict(role='user',content='上次输出未保存。校验错误：'+step['validation_error']+'。依据原始提供的片段重新返回完整本批JSON，逐字引用、不复用已有ID、不增加字段。')]
                        continue
                    step['status']='completed';replies.append(value);break
            if snapshot:result=await call(lab.graph.merge_proposal,mid,uid,snapshot,replies[0])
            else:
                def persist():
                    with lab.store._conn() as c:
                        c.execute('BEGIN IMMEDIATE');lab.authorize(c,mid,uid,('owner','teacher'))
                        current=json.loads(c.execute('SELECT payload FROM academy_materials WHERE id=?',(mid,)).fetchone()['payload'])['revision']
                        if current!=revision:raise ValueError('教材版本已变化，校准结果未保存')
                        return quality.save_calibration(mid,bank['id'],replies,owner,conn=c)
                result=await call(persist)
            run.status='completed';run.outputs=dict(evidence_validated=True,learning_effect_verified=False)
            return dict(result=result,run_id=run.run_id,model_calls=len(run.workflow['trace']),contract_repairs=sum(s['status']=='contract_rejected' for s in run.workflow['trace']))
        except HTTPException as exc:
            exc.headers=dict(exc.headers or {},**{'X-Academy-Run-Id':run.run_id});raise
        except (ValueError,TypeError,KeyError,IndexError) as exc:raise HTTPException(400,str(exc),headers={'X-Academy-Run-Id':run.run_id})
        finally:
            if run.status=='running':run.status='failed'
            for step in run.workflow['trace']:
                if step['status'] in ('running','received'):step['status']='cancelled'
            run.completed_at=now_iso();run.metrics=dict(model_calls=len(run.workflow['trace']),duration_ms=round((clock()-started)*1000,2))
            lab.store.save_run_record(run.to_dict())

    @router.post('/books/{mid}/{action}')
    async def change(mid:str,action:str,request:Request):
        data=await body(request);lab=factory();uid=actor(request)
        if action in ('graph-propose','calibration-run'):return await model_action(lab,mid,uid,action,data)
        if action=='graph':return await call(lab.graph.save,mid,uid,data.get('graph'),data.get('version'),data.get('revision'))
        if action=='index':return await call(lab.save_index,mid,uid,data.get('starts'),data.get('version'),data.get('revision'))
        if action=='invite':return await call(lab.invite,mid,uid,data.get('role'),data.get('target_uid'))
        if action=='revoke':return await call(lab.revoke,mid,uid,data.get('user_id'))
        if action=='teacher-draft':return await call(lab.save_draft,mid,uid,data.get('value'),data.get('version'),data.get('revision'))
        if action=='freeze-bank':return await call(lab.freeze_bank,mid,uid,data.get('version'))
        if action=='study':return await call(lab.evidence.create,mid,uid,data.get('protocol'),data.get('revision'),data.get('graph_version'))
        raise HTTPException(404,'未知教材操作')

    @router.get('/studies/{sid}/{action}')
    async def study_read(sid:str,action:str,request:Request):
        service=factory().evidence;uid=actor(request)
        if action=='view':return await call(service.view,sid,uid)
        if action=='packets':return await call(service.packets,sid,uid)
        if action=='adjudication':return await call(service.packets,sid,uid,adjudication=True)
        if action=='report':return await call(service.report,sid,uid)
        if action=='protocol':return await call(service.protocol,sid,uid)
        raise HTTPException(404,'未知测量操作')

    @router.post('/studies/{sid}/{action}')
    async def study_write(sid:str,action:str,request:Request):
        data=await body(request);service=factory().evidence;uid=actor(request)
        if action=='enroll':return await call(service.enroll,sid,uid)
        if action=='withdraw':return await call(service.withdraw,sid,uid,data.get('reason'))
        if action=='answer':return await call(service.answer,sid,uid,data.get('phase'),data.get('answers'),data.get('activity',''))
        if action=='grade':return await call(service.grade,sid,uid,data.get('packet_id'),data.get('scores'),data.get('reason'),data.get('quotes'))
        if action=='adjudicate':return await call(service.grade,sid,uid,data.get('packet_id'),data.get('scores'),data.get('reason'),data.get('quotes'),adjudication=True)
        raise HTTPException(404,'未知测量操作')
    return router
