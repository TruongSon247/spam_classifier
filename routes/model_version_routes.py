from flask import abort, current_app, flash, redirect, render_template, url_for
from flask_login import current_user

from auth import admin_required
from routes import main_bp
from services.model_registry_service import (
    get_active_model_version,
    get_model_version,
    get_model_versions,
    get_recent_model_events,
    rollback_model,
)
from services.audit_service import log_audit


@main_bp.route("/models")
@admin_required
def model_versions():
    versions = get_model_versions()
    return render_template(
        "model_versions.html",
        versions=versions,
        active_version=get_active_model_version(),
        events=get_recent_model_events(),
        chart_labels=[row["version"] for row in reversed(versions)],
        chart_accuracy=[
            round((row["accuracy"] or 0) * 100, 2)
            for row in reversed(versions)
        ],
        chart_f1=[
            round((row["f1"] or 0) * 100, 2)
            for row in reversed(versions)
        ],
    )


@main_bp.route("/models/<int:version_id>/rollback", methods=["POST"])
@admin_required
def rollback_model_version(version_id):
    version = get_model_version(version_id)
    if not version:
        abort(404)
    if version["is_active"]:
        flash("Phiên bản này đang được sử dụng.", "info")
        return redirect(url_for("model_versions"))
    active = get_active_model_version()
    try:
        rollback_model(version_id, int(current_user.id))
        from_version = active["version"] if active else "none"
        log_audit("MODEL_ROLLBACK", "model", user_id=int(current_user.id), target_type="model_version", target_id=version_id, description=f"Rollback {from_version} -> {version['version']}.")
        flash(
            f"Đã khôi phục và kích hoạt model {version['version']}.",
            "success",
        )
    except ValueError as error:
        log_audit("MODEL_ROLLBACK_FAILED", "model", user_id=int(current_user.id), target_type="model_version", target_id=version_id, description="Model rollback validation failed.", status="failed")
        flash(str(error), "danger")
    except Exception:
        current_app.logger.exception("Model rollback failed for version_id=%s", version_id)
        log_audit("MODEL_ROLLBACK_FAILED", "model", user_id=int(current_user.id), target_type="model_version", target_id=version_id, description="Model rollback could not be completed.", status="failed")
        flash("Không thể khôi phục phiên bản mô hình.", "danger")
    return redirect(url_for("model_versions"))
