"""Artifact object storage: local filesystem by default, S3/MinIO optionally."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any
from observability import inc, observe

ROOT = Path(__file__).resolve().parent.parent


def _instrument_store(cls):
    for operation in ("put_json", "get_json", "put_bytes", "get_bytes", "byte_size", "get_range", "delete", "health_check"):
        original = getattr(cls, operation)
        def wrapped(self, *args, __operation=operation, __original=original, **kwargs):
            started = time.perf_counter(); status = "ok"
            try: return __original(self, *args, **kwargs)
            except Exception:
                status = "error"; inc("clawvision_object_store_errors_total", kind=self.kind, operation=__operation); raise
            finally:
                observe("clawvision_object_store_operation_duration_seconds", time.perf_counter() - started, kind=self.kind, operation=__operation)
                inc("clawvision_object_store_operations_total", kind=self.kind, operation=__operation, status=status)
        setattr(cls, operation, wrapped)
    return cls


@_instrument_store
class LocalObjectStore:
    kind = "local"

    def __init__(self) -> None:
        self.root = Path(os.environ.get("CLAWVISION_OBJECT_DIR") or os.environ.get("ARTIFACT_ROOT") or ROOT / "data" / "objects").resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_json(self, key: str, value: Any) -> str:
        key_path = Path(key)
        if key_path.is_absolute() or ".." in key_path.parts:
            raise ValueError("invalid object key")
        path = self.root / key_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path = path.resolve()
        if os.path.commonpath((os.path.normcase(str(self.root)), os.path.normcase(str(path)))) != os.path.normcase(str(self.root)):
            raise ValueError("invalid object key")
        payload = json.dumps(value, ensure_ascii=False)
        handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return key

    def get_json(self, key: str) -> Any:
        key_path = Path(key)
        if key_path.is_absolute() or ".." in key_path.parts:
            raise ValueError("invalid object key")
        path = (self.root / key_path).resolve()
        if os.path.commonpath((os.path.normcase(str(self.root)), os.path.normcase(str(path)))) != os.path.normcase(str(self.root)):
            raise ValueError("invalid object key")
        return json.loads(path.read_text(encoding="utf-8"))

    def put_bytes(self, key: str, value: bytes, content_type: str = "application/octet-stream") -> str:
        key_path = Path(key)
        if key_path.is_absolute() or ".." in key_path.parts:
            raise ValueError("invalid object key")
        path = (self.root / key_path).resolve()
        if os.path.commonpath((os.path.normcase(str(self.root)), os.path.normcase(str(path)))) != os.path.normcase(str(self.root)):
            raise ValueError("invalid object key")
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return key

    def get_bytes(self, key: str) -> bytes:
        key_path = Path(key)
        if key_path.is_absolute() or ".." in key_path.parts:
            raise ValueError("invalid object key")
        path = (self.root / key_path).resolve()
        if os.path.commonpath((os.path.normcase(str(self.root)), os.path.normcase(str(path)))) != os.path.normcase(str(self.root)):
            raise ValueError("invalid object key")
        return path.read_bytes()

    def byte_size(self, key: str) -> int:
        return Path(self.query_uri(key)).stat().st_size

    def get_range(self, key: str, start: int, end: int) -> bytes:
        path = Path(self.query_uri(key)); size = path.stat().st_size
        if start < 0 or end < start or start >= size:
            raise ValueError("invalid byte range")
        with path.open("rb") as stream:
            stream.seek(start)
            return stream.read(min(end, size - 1) - start + 1)

    def query_uri(self, key: str) -> str:
        """Return a DuckDB-readable path without loading the object into Python."""
        key_path = Path(key)
        if key_path.is_absolute() or ".." in key_path.parts:
            raise ValueError("invalid object key")
        path = (self.root / key_path).resolve()
        if os.path.commonpath((os.path.normcase(str(self.root)), os.path.normcase(str(path)))) != os.path.normcase(str(self.root)):
            raise ValueError("invalid object key")
        return str(path)

    def configure_duckdb(self, connection) -> None:
        del connection

    def delete(self, key: str) -> None:
        key_path = Path(key)
        if key_path.is_absolute() or ".." in key_path.parts:
            raise ValueError("invalid object key")
        path = (self.root / key_path).resolve()
        if os.path.commonpath((os.path.normcase(str(self.root)), os.path.normcase(str(path)))) != os.path.normcase(str(self.root)):
            raise ValueError("invalid object key")
        path.unlink(missing_ok=True)

    def health_check(self) -> dict[str, Any]:
        probe = self.root / ".health"
        probe.write_text("ok", encoding="utf-8")
        readable = probe.read_text(encoding="utf-8") == "ok"
        probe.unlink(missing_ok=True)
        return {"ok": readable, "kind": self.kind, "root": str(self.root)}


@_instrument_store
class S3ObjectStore:
    kind = "s3"

    def __init__(self) -> None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as error:
            raise RuntimeError("S3/MinIO storage requires: pip install boto3") from error
        self.bucket = os.environ["S3_BUCKET"]
        self.endpoint_url = os.environ.get("S3_ENDPOINT_URL")
        self.access_key = os.environ.get("S3_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY_ID")
        self.secret_key = os.environ.get("S3_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY")
        self.region = os.environ.get("S3_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        self.client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            config=Config(connect_timeout=5, read_timeout=15, retries={"max_attempts": 5, "mode": "adaptive"}),
        )

    def put_json(self, key: str, value: Any) -> str:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.client.put_object(Bucket=self.bucket, Key=key, Body=payload, ContentType="application/json")
        return key

    def get_json(self, key: str) -> Any:
        result = self.client.get_object(Bucket=self.bucket, Key=key)
        return json.loads(result["Body"].read().decode("utf-8"))

    def put_bytes(self, key: str, value: bytes, content_type: str = "application/octet-stream") -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=value, ContentType=content_type)
        return key

    def get_bytes(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def byte_size(self, key: str) -> int:
        return int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])

    def get_range(self, key: str, start: int, end: int) -> bytes:
        if start < 0 or end < start:
            raise ValueError("invalid byte range")
        return self.client.get_object(Bucket=self.bucket, Key=key, Range=f"bytes={start}-{end}")["Body"].read()

    def query_uri(self, key: str) -> str:
        if not key or key.startswith("/") or ".." in Path(key).parts:
            raise ValueError("invalid object key")
        return f"s3://{self.bucket}/{key}"

    def configure_duckdb(self, connection) -> None:
        """Configure httpfs so DuckDB performs footer and row-group Range GETs."""
        try:
            connection.execute("LOAD httpfs")
        except Exception:
            connection.execute("INSTALL httpfs")
            connection.execute("LOAD httpfs")
        quote = lambda value: "'" + str(value or "").replace("'", "''") + "'"
        connection.execute(f"SET s3_region={quote(self.region)}")
        if self.access_key:
            connection.execute(f"SET s3_access_key_id={quote(self.access_key)}")
        if self.secret_key:
            connection.execute(f"SET s3_secret_access_key={quote(self.secret_key)}")
        if self.endpoint_url:
            endpoint = self.endpoint_url.removeprefix("https://").removeprefix("http://").rstrip("/")
            connection.execute(f"SET s3_endpoint={quote(endpoint)}")
            connection.execute(f"SET s3_use_ssl={'true' if self.endpoint_url.startswith('https://') else 'false'}")
            connection.execute("SET s3_url_style='path'")

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def health_check(self) -> dict[str, Any]:
        self.client.head_bucket(Bucket=self.bucket)
        return {"ok": True, "kind": self.kind, "bucket": self.bucket}


def create_object_store():
    return S3ObjectStore() if os.environ.get("ARTIFACT_STORE", "local").lower() in {"s3", "minio"} else LocalObjectStore()
