from flask import current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user

from auth import admin_required
from routes import main_bp
from services.audit_service import log_audit
from services.backup_service import (
    BackupError,
    create_backup,
    delete_backup,
    format_file_size,
    get_backup_path,
    list_backups,
    restore_backup,
)


def _audit(action, filename=None, status="success", description=None):
    log_audit(
        action,
        "system",
        user_id=int(current_user.id),
        target_type="backup",
        target_id=filename,
        description=description,
        status=status,
    )


@main_bp.get("/admin/backups")
@admin_required
def admin_backups():
    backups = list_backups()
    return render_template(
        "backups.html",
        backups=backups,
        total_size=format_file_size(sum(item["file_size"] for item in backups)),
        latest_backup=backups[0] if backups else None,
    )


@main_bp.post("/admin/backups/create")
@admin_required
def create_backup_route():
    try:
        backup = create_backup(
            user_id=int(current_user.id), notes=request.form.get("notes", "")
        )
        _audit(
            "BACKUP_CREATE",
            backup["filename"],
            description=f"Created backup {backup['filename']}.",
        )
        flash("Đã tạo bản sao lưu thành công.", "success")
    except BackupError as error:
        _audit("BACKUP_CREATE", status="failed", description=str(error))
        flash(str(error), "danger")
    except Exception:
        current_app.logger.exception("Unexpected backup creation failure")
        _audit("BACKUP_CREATE", status="failed", description="Unexpected backup failure.")
        flash("Không thể tạo bản sao lưu.", "danger")
    return redirect(url_for("admin_backups"))


@main_bp.get("/admin/backups/<filename>/download")
@admin_required
def download_backup(filename):
    try:
        path = get_backup_path(filename)
        _audit(
            "BACKUP_DOWNLOAD",
            path.name,
            description=f"Downloaded backup {path.name}.",
        )
        return send_file(
            path,
            as_attachment=True,
            download_name=path.name,
            mimetype="application/zip",
        )
    except BackupError as error:
        _audit("BACKUP_DOWNLOAD", filename, "failed", str(error))
        flash(str(error), "danger")
        return redirect(url_for("admin_backups"))


@main_bp.post("/admin/backups/<filename>/restore")
@admin_required
def restore_backup_route(filename):
    if request.form.get("confirmation", "").strip().upper() != "RESTORE":
        flash("Nhập RESTORE để xác nhận khôi phục dữ liệu.", "danger")
        return redirect(url_for("admin_backups"))
    try:
        result = restore_backup(filename, user_id=int(current_user.id))
        _audit(
            "BACKUP_RESTORE",
            filename,
            description=(
                f"Restored backup {filename}; pre-restore backup "
                f"{result['pre_restore']['filename']}."
            ),
        )
        flash("Khôi phục dữ liệu thành công.", "success")
    except BackupError as error:
        _audit("BACKUP_RESTORE", filename, "failed", str(error))
        flash(str(error), "danger")
    except Exception:
        current_app.logger.exception("Unexpected restore failure for %s", filename)
        _audit("BACKUP_RESTORE", filename, "failed", "Unexpected restore failure.")
        flash("Không thể khôi phục bản sao lưu.", "danger")
    return redirect(url_for("admin_backups"))


@main_bp.post("/admin/backups/<filename>/delete")
@admin_required
def delete_backup_route(filename):
    try:
        deleted = delete_backup(filename)
        _audit(
            "BACKUP_DELETE",
            deleted,
            description=f"Deleted backup {deleted}.",
        )
        flash("Đã xóa bản sao lưu.", "success")
    except BackupError as error:
        _audit("BACKUP_DELETE", filename, "failed", str(error))
        flash(str(error), "danger")
    return redirect(url_for("admin_backups"))
