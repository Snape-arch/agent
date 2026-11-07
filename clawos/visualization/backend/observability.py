"""Dependency-free platform metrics and W3C trace-context correlation."""
from __future__ import annotations

import contextvars
import json
import os
import secrets
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.id_generator import IdGenerator
    from opentelemetry.trace import NonRecordingSpan, SpanContext, Status, StatusCode, TraceFlags, set_span_in_context
except ImportError:  # The source tree remains dependency-free unless OTLP is enabled.
    otel_trace = None

_lock = threading.RLock()
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
_gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
_histograms: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[list[int], int, float]] = {}
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
_span_id: contextvars.ContextVar[str] = contextvars.ContextVar("span_id", default="")
_parent_span_id: contextvars.ContextVar[str] = contextvars.ContextVar("parent_span_id", default="")
_started_at = time.time()
_otel_next_trace_id: contextvars.ContextVar[int] = contextvars.ContextVar("otel_next_trace_id", default=0)
_otel_next_span_id: contextvars.ContextVar[int] = contextvars.ContextVar("otel_next_span_id", default=0)


class _CorrelatedIdGenerator(IdGenerator if otel_trace else object):
    def generate_trace_id(self) -> int:
        return _otel_next_trace_id.get() or int.from_bytes(secrets.token_bytes(16), "big")

    def generate_span_id(self) -> int:
        return _otel_next_span_id.get() or int.from_bytes(secrets.token_bytes(8), "big")


def _configure_otel():
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip()
    if not endpoint or otel_trace is None:
        return None
    provider = TracerProvider(
        resource=Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "clawvision")}),
        id_generator=_CorrelatedIdGenerator(),
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    otel_trace.set_tracer_provider(provider)
    return otel_trace.get_tracer("clawvision.platform")


_otel_tracer = _configure_otel()

HISTOGRAM_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)


def _labels(labels: dict[str, object]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), str(value)) for key, value in labels.items()))


def inc(name: str, amount: float = 1, **labels: object) -> None:
    with _lock: _counters[(name, _labels(labels))] += amount


def gauge(name: str, value: float, **labels: object) -> None:
    with _lock: _gauges[(name, _labels(labels))] = value


def observe(name: str, value: float, **labels: object) -> None:
    sample=max(0,value);key=(name,_labels(labels))
    with _lock:
        buckets,count,total=_histograms.get(key,([0]*len(HISTOGRAM_BUCKETS),0,0.0))
        for index,bucket in enumerate(HISTOGRAM_BUCKETS):
            if sample <= bucket: buckets[index] += 1
        _histograms[key]=(buckets,count+1,total+sample)


def current_trace() -> dict[str, str]:
    return {"traceId": _trace_id.get(), "spanId": _span_id.get(), "parentSpanId": _parent_span_id.get()}


def current_traceparent() -> str:
    trace, current = _trace_id.get(), _span_id.get()
    return f"00-{trace}-{current}-01" if trace and current else ""


def adopt_traceparent(value: str | None) -> dict[str, str]:
    trace,parent = parse_trace_context(value); current = secrets.token_hex(8)
    _trace_id.set(trace); _span_id.set(current);_parent_span_id.set(parent)
    return {"traceId": trace, "spanId": current,"parentSpanId":parent}


def parse_traceparent(value: str | None) -> str:
    return parse_trace_context(value)[0]


def parse_trace_context(value: str | None) -> tuple[str,str]:
    parts = (value or "").strip().split("-")
    if len(parts) == 4 and len(parts[1]) == 32 and len(parts[2]) == 16 and parts[1] != "0" * 32 and parts[2] != "0"*16:
        try: int(parts[1], 16);int(parts[2],16); return parts[1].lower(),parts[2].lower()
        except ValueError: pass
    return secrets.token_hex(16),""


