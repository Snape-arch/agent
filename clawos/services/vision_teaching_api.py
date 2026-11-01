"""Owner-only course experiment API, sharing the Vision gateway's identity check."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from services.vision_teaching import Conflict, VisionTeaching


def teaching_router(factory, owner):
    router=APIRouter(prefix='/api/vision/teaching')

    async def call(request, method, *args):
        await owner(request)
        try:return await run_in_threadpool(lambda:getattr(factory(),method)('local-user',*args))
        except Conflict as exc:raise HTTPException(409,str(exc))
        except LookupError:raise HTTPException(404,'实验记录不存在')
        except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))

    async def body(request):
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>16384:raise HTTPException(413,'教学实验请求上限16KB')
        import json
        try:return json.loads(raw)
        except ValueError:raise HTTPException(400,'请求需为JSON')

    @router.get('/catalog')
    async def catalog(request:Request):
        await owner(request);return VisionTeaching.catalog()

    @router.get('/books')
    async def books(request:Request):
        await owner(request)
        def load():
            service=factory()
            return service.lab().books('local-user') if service.lab else []
        return await run_in_threadpool(load)

    @router.get('/books/{mid}/nodes')
    async def nodes(mid:str,request:Request):
        await owner(request)
        def load():
            service=factory()
            if not service.lab:raise HTTPException(404,'教材服务不可用')
            graph=service.lab().graph.state(mid,'local-user')
            return {k:graph[k] for k in ('material_id','revision','version','title','nodes','stale')}
        return await run_in_threadpool(load)

    @router.post('/reports')
    async def create(request:Request):
        await owner(request)
        return await call(request,'create',await body(request))

    @router.get('/reports')
    async def history(request:Request,page:int=1,template:str|None=None):return await call(request,'history',page,template)

    @router.get('/reports/{rid}')
    async def get(rid:str,request:Request):return await call(request,'get',rid)

    @router.post('/reports/{rid}/reflections')
    async def reflect(rid:str,request:Request):
        await owner(request)
        return await call(request,'reflect',rid,await body(request))

    @router.get('/reports/{rid}/export')
    async def export(rid:str,request:Request,format:str='json'):
        record=await call(request,'get',rid)
        # Only the persisted UUID is used in attachment headers.
        name='teaching-'+record['report']['id']
        if format=='md':return PlainTextResponse(VisionTeaching.markdown(record),headers={'Content-Disposition':f'attachment; filename="{name}.md"'})
        if format!='json':raise HTTPException(400,'只支持json/md导出')
        return JSONResponse(record,headers={'Content-Disposition':f'attachment; filename="{name}.json"'})
    return router
