"""Owner-only teaching bridge; public source capture never forwards browser credentials."""
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from services.research_learning import Conflict

def research_learning_router(factory,owner):
    router=APIRouter(prefix='/api/vision/research')
    async def call(request,method,*args):
        await owner(request)
        try:return await run_in_threadpool(lambda:getattr(factory(),method)('local-user',*args))
        except Conflict as e:raise HTTPException(409,str(e))
        except PermissionError as e:raise HTTPException(403,str(e))
        except LookupError:raise HTTPException(404,'研究学习记录不存在')
        except (ValueError,TypeError) as e:raise HTTPException(400,str(e))
        except Exception as e:raise HTTPException(503,'公开资料或存储操作暂未完成：'+type(e).__name__) from None
    async def body(request):
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>160000:raise HTTPException(413,'研究学习请求上限160KB')
        import json
        try:value=json.loads(raw)
        except (ValueError,UnicodeError):raise HTTPException(400,'请求需为JSON对象')
        if not isinstance(value,dict):raise HTTPException(400,'请求需为JSON对象')
        return value
    @router.get('/catalog')
    async def catalog(request:Request):return await call(request,'catalog')
    @router.get('/history')
    async def history(request:Request):return await call(request,'course_history')
    @router.post('/prepare')
    async def prepare(request:Request):
        await owner(request);return await call(request,'prepare',await body(request))
    @router.get('/cases/{cid}')
    async def case(cid:str,request:Request):return await call(request,'get_case',cid)
    @router.get('/cases/{cid}/papers/{pid}/pages/{page}')
    async def page(cid:str,pid:str,page:int,request:Request):return await call(request,'page',cid,pid,page)
    @router.get('/cases/{cid}/runs')
    async def runs(cid:str,request:Request,page:int=1):return await call(request,'runs',cid,page)
    @router.post('/cases/{cid}/runs')
    async def run(cid:str,request:Request):
        await owner(request);return await call(request,'run',cid,await body(request))
    @router.get('/runs/{rid}')
    async def report(rid:str,request:Request):return await call(request,'get_run',rid)
    @router.post('/runs/{rid}/attempts')
    async def attempts(rid:str,request:Request):
        await owner(request);return await call(request,'submit',rid,await body(request))
    @router.post('/runs/{rid}/views')
    async def save_view(rid:str,request:Request):
        await owner(request);return await call(request,'save_view',rid,await body(request))
    @router.get('/views/{vid}')
    async def view(vid:str,request:Request):return await call(request,'view',vid)
    @router.get('/runs/{rid}/export')
    async def export(rid:str,request:Request):
        value=await call(request,'export',rid)
        return JSONResponse(value,headers={'Content-Disposition':'attachment; filename="rag-literature.json"'})
    return router
