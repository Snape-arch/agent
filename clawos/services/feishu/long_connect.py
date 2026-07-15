"""Official Feishu long-connection lifecycle (Phase 1b, spec §18 Phase 1).

Replaces the hand-rolled websocket handshake with the official ``lark-oapi``
SDK long-connection client. The connection is established using APP_ID /
APP_SECRET only -- there is no tenant-supplied URL or token. The blocking SDK
client is run inside a daemon thread so the connector can start and stop it
from the server lifespan.

Design notes / honest limitations:
- The SDK's ``ws.Client.start()`` blocks on its asyncio loop and exposes no
  public stop. ``stop()`` therefore does a best-effort clean disconnect
  (disable auto-reconnect + close the socket via the SDK's module-level loop)
  and otherwise relies on daemon-thread semantics so nothing leaks on process
  exit. This is acceptable for a single-process local agent OS.
- Events are marshalled back into the raw ``{header, event}`` dict shape so the
  existing ``connector_service.parse_message_event`` contract is preserved and
  the transport swap stays isolated to this module.
"""
from __future__ import annotations

import json
import threading
from typing import Callable, Optional

from .config import EVENT_MODE_LONG_CONNECTION, FeishuConfig


class FeishuLongConnectError(Exception):
    """Raised when the long-connection cannot be built or started."""


def build_ws_client(config: FeishuConfig, on_message: Callable[[dict], None]):
    """Build an official lark-oapi ws client bound to im.message.receive_v1.

    ``on_message`` receives the raw event dict (``header`` + ``event``) so the
    downstream ``parse_message_event`` normalization is unchanged.
    """
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import P2ImMessageReceiveV1  # noqa: F401
    except ImportError as exc:  # pragma: no cover - install guarded by ask-gate
        raise FeishuLongConnectError(
            "lark-oapi is required for long-connect; install it into the venv"
        ) from exc

    if not (config.app_id and config.app_secret):
        raise FeishuLongConnectError(
            "app_id/app_secret required for long-connect (no custom URL/token)"
        )

    def _dispatch(data) -> None:
        try:
            raw = json.loads(lark.JSON.marshal(data))
        except Exception:
            return
        try:
            on_message(raw)
        except Exception:
            # A single bad event must not tear down the connection.
            pass

    handler = (
        lark.EventDispatcherHandler.builder(
            config.verification_token or "",
            config.encrypt_key or "",
        )
        .register_p2_im_message_receive_v1(_dispatch)
        .build()
    )

    client = lark.ws.Client(
        config.app_id,
        config.app_secret,
        event_handler=handler,
        domain=config.base_url or "https://open.feishu.cn",
        log_level=lark.LogLevel.WARNING,
    )
    return client


class FeishuLongConnectManager:
    """Start/stop lifecycle wrapper around the official SDK long-connection."""

    def __init__(self, config: FeishuConfig, on_message: Callable[[dict], None]):
        self.config = config
        self._on_message = on_message
        self._client = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._running = False
        self._last_error: Optional[str] = None

    @property
    def running(self) -> bool:
        return bool(
            self._running
            and self._thread is not None
            and self._thread.is_alive()
        )

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            if self.config.event_mode != EVENT_MODE_LONG_CONNECTION:
                raise FeishuLongConnectError(
                    f"event_mode is {self.config.event_mode!r}; long-connect not enabled"
                )
            client = build_ws_client(self.config, self._on_message)
            self._client = client
            self._last_error = None

            def _run() -> None:
                try:
                    client.start()  # blocking until disconnect/stop
                except Exception as exc:  # pragma: no cover - live transport
                    self._last_error = str(exc)[:200]
                finally:
                    self._running = False

            thread = threading.Thread(
                target=_run, name="feishu-long-connect", daemon=True
            )
            self._thread = thread
            self._running = True
            thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            self._running = False
            client = self._client
            self._client = None
        if client is not None:
            self._best_effort_disconnect(client, timeout)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    @staticmethod
    def _best_effort_disconnect(client, timeout: float) -> None:
        try:
            setattr(client, "_auto_reconnect", False)
            import asyncio

            import lark_oapi.ws.client as _wsmod

            loop = getattr(_wsmod, "loop", None)
            disconnect = getattr(client, "_disconnect", None)
            if loop is not None and disconnect is not None and loop.is_running():
                future = asyncio.run_coroutine_threadsafe(disconnect(), loop)
                try:
                    future.result(timeout=timeout)
                except Exception:
                    pass
        except Exception:
            pass
