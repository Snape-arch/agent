"""Security HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
import os


class SecurityAPI:
    def __init__(self, *,
        get_security_service: Callable[..., Any],
        output_root_provider: Callable[[], Any],
    ):
        self.get_security_service = get_security_service
        self.output_root_provider = output_root_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/security/audit', self.api_security_audit, methods=['GET'])
        self.router.add_api_route('/api/security/secrets', self.api_secret_register, methods=['POST'])
        self.router.add_api_route('/api/security/secrets', self.api_secret_list, methods=['GET'])
        self.router.add_api_route('/api/security/policy/check', self.api_security_policy_check, methods=['POST'])
        self.router.add_api_route('/api/security/policy/grants', self.api_security_policy_grants, methods=['GET'])
        self.router.add_api_route('/api/security/policy/grants', self.api_security_policy_grant_create, methods=['POST'])
        self.router.add_api_route('/api/security/policy/grants/{grant_id}', self.api_security_policy_grant_revoke, methods=['DELETE'])
        self.router.add_api_route('/api/security/appcontainer', self.api_appcontainer_status, methods=['GET'])
        self.router.add_api_route('/api/security/appcontainer/{action}', self.api_appcontainer_change, methods=['POST'])

    async def api_security_audit(self, action: str = "", decision: str = "", limit: int = 100):
        try:
            rows = self.get_security_service().audit(action, decision, limit)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        return JSONResponse({"events": rows, "count": len(rows)})


    async def api_secret_register(self, request: Request):
        data = await request.json()
        try:
            item = self.get_security_service().register_secret(data)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        return JSONResponse({"secret": item})


    async def api_secret_list(self):
        try:
            secrets = self.get_security_service().list_secrets()
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        return JSONResponse({"secrets": secrets})


    async def api_security_policy_check(self, request: Request):
        data = await request.json()
        try:
            result = self.get_security_service().check_policy(str(data.get("tool", "") or ""), data.get("arguments", {}))
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        return JSONResponse(result)


    async def api_security_policy_grants(self, include_expired: bool = False):
        try:
            grants = self.get_security_service().list_grants(include_expired)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        return JSONResponse({"grants": grants, "count": len(grants)})


    async def api_security_policy_grant_create(self, request: Request):
        data = await request.json()
        try:
            grant = self.get_security_service().create_grant(data)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        return JSONResponse({"grant": grant})


    async def api_security_policy_grant_revoke(self, grant_id: str):
        try:
            revoked = self.get_security_service().revoke_grant(grant_id)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        return JSONResponse({"revoked": bool(revoked), "grant_id": grant_id})


    async def api_appcontainer_status(self):
        from services.windows_appcontainer_boundary import WindowsAppContainerBoundary, WindowsFirewallPackageGuard

        boundary = WindowsAppContainerBoundary(os.environ.get("CLAWOS_APPCONTAINER_PROFILE", "ClawOS.CodingSandbox"))
        return JSONResponse({"appcontainer": boundary.status(), "firewall": WindowsFirewallPackageGuard().status()})


    async def api_appcontainer_change(self, action: str, request: Request):
        from services.windows_appcontainer_boundary import WindowsAppContainerBoundary, WindowsFirewallPackageGuard

        body = await request.json()
        if body.get("confirmed") is not True:
            raise HTTPException(409, "confirmed=true is required for system boundary changes")
        boundary = WindowsAppContainerBoundary(os.environ.get("CLAWOS_APPCONTAINER_PROFILE", "ClawOS.CodingSandbox"))
        firewall = WindowsFirewallPackageGuard()
        try:
            if action == "install":
                installed = boundary.install(confirmed=True)
                rule = firewall.install(installed["sid"], confirmed=True)
                return JSONResponse({"appcontainer": installed, "firewall": rule})
            if action == "uninstall":
                rule = firewall.remove(confirmed=True)
                removed = boundary.uninstall(confirmed=True)
                return JSONResponse({"appcontainer": removed, "firewall": rule})
            if action == "probe":
                workspace = (self.output_root_provider() / "coding" / "appcontainer-probe").resolve()
                workspace.mkdir(parents=True, exist_ok=True)
                return JSONResponse(boundary.probe(workspace, confirmed_acl=True))
            raise HTTPException(404, "Unknown AppContainer action")
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
            raise HTTPException(409, str(exc))
