import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


APP_LOGGER_NAME = "translation_backend"
HTTP_LOGGER = logging.getLogger(f"{APP_LOGGER_NAME}.http")
REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024
LOG_FILE_BACKUP_COUNT = 5


def configure_logging(
    level: str = "INFO", log_file_path: str | Path | None = None
) -> None:
    logger = logging.getLogger(APP_LOGGER_NAME)
    numeric_level = logging.getLevelName(level.upper())
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    stream_handler = next(
        (
            handler
            for handler in logger.handlers
            if getattr(handler, "_translation_platform_handler_kind", None) == "stdout"
        ),
        None,
    )
    if stream_handler is None:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        handler._translation_platform_handler = True
        handler._translation_platform_handler_kind = "stdout"
        logger.addHandler(handler)

    configured_path = str(Path(log_file_path).resolve()) if log_file_path else None
    file_handlers = [
        handler
        for handler in logger.handlers
        if getattr(handler, "_translation_platform_handler_kind", None) == "file"
    ]
    matching_handler = next(
        (
            handler
            for handler in file_handlers
            if getattr(handler, "baseFilename", None) == configured_path
        ),
        None,
    )
    for handler in file_handlers:
        if handler is not matching_handler:
            logger.removeHandler(handler)
            handler.close()

    if configured_path and matching_handler is None:
        log_path = Path(configured_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_path,
            maxBytes=LOG_FILE_MAX_BYTES,
            backupCount=LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        handler._translation_platform_handler = True
        handler._translation_platform_handler_kind = "file"
        logger.addHandler(handler)

    logger.setLevel(numeric_level)
    logger.propagate = False


def install_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def log_http_request(request: Request, call_next):
        supplied_request_id = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = (
            supplied_request_id
            if REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else uuid4().hex
        )
        request.state.request_id = request_id
        started_at = perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (perf_counter() - started_at) * 1000
            HTTP_LOGGER.exception(
                "request_failed request_id=%s method=%s path=%s duration_ms=%.2f",
                request_id,
                request.method,
                request.url.path,
                duration_ms,
            )
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal Server Error"},
                headers={REQUEST_ID_HEADER: request_id},
            )

        duration_ms = (perf_counter() - started_at) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        HTTP_LOGGER.info(
            "request_completed request_id=%s method=%s path=%s status=%d duration_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
