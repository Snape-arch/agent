"""Transport-neutral application errors and RFC 9457-style problem details."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApplicationError(Exception):
    message: str
    code: str = "internal_error"
    status: int = 500
    detail: dict | None = None

    def __str__(self) -> str:
        return self.message


class NotFoundError(ApplicationError):
    def __init__(self, message: str = "resource not found", *, detail: dict | None = None):
        super().__init__(message, "not_found", 404, detail)


class ValidationError(ApplicationError):
    def __init__(self, message: str, *, detail: dict | None = None):
        super().__init__(message, "validation_error", 400, detail)


class ConflictError(ApplicationError):
    def __init__(self, message: str, *, detail: dict | None = None):
        super().__init__(message, "conflict", 409, detail)


def problem_details(message: str, status: int, request_id: str, *, code: str | None = None, detail: dict | None = None) -> dict:
    names = {400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 409: "Conflict", 413: "Content Too Large", 500: "Internal Server Error", 502: "Bad Gateway"}
    return {
        "type": f"https://clawvision.dev/problems/{code or 'request-error'}",
        "title": names.get(int(status), "Request Error"),
        "status": int(status),
        "code": code or "request_error",
        "error": message,
        "requestId": request_id,
        **({"detail": detail} if detail else {}),
    }
