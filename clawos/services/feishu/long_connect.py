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
import time
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
    """Start/stop lifecycle wrapper around the official SDK long-connection.

    ``running`` only reports that the SDK thread is alive. Because the SDK's
    ``start()`` blocks on an *infinite* auto-reconnect loop, a live thread does
    NOT mean a real WebSocket handshake occurred (e.g. bad credentials leave the
    thread alive forever while it retries). ``connected`` is the authoritative
    "handshake actually happened" signal: it is True only while the SDK client
    has a live connection object (``_conn``) established, and it reverts to
    False the moment the link drops. Never use ``running`` alone as proof of a
    connection (see runbook §5 and the handoff W2).

    ``client_factory`` is injectable so the handshake lifecycle can be driven
    deterministically in tests without a real network or credentials; it
    defaults to :func:`build_ws_client`.
    """

    def __init__(
        self,
        config: FeishuConfig,
        on_message: Callable[[dict], None],
        client_factory: Optional[Callable[[FeishuConfig, Callable[[dict], None]], object]] = None,
    ):
        self.config = config
        self._on_message = on_message
        self._client_factory = client_factory or build_ws_client
        self._client = None
        self._thread: Optional[threading.Thread] = None
        self._watch_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._running = False
        self._connected = threading.Event()
        self._last_error: Optional[str] = None

    @property
    def running(self) -> bool:
        return bool(
            self._running
            and self._thread is not None
            and self._thread.is_alive()
        )

    @property
    def connected(self) -> bool:
        """True only when the SDK has a real, live WS handshake right now.

        Requires the thread to be running AND the SDK connection object to be
        established. This is the signal callers must use for health/connected
        status — not ``running``.
        """
        return bool(self.running and self._connected.is_set())

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
            client = self._client_factory(self.config, self._on_message)
            self._client = client
            self._last_error = None
            self._connected.clear()

            # Wire the SDK reconnect observer so a re-established link is
            # reflected immediately; the watcher below also covers the first
            # connect (on_reconnected does NOT fire on the initial handshake).
            try:
                prev_reconnected = getattr(client, "on_reconnected", None)

                def _on_reconnected() -> None:
                    self._connected.set()
                    if callable(prev_reconnected):
                        try:
                            prev_reconnected()
                        except Exception:
                            pass

                client.on_reconnected = _on_reconnected
            except Exception:  # pragma: no cover - client without the hook
                pass

            def _run() -> None:
                try:
                    client.start()  # blocking until disconnect/stop
                except Exception as exc:  # pragma: no cover - live transport
                    self._last_error = str(exc)[:200]
                finally:
                    self._running = False
                    self._connected.clear()

            thread = threading.Thread(
                target=_run, name="feishu-long-connect", daemon=True
            )
            self._thread = thread
            self._running = True
            thread.start()

            # Handshake watcher: track the SDK's live connection object so
            # ``connected`` reflects the *actual* WS state (established on first
            # connect, cleared on drop/infinite-reconnect).
            watch = threading.Thread(
                target=self._watch_connection,
                args=(client,),
                name="feishu-long-connect-watch",
                daemon=True,
            )
            self._watch_thread = watch
            watch.start()

    def _watch_connection(self, client, interval: float = 0.05) -> None:
        while self._running:
            try:
                conn_live = getattr(client, "_conn", None) is not None
            except Exception:  # pragma: no cover - defensive
                conn_live = False
            if conn_live:
                self._connected.set()
            else:
                self._connected.clear()
            time.sleep(interval)
        self._connected.clear()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            self._running = False
            self._connected.clear()
            client = self._client
            self._client = None
        if client is not None:
            self._best_effort_disconnect(client, timeout)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        watch = self._watch_thread
        if watch is not None and watch.is_alive():
            watch.join(timeout=timeout)
        self._watch_thread = None

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
