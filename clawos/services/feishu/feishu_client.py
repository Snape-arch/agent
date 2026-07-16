"""Real Feishu HTTP client (synchronous).

Implements the minimal Feishu OpenAPI surface needed for the connector:
  - tenant_access_token (cached, single safe refresh on auth failure)
  - approval instance create / query (native approval gate)
  - message send (text / post) with caller-supplied uuid idempotency key
  - health check (no secrets leaked)

The connector service is synchronous and runs in the request path, so the
client uses a blocking httpx.Client. Feishu sends are low-frequency; brief
blocking is acceptable. All network errors normalize into FeishuClientError
with a stable `category`.
"""
from __future__ import annotations

import json
import time

import httpx

from .config import FeishuConfig


# Stable error categories used by the connector for gating / retry decisions.
AUTH = "auth"
PERMISSION = "permission"
SCOPE = "scope"
RATE_LIMIT = "rate_limit"
TIMEOUT = "timeout"
APPROVAL_INVALID = "approval_invalid"
NETWORK = "network"
TERMINAL = "terminal"
CONFIG_ERR = "config"


# Feishu business error codes mapped to a category. Unknown codes fall back to
# TERMINAL. Verify against the live tenant before relying on a specific mapping.
_AUTH_CODES = {99991663, 99991664, 99991665, 99991666, 99991667}
_PERMISSION_CODES = {10012, 10013, 11200, 11201, 11202, 11235, 99991668, 22003, 22004}


class FeishuClientError(Exception):
    def __init__(self, message: str, *, category: str = TERMINAL, raw_code: int | None = None):
        super().__init__(message)
        self.category = category
        self.raw_code = raw_code