def record_span(name: str, trace_id: str, span_id: str, duration: float, *, parent_span_id: str = "", status: str = "ok", **attributes: object) -> None:
    """Record a completed span and emit one correlation-friendly JSON event."""
    observe("clawvision_span_duration_seconds", duration, span=name)
    inc("clawvision_spans_total", status=status, span=name)
    if _otel_tracer is not None:
        trace_token = _otel_next_trace_id.set(int(trace_id, 16))
        span_token = _otel_next_span_id.set(int(span_id, 16))
        context = None
        if parent_span_id:
            parent = SpanContext(int(trace_id, 16), int(parent_span_id, 16), True, TraceFlags(TraceFlags.SAMPLED), None)
            context = set_span_in_context(NonRecordingSpan(parent))
        try:
            ended_at = time.time_ns()
            item = _otel_tracer.start_span(name, context=context, attributes={key: str(value) for key, value in attributes.items()}, start_time=ended_at-int(duration*1_000_000_000))
            if status == "error": item.set_status(Status(StatusCode.ERROR))
            item.end(end_time=ended_at)
        finally:
            _otel_next_span_id.reset(span_token); _otel_next_trace_id.reset(trace_token)
    if os.environ.get("CLAWVISION_TRACE_LOG", "true").lower() in {"1", "true", "yes"}:
        print(json.dumps({"type": "span", "name": name, "traceId": trace_id, "spanId": span_id,
                          "parentSpanId": parent_span_id or None, "durationMs": round(duration * 1000, 3),
                          "status": status, "attributes": attributes}, ensure_ascii=False), flush=True)


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str
    started: float
    attributes: dict[str, object]

    @property
    def traceparent(self) -> str: return f"00-{self.trace_id}-{self.span_id}-01"


@contextmanager
def span(name: str, *, traceparent: str | None = None, **attributes: object) -> Iterator[Span]:
    inherited_trace,inherited_parent=parse_trace_context(traceparent) if traceparent else ("","")
    parent = inherited_parent or _span_id.get()
    trace = inherited_trace or _trace_id.get() or secrets.token_hex(16)
    item = Span(name, trace, secrets.token_hex(8), parent, time.perf_counter(), attributes)
    trace_token = _trace_id.set(trace); span_token = _span_id.set(item.span_id)
    error: Exception | None = None
    try:
        yield item
    except Exception as caught:
        error = caught; raise
    finally:
        duration = time.perf_counter() - item.started
        record_span(name, trace, item.span_id, duration, parent_span_id=parent,
                    status="error" if error else "ok", **attributes)
        _span_id.reset(span_token); _trace_id.reset(trace_token)


def _format_labels(labels: tuple[tuple[str, str], ...], extra: tuple[tuple[str, str], ...] = ()) -> str:
    values = labels + extra
    if not values: return ""
    escaped = [f'{key}="{value.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"' for key, value in values]
    return "{" + ",".join(escaped) + "}"


def render_prometheus() -> str:
    gauge("clawvision_uptime_seconds", time.time() - _started_at)
    lines: list[str] = []
    with _lock:
        for (name, labels), value in sorted(_counters.items()): lines.append(f"{name}{_format_labels(labels)} {value:g}")
        for (name, labels), value in sorted(_gauges.items()): lines.append(f"{name}{_format_labels(labels)} {value:g}")
        for (name, labels), (buckets,count,total) in sorted(_histograms.items()):
            for bucket,bucket_count in zip(HISTOGRAM_BUCKETS,buckets):
                lines.append(f'{name}_bucket{_format_labels(labels, (("le", str(bucket)),))} {bucket_count}')
            lines.append(f'{name}_bucket{_format_labels(labels, (("le", "+Inf"),))} {count}')
            lines.append(f"{name}_count{_format_labels(labels)} {count}")
            lines.append(f"{name}_sum{_format_labels(labels)} {total:g}")
    return "\n".join(lines) + "\n"


def reset_for_tests() -> None:
    with _lock: _counters.clear(); _gauges.clear(); _histograms.clear()


def metric_storage_size() -> dict[str,int]:
    """Expose bounded registry cardinality for operational tests, never samples."""
    with _lock:return {"counters":len(_counters),"gauges":len(_gauges),"histograms":len(_histograms)}
