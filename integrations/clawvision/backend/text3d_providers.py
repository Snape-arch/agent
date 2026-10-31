"""Pluggable high-quality Text-to-3D provider contracts.

GPU providers are intentionally isolated behind either a JSON-lines command or an
operator-configured HTTP endpoint. ClawVision never imports model runtimes into the API process.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import sys
import urllib.request
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class ProviderResult:
    content: bytes
    format: str
    stats: dict


PROVIDERS = {
    "local-implicit": {"label": "Local implicit preview", "kind": "local", "imageConditioning": False, "requiresGpu": False, "qualityTier":"preview"},
    "local-semantic": {"label": "Local semantic PBR + rigged mesh", "kind": "local", "imageConditioning": False, "requiresGpu": False, "qualityTier":"standard"},
    "local-neural": {"label": "Local neural Text-to-3D Worker", "kind": "command", "imageConditioning": True, "requiresGpu": True, "inputModes":["text","image"], "qualityTier":"production"},
    "trellis": {"label": "Microsoft TRELLIS", "kind": "command", "imageConditioning": True, "requiresGpu": True, "inputModes": ["text", "image"]},
    "hunyuan3d": {"label": "Tencent Hunyuan3D", "kind": "command", "imageConditioning": True, "requiresGpu": True, "inputModes": ["image"]},
    "triposr": {"label": "TripoSR", "kind": "command", "imageConditioning": True, "requiresGpu": True, "inputModes": ["image"]},
    "external": {"label": "External Text-to-3D API", "kind": "http", "imageConditioning": True, "requiresGpu": False},
    "meshy": {"label": "Meshy API · Preview + PBR Refine", "kind": "managed-api", "imageConditioning": False, "requiresGpu": False, "inputModes": ["text"]},
    "tripo": {"label": "Tripo API · Text/Image to Model", "kind": "managed-api", "imageConditioning": True, "requiresGpu": False, "inputModes": ["text", "image"]},
}


def provider_catalog() -> list[dict]:
    items = []
    for provider_id, metadata in PROVIDERS.items():
        configured = provider_id in {"local-implicit","local-semantic"}
        if metadata["kind"] == "command":
            configured = bool(os.environ.get(f"TEXT3D_{provider_id.upper()}_COMMAND"))
        elif metadata["kind"] == "http":
            configured = bool(os.environ.get("TEXT3D_EXTERNAL_URL"))
        elif provider_id == "meshy":
            configured = bool(os.environ.get("TEXT3D_MESHY_API_KEY"))
        elif provider_id == "tripo":
            configured = bool(os.environ.get("TEXT3D_TRIPO_API_KEY"))
        items.append({"id": provider_id, **metadata, "configured": configured})
    return items


def _command_provider(provider: str, request: dict, timeout: int, progress: Callable[[int, str], None], cancelled: Callable[[], bool]) -> ProviderResult:
    command = os.environ.get(f"TEXT3D_{provider.upper()}_COMMAND", "").strip()
    if not command:
        raise RuntimeError(f"{provider} is not configured; set TEXT3D_{provider.upper()}_COMMAND")
    # Windows CreateProcess accepts a command-line string without invoking a shell;
    # POSIX requires an argv list.
    args = command if sys.platform == "win32" else shlex.split(command)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", creationflags=flags)
    assert process.stdin and process.stdout
    process.stdin.write(json.dumps(request, ensure_ascii=True)); process.stdin.close()
    final = None
    for line in process.stdout:
        if cancelled():
            process.terminate(); raise RuntimeError("cancelled")
        event = json.loads(line)
        if event.get("type") == "progress":
            progress(int(event.get("progress", 0)), str(event.get("stage") or provider))
        elif event.get("type") == "result":
            final = event
    process.wait(timeout=timeout)
    if process.returncode or not final:
        detail = process.stderr.read()[-1500:] if process.stderr else ""
        raise RuntimeError(detail or f"{provider} returned no mesh")
    if process.stdout: process.stdout.close()
    if process.stderr: process.stderr.close()
    return ProviderResult(base64.b64decode(final["content"]), str(final.get("format") or "obj").lower(),
                          {**final.get("stats", {}), "provider": provider, "nonParametric": True})


def _external_provider(request: dict, timeout: int) -> ProviderResult:
    endpoint = os.environ.get("TEXT3D_EXTERNAL_URL", "").strip()
    if not endpoint.startswith("https://") and not (endpoint.startswith("http://127.0.0.1") or endpoint.startswith("http://localhost")):
        raise RuntimeError("TEXT3D_EXTERNAL_URL must use HTTPS or localhost")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    api_key = os.environ.get("TEXT3D_EXTERNAL_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    call = urllib.request.Request(endpoint, data=json.dumps(request, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(call, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return ProviderResult(base64.b64decode(payload["content"]), str(payload.get("format") or "obj").lower(),
                          {**payload.get("stats", {}), "provider": "external", "nonParametric": True})


def _safe_base(name: str, default: str) -> str:
    value=os.environ.get(name,default).rstrip("/")
    if value.startswith("https://") or value.startswith("http://127.0.0.1") or value.startswith("http://localhost"):
        return value
    raise RuntimeError(f"{name} must use HTTPS or localhost")


def _json_call(url: str, method: str, key: str, payload: dict | None, timeout: int) -> dict:
    data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None
    call=urllib.request.Request(url,data=data,method=method,headers={"Authorization":f"Bearer {key}","Content-Type":"application/json","Accept":"application/json","User-Agent":"ClawVision/0.11"})
    with urllib.request.urlopen(call,timeout=timeout) as response: return json.loads(response.read().decode())


def _download(url: str, timeout: int) -> bytes:
    if not url.startswith("https://") and not url.startswith("http://127.0.0.1") and not url.startswith("http://localhost"):
        raise RuntimeError("provider returned an unsafe asset URL")
    with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"ClawVision/0.11"}),timeout=timeout) as response:
        payload=response.read(128*1024*1024+1)
    if len(payload)>128*1024*1024: raise RuntimeError("provider asset exceeds 128 MB")
    return payload


def _poll_task(fetch, cancelled, progress, timeout: int, label: str, success, failure):
    deadline=time.monotonic()+timeout; interval=max(.05,float(os.environ.get("TEXT3D_API_POLL_SECONDS","2")))
    while time.monotonic()<deadline:
        if cancelled(): raise RuntimeError("cancelled")
        task=fetch(); status=str(task.get("status") or "").upper(); value=int(task.get("progress") or 0)
        progress(value,label)
        if success(status): return task
        if failure(status):
            detail = task.get("task_error")
            if isinstance(detail, dict): detail = detail.get("message")
            raise RuntimeError(str(detail or task.get("error") or f"{label} failed"))
        time.sleep(interval)
    raise TimeoutError(f"{label} exceeded {timeout}s")


def _meshy_provider(request: dict, timeout: int, progress, cancelled) -> ProviderResult:
    key=os.environ.get("TEXT3D_MESHY_API_KEY",""); base=_safe_base("TEXT3D_MESHY_BASE_URL","https://api.meshy.ai/openapi/v2")
    if not key: raise RuntimeError("Meshy is not configured; set TEXT3D_MESHY_API_KEY")
    target=max(10000,min(300000,int(request.get("targetPolycount") or 80000)))
    created=_json_call(base+"/text-to-3d","POST",key,{"mode":"preview","prompt":request["prompt"],"should_remesh":True,"target_polycount":target,"target_formats":["glb"]},timeout)
    preview_id=str(created["result"]); progress(5,"meshy-preview")
    preview=_poll_task(lambda:_json_call(base+f"/text-to-3d/{preview_id}","GET",key,None,min(timeout,60)),cancelled,lambda p,s:progress(min(45,5+int(p*.4)),s),timeout,"meshy-preview",lambda s:s=="SUCCEEDED",lambda s:s in {"FAILED","EXPIRED","CANCELED"})
    refined=_json_call(base+"/text-to-3d","POST",key,{"mode":"refine","preview_task_id":preview_id,"enable_pbr":True,"target_formats":["glb"]},timeout)
    refine_id=str(refined["result"]); progress(50,"meshy-refine")
    task=_poll_task(lambda:_json_call(base+f"/text-to-3d/{refine_id}","GET",key,None,min(timeout,60)),cancelled,lambda p,s:progress(50+int(p*.45),s),timeout,"meshy-refine",lambda s:s=="SUCCEEDED",lambda s:s in {"FAILED","EXPIRED","CANCELED"})
    asset_url=str(task.get("model_urls",{}).get("glb") or "")
    if not asset_url: raise RuntimeError("Meshy returned no GLB asset URL")
    return ProviderResult(_download(asset_url,timeout),"glb",{"provider":"meshy","providerTaskId":refine_id,"previewTaskId":preview_id,"consumedCredits":task.get("consumed_credits"),"nonParametric":True,"pbr":True})


def _tripo_provider(request: dict, timeout: int, progress, cancelled) -> ProviderResult:
    key=os.environ.get("TEXT3D_TRIPO_API_KEY",""); base=_safe_base("TEXT3D_TRIPO_BASE_URL","https://openapi.tripo3d.ai/v3")
    if not key: raise RuntimeError("Tripo is not configured; set TEXT3D_TRIPO_API_KEY")
    body={"prompt":request["prompt"],"model":os.environ.get("TEXT3D_TRIPO_MODEL","tripo-v3.1"),"texture":True,"pbr":True}
    created=_json_call(base+"/generation/text-to-model","POST",key,body,timeout); task_id=str(created.get("data",{}).get("task_id") or created.get("task_id") or "")
    if not task_id: raise RuntimeError("Tripo returned no task id")
    task=_poll_task(lambda:_json_call(base+f"/tasks/{task_id}","GET",key,None,min(timeout,60)).get("data",{}),cancelled,progress,timeout,"tripo-generation",lambda s:s=="SUCCESS",lambda s:s in {"FAILED","CANCELLED","EXPIRED"})
    asset_url=str(task.get("output",{}).get("model_url") or "")
    if not asset_url: raise RuntimeError("Tripo returned no model asset URL")
    return ProviderResult(_download(asset_url,timeout),"glb",{"provider":"tripo","providerTaskId":task_id,"nonParametric":True,"pbr":True})


def generate_reference_image(prompt: str, timeout: int) -> str:
    endpoint=os.environ.get("TEXT3D_IMAGE_PROVIDER_URL","").strip()
    if not endpoint.startswith("https://") and not (endpoint.startswith("http://127.0.0.1") or endpoint.startswith("http://localhost")):
        raise RuntimeError("this provider requires an image; upload one or configure TEXT3D_IMAGE_PROVIDER_URL")
    headers={"Content-Type":"application/json","Accept":"application/json"}; key=os.environ.get("TEXT3D_IMAGE_PROVIDER_API_KEY")
    if key: headers["Authorization"]=f"Bearer {key}"
    call=urllib.request.Request(endpoint,data=json.dumps({"prompt":prompt,"responseFormat":"base64"}).encode(),headers=headers,method="POST")
    with urllib.request.urlopen(call,timeout=timeout) as response: payload=json.loads(response.read().decode())
    image=str(payload.get("imageBase64") or payload.get("data",{}).get("base64") or "")
    base64.b64decode(image,validate=True)
    return image


def run_provider(provider: str, request: dict, timeout: int, progress: Callable[[int, str], None], cancelled: Callable[[], bool]) -> ProviderResult:
    if provider not in PROVIDERS or PROVIDERS[provider]["kind"] == "local":
        raise ValueError("a configured high-quality provider is required")
    if PROVIDERS[provider]["kind"] == "command":
        return _command_provider(provider, request, timeout, progress, cancelled)
    if provider == "meshy": return _meshy_provider(request,timeout,progress,cancelled)
    if provider == "tripo": return _tripo_provider(request,timeout,progress,cancelled)
    progress(58, "external-provider")
    result = _external_provider(request, timeout)
    if cancelled():
        raise RuntimeError("cancelled")
    return result
