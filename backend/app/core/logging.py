from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.config import dictConfig
from time import perf_counter
from uuid import uuid4

from fastapi import Request

_request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)

_RESERVED_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = _request_id_context.get()
        if request_id:
            payload["request_id"] = request_id

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_ATTRS and not key.startswith("_")
        }
        if extras:
            payload.update(self._normalize_mapping(extras))

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=self._json_default)

    def _normalize_mapping(self, values: Mapping[str, object]) -> dict[str, object]:
        return {key: self._normalize_value(value) for key, value in values.items()}

    def _normalize_value(self, value: object) -> object:
        if isinstance(value, Mapping):
            return self._normalize_mapping(value)
        if isinstance(value, (list, tuple, set)):
            return [self._normalize_value(item) for item in value]
        return value

    def _json_default(self, value: object) -> object:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)


def configure_logging(*, level: str, environment: str, app_name: str) -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": "app.core.logging.JsonFormatter",
                }
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "stream": "ext://sys.stdout",
                },
                "stderr": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "stream": "ext://sys.stderr",
                },
            },
            "root": {
                "handlers": ["default"],
                "level": level,
            },
            "loggers": {
                "uvicorn": {"handlers": ["default"], "level": level, "propagate": False},
                "uvicorn.error": {
                    "handlers": ["stderr"],
                    "level": level,
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["default"],
                    "level": level,
                    "propagate": False,
                },
            },
        }
    )

    logging.getLogger(__name__).info(
        "Logging configured",
        extra={
            "event": "logging_configured",
            "environment": environment,
            "app_name": app_name,
            "stream": sys.stdout.name,
        },
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


async def log_request_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid4().hex
    token = _request_id_context.set(request_id)
    started = perf_counter()
    logger = get_logger("app.http")

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((perf_counter() - started) * 1000, 2)
        logger.exception(
            "Unhandled request error",
            extra={
                "event": "http_request_failed",
                "request": {
                    "method": request.method,
                    "path": request.url.path,
                    "query_string": request.url.query or None,
                },
                "client": request.client.host if request.client else None,
                "duration_ms": duration_ms,
            },
        )
        raise
    else:
        duration_ms = round((perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "Request completed",
            extra={
                "event": "http_request_completed",
                "request": {
                    "method": request.method,
                    "path": request.url.path,
                    "query_string": request.url.query or None,
                },
                "response": {"status_code": response.status_code},
                "client": request.client.host if request.client else None,
                "duration_ms": duration_ms,
            },
        )
        return response
    finally:
        _request_id_context.reset(token)
