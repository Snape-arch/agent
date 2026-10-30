"""Small router; identity comes from existing server-issued collaboration sessions."""
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool


def research_watch_router(service, collaboration, worker_status, ai_ready=None):
    router = APIRouter(prefix='/api/research/watch')

    def owner(request):
        if request.method not in ('GET', 'HEAD'):
            origin = request.headers.get('origin')
            if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (request.url.scheme, request.url.netloc)):
                raise HTTPException(403, '拒绝跨站写入')
        return collaboration().identity(request)['id']

    async def call(request, method, *args):
        uid = await run_in_threadpool(owner, request)
        try:
            return await run_in_threadpool(lambda: getattr(service(), method)(uid, *args))
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc))

    async def body(request):
        raw = await request.body()
        if len(raw) > 16000:
            raise HTTPException(413, '请求过大')
        try:
            import json
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise HTTPException(400, '请求应为 JSON 对象')
        if not isinstance(value, dict):
            raise HTTPException(400, '请求应为 JSON 对象')
        return value

    @router.get('')
    async def state(request: Request):
        result = await call(request, 'state')
        result['worker'] = worker_status()
        return result

    @router.post('/subscriptions', status_code=201)
    async def create(request: Request):
        return await call(request, 'create', await body(request))

    @router.post('/subscriptions/{sid}/{action}')
    async def action(sid: str, action: str, request: Request):
        return await call(request, 'action', sid, action)

    @router.get('/feed')
    async def feed(request: Request, subscription_id: str = '', offset: int = Query(0, ge=0, le=1000000), limit: int = Query(30, ge=1, le=100)):
        return await call(request, 'feed', subscription_id, offset, limit)

    @router.get('/digests/{did}')
    async def digest(did: str, request: Request, offset: int = Query(0, ge=0, le=1000000), limit: int = Query(30, ge=1, le=100)):
        return await call(request, 'digest', did, offset, limit)

    @router.get('/snapshots/{snapid}')
    async def snapshot(snapid: str, request: Request):
        return await call(request, 'snapshot', snapid)

    @router.post('/notifications/{nid}/read')
    async def read(nid: str, request: Request):
        return await call(request, 'read', nid)

    @router.post('/classifications/{sid}/{pid}')
    async def classify(sid: str, pid: str, request: Request):
        data = await body(request)
        return await call(request, 'reclassify', sid, pid, data.get('labels'))

    async def metadata_call(request,method,*args):
        from services.research_metadata import ResearchMetadata
        uid=await run_in_threadpool(owner,request)
        try:return await run_in_threadpool(lambda:getattr(ResearchMetadata(service()),method)(uid,*args))
        except LookupError as exc:raise HTTPException(404,str(exc))
        except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))
        except Exception as exc:raise HTTPException(502,'元数据来源暂不可用：'+type(exc).__name__)

    @router.get('/papers/{pid}/metadata')
    async def paper_metadata(pid:str,request:Request):return await metadata_call(request,'get',pid)

    @router.post('/papers/{pid}/metadata')
    async def refresh_metadata(pid:str,request:Request):return await metadata_call(request,'refresh',pid,await body(request))

    async def synthesis_call(request, method, *args):
        from services.research_synthesis import ResearchSynthesis
        uid = await run_in_threadpool(owner, request)
        try:
            return await run_in_threadpool(lambda: getattr(ResearchSynthesis(service()), method)(uid, *args))
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc))

    @router.get('/syntheses')
    async def syntheses(request: Request):
        return await synthesis_call(request, 'list')

    @router.post('/syntheses', status_code=201)
    async def create_synthesis(request: Request):
        return await synthesis_call(request, 'create', await body(request))

    @router.get('/syntheses/{rid}')
    async def get_synthesis(rid: str, request: Request):
        return await synthesis_call(request, 'get', rid)

    @router.get('/syntheses/{rid}/export')
    async def export_synthesis(rid: str, request: Request):
        return await synthesis_call(request, 'export', rid)

    @router.post('/syntheses/{rid}/relations/{edge_id}')
    async def review_relation(rid: str, edge_id: str, request: Request):
        return await synthesis_call(request, 'review', rid, edge_id, await body(request))

    async def ai_call(request,method,*args):
        from services.research_ai import ResearchAI
        uid=await run_in_threadpool(owner,request)
        try:return await run_in_threadpool(lambda:getattr(ResearchAI(service()),method)(uid,*args))
        except LookupError as exc:raise HTTPException(404,str(exc))
        except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))

    @router.get('/ai/status')
    async def ai_status(request:Request):
        await run_in_threadpool(owner,request)
        return ai_ready() if ai_ready else dict(ready=False,reason='此预览未接入本地模型')

    @router.post('/syntheses/{rid}/ai',status_code=202)
    async def start_ai(rid:str,request:Request):
        await run_in_threadpool(owner,request)
        data=await body(request)
        if data!={'confirmed':True}:raise HTTPException(400,'请明确确认使用本地模型综合此份冻结语料')
        status=ai_ready() if ai_ready else dict(ready=False)
        if not status.get('ready'):raise HTTPException(503,'本地模型或后台综合服务未就绪；不会回退外部模型')
        return await ai_call(request,'enqueue',rid)

    @router.get('/syntheses/{rid}/ai')
    async def list_ai(rid:str,request:Request):return await ai_call(request,'list',rid)

    @router.get('/ai/jobs/{jid}')
    async def get_ai(jid:str,request:Request):return await ai_call(request,'get',jid)

    @router.post('/ai/jobs/{jid}/cancel')
    async def cancel_ai(jid:str,request:Request):return await ai_call(request,'cancel',jid)

    return router
