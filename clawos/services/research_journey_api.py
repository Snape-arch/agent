"""Private shared-paper/course gateway; no arbitrary file or model endpoints."""
import json
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import Response,JSONResponse
from starlette.concurrency import run_in_threadpool
from services.research_learning import Conflict
from services.research_grounded import bank

def journey_router(journey,grounded,ready,owner):
    router=APIRouter(prefix='/api/vision/research')
    async def invoke(request,factory,method,*args):
        await owner(request)
        try:return await run_in_threadpool(lambda:getattr(factory(),method)('local-user',*args))
        except Conflict as e:raise HTTPException(409,str(e))
        except PermissionError as e:raise HTTPException(403,str(e))
        except LookupError:raise HTTPException(404,'研究学习记录或捕获原件不存在')
        except (ValueError,TypeError) as e:raise HTTPException(400,str(e))
        except Exception as e:raise HTTPException(503,'操作未完成：'+type(e).__name__) from None
    async def body(request):
        await owner(request);raw=bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw)>160000:raise HTTPException(413,'研究学习请求上限160KB')
        try:value=json.loads(raw)
        except (ValueError,UnicodeError):raise HTTPException(400,'需要JSON对象')
        if not isinstance(value,dict):raise HTTPException(400,'需要JSON对象')
        return value
    @router.get('/cases/{cid}/journey')
    async def dashboard(cid:str,request:Request):return await invoke(request,journey,'dashboard',cid)
    @router.get('/cases/{cid}/papers/{pid}/pdf')
    async def pdf(cid:str,pid:str,request:Request,download:bool=False):
        name,raw=await invoke(request,journey,'pdf',cid,pid)
        return Response(raw,media_type='application/pdf',headers={'Content-Disposition':('attachment' if download else 'inline')+'; filename="'+name+'"','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    @router.post('/cases/{cid}/papers/{pid}/note')
    async def note(cid:str,pid:str,request:Request):return await invoke(request,journey,'save_note',cid,pid,await body(request))
    @router.get('/cases/{cid}/papers/{pid}/pdf-page/{page}')
    async def pdf_page(cid:str,pid:str,page:int,request:Request):
        return JSONResponse(await invoke(request,journey,'pdf_page',cid,pid,page),headers={'Cache-Control':'no-store'})
    @router.post('/cases/{cid}/papers/{pid}/import')
    async def imported(cid:str,pid:str,request:Request):return await invoke(request,journey,'import_paper',cid,pid,await body(request))
    @router.post('/cases/{cid}/units/{unit}/checkpoint')
    async def checkpoint(cid:str,unit:str,request:Request):return await invoke(request,journey,'checkpoint',cid,unit,await body(request))
    @router.get('/answer-bank')
    async def questions(request:Request):await owner(request);return bank()
    @router.get('/answer-status')
    async def status(request:Request):await owner(request);return ready()
    @router.get('/cases/{cid}/answers')
    async def jobs(cid:str,request:Request):return await invoke(request,grounded,'list',cid)
    @router.post('/cases/{cid}/answers')
    async def enqueue(cid:str,request:Request):
        data=await body(request)
        # Restoration of an existing receipt must work even when the model is now offline.
        existing=await invoke(request,grounded,'retry',cid,data)
        if existing:return existing
        if not ready().get('ready'):raise HTTPException(503,'本地模型未配置或后台服务未运行；不启动权重、不外部回退')
        return await invoke(request,grounded,'enqueue',cid,data)
    @router.get('/answers/{jid}')
    async def job(jid:str,request:Request):return await invoke(request,grounded,'get',jid)
    @router.post('/answers/{jid}/cancel')
    async def cancel(jid:str,request:Request):
        if await body(request)!={}:raise HTTPException(400,'取消操作不接受额外参数')
        return await invoke(request,grounded,'cancel',jid)
    @router.post('/answers/{jid}/review')
    async def review(jid:str,request:Request):
        if await body(request)!={}:raise HTTPException(400,'评审操作不接受额外参数')
        return await invoke(request,grounded,'create_review',jid)
    @router.post('/answers/{jid}/reflection')
    async def reflection(jid:str,request:Request):
        if await body(request)!={}:raise HTTPException(400,'反思提交不接受额外参数')
        return await invoke(request,grounded,'reflect',jid)
    @router.get('/answers/{jid}/export')
    async def export(jid:str,request:Request):
        value=await invoke(request,grounded,'export',jid)
        return JSONResponse(value,headers={'Content-Disposition':'attachment; filename="research-answer-evidence.json"','Cache-Control':'no-store'})
    return router