class FeishuClient:
    def __init__(self, config: FeishuConfig, http_client: httpx.Client | None = None):
        self.config = config
        self._client = http_client
        self._token: str | None = None
        self._token_expire_at: float = 0.0

    # ---- low level HTTP -------------------------------------------------
    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=httpx.Timeout(self.config.send_timeout_seconds))
        return self._client

    def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None

    def _unwrap(self, resp: httpx.Response) -> dict:
        if resp.status_code == 401:
            raise FeishuClientError(resp.text[:200] or "unauthorized", category=AUTH)
        if resp.status_code == 403:
            raise FeishuClientError(resp.text[:200] or "forbidden", category=PERMISSION)
        if resp.status_code == 429:
            raise FeishuClientError("rate limited", category=RATE_LIMIT)
        if resp.status_code >= 500:
            raise FeishuClientError(f"server error {resp.status_code}", category=TERMINAL)
        try:
            data = resp.json()
        except Exception:
            raise FeishuClientError(f"invalid response: {resp.text[:200]}", category=TERMINAL)
        code = int(data.get("code", 0) or 0)
        if code != 0:
            msg = data.get("msg") or f"feishu error {code}"
            if code in _AUTH_CODES:
                raise FeishuClientError(msg, category=AUTH, raw_code=code)
            if code in _PERMISSION_CODES:
                cat = SCOPE if code == 99991668 else PERMISSION
                raise FeishuClientError(msg, category=cat, raw_code=code)
            if code == 60012:
                raise FeishuClientError(msg, category=APPROVAL_INVALID, raw_code=code)
            if code in {99991660, 99991661}:
                raise FeishuClientError(msg, category=RATE_LIMIT, raw_code=code)
            raise FeishuClientError(msg, category=TERMINAL, raw_code=code)
        return data.get("data", data)

    def _call(self, method: str, url: str, *, json=None, params=None, _retry_auth: bool = True):
        try:
            resp = self._http().request(
                method,
                url,
                json=json,
                params=params,
                headers={"Authorization": f"Bearer {self._token}"} if self._token else {},
                timeout=httpx.Timeout(self.config.send_timeout_seconds),
            )
        except httpx.TimeoutException:
            raise FeishuClientError("request timed out", category=TIMEOUT)
        except FeishuClientError:
            raise
        except Exception as exc:  # network / connection errors
            raise FeishuClientError(f"network error: {exc}", category=NETWORK)
        try:
            return self._unwrap(resp)
        except FeishuClientError as err:
            if err.category == AUTH and _retry_auth and self._token is not None:
                self._token = None
                self._ensure_token()
                return self._call(method, url, json=json, params=params, _retry_auth=False)
            raise

    # ---- auth -----------------------------------------------------------
    def _ensure_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expire_at - 30:
            return self._token
        url = f"{self.config.base_url}/open-apis/auth/v3/tenant_access_token/internal"
        try:
            resp = self._http().post(
                url,
                json={"app_id": self.config.app_id, "app_secret": self.config.app_secret},
                timeout=httpx.Timeout(self.config.send_timeout_seconds),
            )
        except httpx.TimeoutException:
            raise FeishuClientError("token request timed out", category=TIMEOUT)
        except Exception as exc:
            raise FeishuClientError(f"token request failed: {exc}", category=NETWORK)
        try:
            data = resp.json()
        except Exception:
            raise FeishuClientError(f"invalid token response: {resp.text[:200]}", category=TERMINAL)
        code = data.get("code")
        if code is None or int(code) != 0:
            raise FeishuClientError(data.get("msg") or "token error", category=AUTH)
        self._token = data.get("tenant_access_token")
        self._token_expire_at = now + int(data.get("expire", 7200))
        return self._token

    # ---- approval -------------------------------------------------------
    def create_approval_instance(
        self,
        *,
        approval_code: str,
        form: list,
        title: str | None = None,
        user_id: str | None = None,
        open_id: str | None = None,
        uuid: str | None = None,
    ) -> dict:
        self._ensure_token()
        body = {
            "approval_code": approval_code,
            "form": json.dumps(form, ensure_ascii=False),
        }
        if title:
            body["title"] = title
        if user_id:
            body["user_id"] = user_id
        if open_id:
            body["open_id"] = open_id
        if uuid:
            body["uuid"] = uuid
        return self._call("POST", f"{self.config.base_url}/open-apis/approval/v4/instances", json=body)

    def get_approval_instance(self, instance_code: str, *, user_id: str | None = None, open_id: str | None = None) -> dict:
        self._ensure_token()
        params: dict = {}
        if user_id:
            params["user_id"] = user_id
        if open_id:
            params["open_id"] = open_id
        return self._call(
            "GET",
            f"{self.config.base_url}/open-apis/approval/v4/instances/{instance_code}",
            params=params,
        )

    # ---- send -----------------------------------------------------------
    def send_message(
        self,
        *,
        receive_id_type: str,
        receive_id: str,
        msg_type: str,
        content: str | dict,
        uuid: str,
    ) -> dict:
        self._ensure_token()
        if isinstance(content, (dict, list)):
            content_str = json.dumps(content, ensure_ascii=False)
        else:
            content_str = content
        body = {
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": content_str,
            "uuid": uuid,
        }
        return self._call(
            "POST",
            f"{self.config.base_url}/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
            json=body,
        )

    # ---- health ---------------------------------------------------------
    def health_check(self) -> dict:
        out = {
            "configured": self.config.is_configured(),
            "live": self.config.live,
            "auth_ok": None,
            "message_permission": "unknown",
            "approval_configured": bool(self.config.approval_definition_code),
            "connection": "not_tested",
        }
        if not self.config.is_configured():
            out["connection"] = "skipped_not_configured"
            return out
        try:
            self._ensure_token()
            out["auth_ok"] = True
            out["connection"] = "ok"
            out["message_permission"] = "configured" if self.config.allowed_chat_ids else "unknown"
        except FeishuClientError as exc:
            out["auth_ok"] = False
            out["connection"] = "error"
            out["error_category"] = exc.category
            out["error"] = str(exc)
        return out

    # ---- long connect (official lark-oapi SDK) -------------------------
    def start_long_connect(self, handler) -> None:
        """Connect to the Feishu long-connection via the official SDK (blocking).

        The connection is established from APP_ID / APP_SECRET only -- there is
        no tenant-supplied websocket URL or token (spec §18 Phase 1). This call
        blocks on the SDK event loop; use ``FeishuLongConnectManager`` for a
        start/stop lifecycle in the server. ``handler`` is a callable receiving
        the raw event dict (``header`` + ``event``).
        """
        from .long_connect import build_ws_client

        client = build_ws_client(self.config, handler)
        client.start()
