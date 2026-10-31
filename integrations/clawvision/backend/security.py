"""Opt-in multi-user authentication, RBAC, quotas and immutable audit records."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from database import connect

ROLES = {"viewer": 10, "researcher": 20, "admin": 30, "owner": 40}


def now() -> str: return datetime.now(timezone.utc).isoformat()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(derived).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, expected = stored.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt), int(rounds))
        return hmac.compare_digest(actual, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError): return False


def token_hash(token: str) -> str: return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    role: str
    scopes: tuple[str, ...]

    def permits(self, role: str) -> bool: return ROLES.get(self.role, 0) >= ROLES[role]
    def permits_scope(self, scope: str) -> bool: return "*" in self.scopes or scope in self.scopes


def bootstrap(email: str, password: str, tenant_name: str) -> tuple[Principal, str]:
    if len(password) < 12: raise ValueError("password must contain at least 12 characters")
    created = now(); user_id = "usr_" + uuid.uuid4().hex[:16]; tenant_id = "ten_" + uuid.uuid4().hex[:16]
    with connect() as db:
        if db.execute("SELECT 1 FROM users").fetchone(): raise ValueError("bootstrap is already complete")
        db.execute("INSERT INTO tenants(id,name,created_at) VALUES(?,?,?)", (tenant_id, tenant_name, created))
        db.execute("INSERT INTO users(id,email,password_hash,active,created_at) VALUES(?,?,?,?,?)", (user_id, email.lower(), hash_password(password), 1, created))
        db.execute("INSERT INTO memberships(tenant_id,user_id,role) VALUES(?,?,?)", (tenant_id, user_id, "owner"))
        db.execute("INSERT INTO tenant_quotas(tenant_id) VALUES(?)", (tenant_id,))
    principal = Principal(user_id, tenant_id, "owner", ("*",)); return principal, issue_token(principal, "bootstrap")


def issue_token(principal: Principal, name: str, scopes: list[str] | None = None, expires_hours: int | None = None) -> str:
    raw = "cv_" + secrets.token_urlsafe(36); token_id = "tok_" + uuid.uuid4().hex[:16]; values = scopes or list(principal.scopes)
    hours = expires_hours if expires_hours is not None else int(os.environ.get("CLAWVISION_TOKEN_HOURS", "12"))
    expires = (datetime.now(timezone.utc) + timedelta(hours=max(1, min(hours, 24 * 365)))).isoformat()
    with connect() as db: db.execute("INSERT INTO api_tokens(id,user_id,tenant_id,name,token_hash,scopes,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?)", (token_id, principal.user_id, principal.tenant_id, name, token_hash(raw), json.dumps(values), expires, now()))
    return raw


def login(email: str, password: str) -> tuple[Principal, str]:
    with connect() as db:
        row = db.execute("SELECT u.*,m.tenant_id,m.role FROM users u JOIN memberships m ON m.user_id=u.id WHERE u.email=? AND u.active=1 ORDER BY m.tenant_id LIMIT 1", (email.lower(),)).fetchone()
    if not row or not verify_password(password, row["password_hash"]): raise ValueError("invalid credentials")
    principal = Principal(row["id"], row["tenant_id"], row["role"], ("*",)); return principal, issue_token(principal, "login")


def authenticate(header: str | None) -> Principal | None:
    if os.environ.get("CLAWVISION_AUTH_MODE", "disabled").lower() == "disabled": return Principal("system", "default", "owner", ("*",))
    if not header or not header.startswith("Bearer "): return None
    with connect() as db:
        row = db.execute("SELECT t.user_id,t.tenant_id,t.scopes,m.role FROM api_tokens t JOIN users u ON u.id=t.user_id JOIN memberships m ON m.user_id=t.user_id AND m.tenant_id=t.tenant_id WHERE t.token_hash=? AND t.revoked_at IS NULL AND (t.expires_at IS NULL OR t.expires_at>?) AND u.active=1", (token_hash(header[7:].strip()), now())).fetchone()
    return Principal(row["user_id"], row["tenant_id"], row["role"], tuple(json.loads(row["scopes"]))) if row else None


def audit(principal: Principal | None, method: str, path: str, status: str, detail: dict | None = None) -> None:
    try:
        with connect() as db: db.execute("INSERT INTO audit_logs(id,tenant_id,user_id,method,path,action,status,detail,created_at) VALUES(?,?,?,?,?,?,?,?,?)", ("aud_" + uuid.uuid4().hex[:16], principal.tenant_id if principal else None, principal.user_id if principal else None, method, path, f"{method} {path}", status, json.dumps(detail or {}, ensure_ascii=False), now()))
    except Exception: pass


def check_run_quota(principal: Principal) -> None:
    if principal.tenant_id == "default": return
    with connect() as db:
        quota = db.execute("SELECT * FROM tenant_quotas WHERE tenant_id=?", (principal.tenant_id,)).fetchone()
        running = db.execute("SELECT COUNT(*) AS count FROM durable_tasks WHERE tenant_id=? AND status IN ('queued','leased')", (principal.tenant_id,)).fetchone()["count"]
        runs = db.execute("SELECT COUNT(*) AS count FROM runs WHERE tenant_id=?", (principal.tenant_id,)).fetchone()["count"]
    if quota and runs >= quota["max_runs"]: raise PermissionError("tenant run quota exceeded")
    if quota and running >= quota["max_concurrent_jobs"]: raise PermissionError("tenant concurrent job quota exceeded")


def check_task_quota(principal: Principal) -> None:
    """Enforce the shared task budget without consuming the historical run budget."""
    if principal.tenant_id == "default": return
    with connect() as db:
        quota = db.execute("SELECT max_concurrent_jobs FROM tenant_quotas WHERE tenant_id=?", (principal.tenant_id,)).fetchone()
        active = db.execute("SELECT COUNT(*) AS count FROM durable_tasks WHERE tenant_id=? AND status IN ('queued','leased')", (principal.tenant_id,)).fetchone()["count"]
    if quota and active >= quota["max_concurrent_jobs"]: raise PermissionError("tenant concurrent task quota exceeded")


def quota_status(principal: Principal) -> dict:
    with connect() as db:
        quota = db.execute("SELECT * FROM tenant_quotas WHERE tenant_id=?", (principal.tenant_id,)).fetchone()
        runs = db.execute("SELECT COUNT(*) AS count FROM runs WHERE tenant_id=?", (principal.tenant_id,)).fetchone()["count"]
        active = db.execute("SELECT COUNT(*) AS count FROM durable_tasks WHERE tenant_id=? AND status IN ('queued','leased')", (principal.tenant_id,)).fetchone()["count"]
        artifacts = db.execute("SELECT COUNT(*) AS count FROM artifacts a JOIN runs r ON r.id=a.run_id WHERE r.tenant_id=?", (principal.tenant_id,)).fetchone()["count"]
        usage=db.execute("SELECT storage_bytes FROM tenant_usage WHERE tenant_id=?",(principal.tenant_id,)).fetchone()
    return {"limits": dict(quota) if quota else {}, "usage": {"runs": runs, "activeTasks": active, "artifacts": artifacts,"storageBytes":int(usage["storage_bytes"] if usage else 0)}}


def reserve_storage(tenant_id: str, size: int) -> None:
    if tenant_id == "default" or size <= 0: return
    timestamp=now()
    with connect() as db:
        quota=db.execute("SELECT max_storage_bytes FROM tenant_quotas WHERE tenant_id=?",(tenant_id,)).fetchone()
        usage=db.execute("SELECT storage_bytes FROM tenant_usage WHERE tenant_id=?",(tenant_id,)).fetchone();current=int(usage["storage_bytes"] if usage else 0)
        if quota and current+size>int(quota["max_storage_bytes"]): raise PermissionError("tenant storage quota exceeded")
        db.execute("""INSERT INTO tenant_usage(tenant_id,storage_bytes,updated_at) VALUES(?,?,?)
          ON CONFLICT(tenant_id) DO UPDATE SET storage_bytes=tenant_usage.storage_bytes+excluded.storage_bytes,updated_at=excluded.updated_at""",(tenant_id,size,timestamp))


def list_tokens(principal: Principal) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT id,name,scopes,expires_at,revoked_at,created_at FROM api_tokens WHERE tenant_id=? AND user_id=? ORDER BY created_at DESC", (principal.tenant_id, principal.user_id)).fetchall()
    return [{"id": row["id"], "name": row["name"], "scopes": json.loads(row["scopes"]), "expiresAt": row["expires_at"], "revokedAt": row["revoked_at"], "createdAt": row["created_at"]} for row in rows]


def revoke_token(principal: Principal, token_id: str) -> bool:
    with connect() as db:
        cursor = db.execute("UPDATE api_tokens SET revoked_at=? WHERE id=? AND tenant_id=? AND (user_id=? OR ? IN ('admin','owner'))", (now(), token_id, principal.tenant_id, principal.user_id, principal.role))
        return getattr(cursor, "rowcount", 1) > 0


def create_member(principal: Principal, email: str, password: str, role: str) -> dict:
    if not principal.permits("admin"): raise PermissionError("admin role required")
    if role not in ROLES or role == "owner": raise ValueError("role must be viewer, researcher or admin")
    if len(password) < 12: raise ValueError("password must contain at least 12 characters")
    timestamp = now(); user_id = "usr_" + uuid.uuid4().hex[:16]
    with connect() as db:
        row = db.execute("SELECT id FROM users WHERE email=?", (email.lower(),)).fetchone()
        if row: user_id = row["id"]
        else: db.execute("INSERT INTO users(id,email,password_hash,active,created_at) VALUES(?,?,?,?,?)", (user_id, email.lower(), hash_password(password), 1, timestamp))
        db.execute("INSERT INTO memberships(tenant_id,user_id,role) VALUES(?,?,?)", (principal.tenant_id, user_id, role))
    return {"userId": user_id, "email": email.lower(), "role": role}


def list_members(principal: Principal) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT u.id,u.email,u.active,m.role,u.created_at FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.tenant_id=? ORDER BY u.email", (principal.tenant_id,)).fetchall()
    return [{"userId": row["id"], "email": row["email"], "active": bool(row["active"]), "role": row["role"], "createdAt": row["created_at"]} for row in rows]


def _fernet():
    try: from cryptography.fernet import Fernet
    except ImportError as error: raise RuntimeError("encrypted credentials require the cryptography package") from error
    key = os.environ.get("CLAWVISION_MASTER_KEY", "").encode()
    if not key: raise RuntimeError("CLAWVISION_MASTER_KEY is required for credential storage")
    return Fernet(key)


def save_credential(principal: Principal, provider: str, name: str, secret: str) -> str:
    if not principal.permits("admin"): raise PermissionError("admin role required")
    item_id = "cred_" + uuid.uuid4().hex[:16]; timestamp = now(); ciphertext = _fernet().encrypt(secret.encode()).decode()
    with connect() as db: db.execute("INSERT INTO credential_refs(id,tenant_id,provider,name,ciphertext,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (item_id, principal.tenant_id, provider, name, ciphertext, timestamp, timestamp))
    return item_id


def resolve_credential(principal: Principal, item_id: str) -> str:
    with connect() as db: row = db.execute("SELECT ciphertext FROM credential_refs WHERE id=? AND tenant_id=?", (item_id, principal.tenant_id)).fetchone()
    if not row: raise ValueError("credential reference not found")
    return _fernet().decrypt(row["ciphertext"].encode()).decode()
