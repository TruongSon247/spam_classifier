import logging
import os
from logging.handlers import RotatingFileHandler

from flask import current_app, has_app_context, has_request_context, request

from database.db import create_audit_log


AUDIT_CATEGORIES = (
    "auth",
    "dataset",
    "model",
    "mail",
    "feedback",
    "rule",
    "user",
    "api",
    "system",
)
AUDIT_STATUSES = ("success", "failed")
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 5


def configure_application_logging(app):
    log_dir = os.path.join(app.root_path, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.abspath(os.path.join(log_dir, "app.log"))

    existing_handler = next((
        handler
        for handler in app.logger.handlers
        if isinstance(handler, RotatingFileHandler)
        and os.path.abspath(getattr(handler, "baseFilename", "")) == log_path
    ), None)
    if existing_handler is None:
        existing_handler = RotatingFileHandler(
            log_path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        existing_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ))
        existing_handler.setLevel(logging.INFO)
        app.logger.addHandler(existing_handler)

    app.logger.setLevel(logging.INFO)
    app.logger.propagate = False
    for logger_name in (
        "services.application_service",
        "services.model_registry_service",
    ):
        service_logger = logging.getLogger(logger_name)
        if existing_handler not in service_logger.handlers:
            service_logger.addHandler(existing_handler)
        service_logger.setLevel(logging.INFO)
        service_logger.propagate = False
    app.logger.info("Application initialized")


def _clean(value, max_length):
    if value is None:
        return None
    return str(value).replace("\r", " ").replace("\n", " ")[:max_length]


def log_audit(
    action,
    category,
    user_id=None,
    target_type=None,
    target_id=None,
    description=None,
    status="success",
    ip_address=None,
):
    if category not in AUDIT_CATEGORIES:
        raise ValueError("Invalid audit category.")
    if status not in AUDIT_STATUSES:
        raise ValueError("Invalid audit status.")
    if ip_address is None and has_request_context():
        ip_address = request.remote_addr

    try:
        return create_audit_log(
            user_id,
            _clean(action, 80),
            category,
            _clean(target_type, 40),
            _clean(target_id, 100),
            _clean(description, 500),
            status,
            _clean(ip_address, 64),
        )
    except Exception:
        if has_app_context():
            current_app.logger.exception(
                "Unable to persist audit action=%s", _clean(action, 80)
            )
        return None
