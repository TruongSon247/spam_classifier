from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from auth import admin_required
from database.db import (
    get_api_key,
    get_api_key_statistics,
    get_api_keys,
    set_api_key_active,
)
from routes import main_bp
from services.api_key_service import generate_api_key
from services.audit_service import log_audit


def _render_api_keys(new_api_key=None):
    return render_template(
        "api_keys.html",
        api_keys=get_api_keys(),
        statistics=get_api_key_statistics(),
        new_api_key=new_api_key,
    )


@main_bp.get("/admin/api-keys")
@admin_required
def admin_api_keys():
    return _render_api_keys()


@main_bp.post("/admin/api-keys/create")
@admin_required
def create_api_key_route():
    try:
        new_api_key = generate_api_key(
            request.form.get("name"), int(current_user.id)
        )
        log_audit("API_KEY_CREATE", "api", user_id=int(current_user.id), target_type="api_key", target_id=new_api_key["id"], description=f"Created API key {new_api_key['key_prefix']}.")
        flash("Đã tạo API Key. Key đầy đủ chỉ hiển thị lần này.", "success")
        return _render_api_keys(new_api_key)
    except ValueError as error:
        flash(str(error), "danger")
        return _render_api_keys(), 400


@main_bp.post("/admin/api-keys/<int:api_key_id>/toggle")
@admin_required
def toggle_api_key(api_key_id):
    api_key = get_api_key(api_key_id)
    if not api_key:
        abort(404)
    set_api_key_active(api_key_id, not bool(api_key["is_active"]))
    enabled = not bool(api_key["is_active"])
    log_audit("API_KEY_ENABLE" if enabled else "API_KEY_DISABLE", "api", user_id=int(current_user.id), target_type="api_key", target_id=api_key_id, description=f"{'Enabled' if enabled else 'Disabled'} API key {api_key['key_prefix']}.")
    flash("Đã cập nhật trạng thái API Key.", "success")
    return redirect(url_for("admin_api_keys"))


@main_bp.post("/admin/api-keys/<int:api_key_id>/revoke")
@admin_required
def revoke_api_key(api_key_id):
    api_key = get_api_key(api_key_id)
    if not api_key:
        abort(404)
    set_api_key_active(api_key_id, False)
    log_audit("API_KEY_DISABLE", "api", user_id=int(current_user.id), target_type="api_key", target_id=api_key_id, description=f"Disabled API key {api_key['key_prefix']}.")
    flash("API Key đã được vô hiệu hóa.", "success")
    return redirect(url_for("admin_api_keys"))


@main_bp.get("/api-docs")
@admin_required
def api_docs():
    return render_template("api_docs.html")
