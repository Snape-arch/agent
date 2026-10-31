"""Same-origin, local-owner gateway; strips user credentials and preserves streams."""
from pathlib import Path
from urllib.parse import urlsplit, quote
import httpx
import anyio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from services.collaboration import direct_owner


def vision_router(runtime,collaboration,static_dir):
    router=APIRouter();static=Path(static_dir).resolve()
    async def owner(request):
        if not direct_owner(request):raise HTTPException(403,'实验工作区当前仅开放给本机所有者；文档协作授权不包含实验权限')
        uid=await run_in_threadpool(lambda:collaboration().identity(request))
        if uid['id']!='local-user':raise HTTPException(403,'实验权限不足')
        origin=request.headers.get('origin')
        if request.headers.get('sec-fetch-site')=='cross-site' or origin and (urlsplit(origin).scheme,urlsplit(origin).netloc)!=(request.url.scheme,request.url.netloc):raise HTTPException(403,'拒绝跨站实验请求')
    @router.get('/api/vision/runtime')
    async def status(request:Request):await owner(request);return await run_in_threadpool(runtime().status)
    async def action(request,method):
        await owner(request)
        if await request.body() not in (b'',b'{}'):raise HTTPException(400,'实验服务操作不接受配置或路径参数')
        try:return await run_in_threadpool(getattr(runtime(),method))
        except (ValueError,RuntimeError) as exc:raise HTTPException(503,str(exc))
    @router.post('/api/vision/start')
    async def start(request:Request):return await action(request,'start')
    @router.post('/api/vision/stop')
    async def stop(request:Request):return await action(request,'close')
    @router.api_route('/api/vision/service/{path:path}',methods=['GET','HEAD','POST','PUT','PATCH','DELETE'])
    async def proxy(path:str,request:Request):
        await owner(request)
        if not path or '\\' in path or any(p in ('.','..') for p in path.split('/')):raise HTTPException(400,'实验路径无效')
        if path.startswith('auth/') and path!='auth/me' or path.startswith('__clawos_') or path.startswith('credentials'):
            raise HTTPException(403,'整合工作区的身份与凭据由ClawOS管理')
        try:base,secret=await run_in_threadpool(runtime().endpoint)
        except LookupError as exc:raise HTTPException(503,str(exc))
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>32*1024*1024:raise HTTPException(413,'单次实验请求上限32MB')
        headers={k:v for k,v in request.headers.items() if k.lower() in {'content-type','accept','range','if-range','if-none-match','if-match','last-event-id'}}
        headers['X-ClawOS-Vision-Gateway']=secret
        client=httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=httpx.Timeout(30,read=None,connect=5))
        try:
            target=base+'/api/'+quote(path,safe='/')+('?' + request.url.query if request.url.query else '')
            upstream=await client.send(client.build_request(request.method,target,content=bytes(body),headers=headers),stream=True)
        except Exception:
            await client.aclose();raise HTTPException(502,'实验服务连接中断') from None
        outgoing={k:v for k,v in upstream.headers.items() if k.lower() not in {'connection','transfer-encoding','set-cookie','server','date'} and not k.lower().startswith('access-control-')}
        async def stream():
            try:
                async for chunk in upstream.aiter_raw():yield chunk
            finally:
                with anyio.CancelScope(shield=True):
                    await upstream.aclose();await client.aclose()
        return StreamingResponse(stream(),status_code=upstream.status_code,headers=outgoing)
    @router.get('/academy/vision')
    async def redirect():return RedirectResponse('/academy/vision/',status_code=307)
    @router.get('/academy/vision/{path:path}')
    async def frontend(path:str=''):
        target=(static/(path or 'index.html')).resolve()
        if not target.is_relative_to(static) or not target.is_file():raise HTTPException(404,'实验工作区资源未构建或不存在')
        return FileResponse(target,headers={'Cache-Control':'no-cache' if target.name=='index.html' else 'public, max-age=31536000, immutable'})
    return router
