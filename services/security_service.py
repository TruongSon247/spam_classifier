import os

from cryptography.fernet import Fernet
from flask import current_app, flash, jsonify, render_template, request
from flask_wtf.csrf import CSRFError

from extensions import csrf


NO_STORE_PATHS = (
    "/login",
    "/users",
    "/admin/api-keys",
    "/admin/backups",
)


def validate_credential_key(app):
    key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if not key:
        app.logger.warning(
            "CREDENTIAL_ENCRYPTION_KEY is missing; mail connections are unavailable."
        )
        return
    try:
        Fernet(key.encode("utf-8"))
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY is not a valid Fernet key."
        ) from error


def _is_api_request():
    return request.path.startswith("/api/v1/")


def _error_response(status_code, message):
    if _is_api_request():
        return jsonify({"success": False, "error": message}), status_code
    return render_template(
        "error.html", status_code=status_code, message=message
    ), status_code


def register_security(app, api_blueprint):
    csrf.init_app(app)
    csrf.exempt(api_blueprint)

    @app.before_request
    def protect_web_forms():
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and not _is_api_request()
            and (
                not current_app.testing
                or current_app.config.get("WTF_CSRF_TEST_ENABLED", False)
            )
        ):
            csrf.protect()

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
            "img-src 'self' data:; "
            "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "connect-src 'self' https://accounts.google.com https://oauth2.googleapis.com https://gmail.googleapis.com; "
            "form-action 'self' https://accounts.google.com"
        )
        if request.path.startswith(NO_STORE_PATHS):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
        if app.config.get("APP_ENV") == "production" and request.is_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        if _is_api_request():
            return jsonify({"success": False, "error": "Invalid CSRF token."}), 400
        flash("Phiên biểu mẫu không hợp lệ hoặc đã hết hạn. Vui lòng thử lại.", "danger")
        return _error_response(400, "Không thể xác thực yêu cầu.")

    messages = {
        400: "Yêu cầu không hợp lệ.",
        403: "Bạn không có quyền thực hiện thao tác này.",
        404: "Không tìm thấy nội dung yêu cầu.",
        413: "File tải lên vượt quá giới hạn 10 MB.",
        429: "Bạn thao tác quá nhanh. Vui lòng thử lại sau.",
        500: "Không thể hoàn tất thao tác.",
    }

    for status_code, message in messages.items():
        def handler(error, code=status_code, safe_message=message):
            if code == 500:
                current_app.logger.error(
                    "Unhandled server error: %s", type(error).__name__
                )
            api_message = "Too many requests." if code == 429 else safe_message
            return _error_response(code, api_message)

        app.register_error_handler(status_code, handler)

