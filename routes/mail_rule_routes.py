from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from auth import admin_required
from database.db import (
    delete_mail_rule,
    get_mail_rule,
    get_mail_rule_statistics,
    get_mail_rules,
    set_mail_rule_active,
)
from routes import main_bp
from services.mail_rule_service import (
    create_validated_mail_rule,
    re_evaluate_existing_messages,
)


@main_bp.route("/admin/mail-rules")
@admin_required
def admin_mail_rules():
    search = request.args.get("search", "").strip().lower()
    rule_filter = request.args.get("rule_type", "all").strip().lower()
    target_filter = request.args.get("target_type", "all").strip().lower()
    status_filter = request.args.get("status", "all").strip().lower()
    if rule_filter not in {"all", "whitelist", "blacklist"}:
        rule_filter = "all"
    if target_filter not in {"all", "email", "domain"}:
        target_filter = "all"
    if status_filter not in {"all", "active", "disabled"}:
        status_filter = "all"
    return render_template(
        "mail_rules.html",
        rules=get_mail_rules(
            search, rule_filter, target_filter, status_filter
        ),
        statistics=get_mail_rule_statistics(),
        search=search,
        rule_filter=rule_filter,
        target_filter=target_filter,
        status_filter=status_filter,
    )


@main_bp.route("/admin/mail-rules/add", methods=["POST"])
@admin_required
def add_mail_rule():
    try:
        create_validated_mail_rule(
            request.form.get("rule_type"),
            request.form.get("target_type"),
            request.form.get("target_value"),
            request.form.get("description"),
            int(current_user.id),
        )
        flash("Đã thêm quy tắc Email.", "success")
    except ValueError as error:
        flash(str(error), "danger")
    return redirect(url_for("admin_mail_rules"))


@main_bp.route("/admin/mail-rules/<int:id>/toggle", methods=["POST"])
@admin_required
def toggle_mail_rule(id):
    rule = get_mail_rule(id)
    if not rule:
        abort(404)
    set_mail_rule_active(id, not bool(rule["is_active"]))
    flash("Đã cập nhật trạng thái quy tắc.", "success")
    return redirect(url_for("admin_mail_rules"))


@main_bp.route("/admin/mail-rules/<int:id>/delete", methods=["POST"])
@admin_required
def remove_mail_rule(id):
    outcome = delete_mail_rule(id)
    if not outcome:
        abort(404)
    if outcome == "disabled":
        flash(
            "Quy tắc đã được vô hiệu hóa vì đang được tham chiếu bởi Email cũ.",
            "info",
        )
    else:
        flash("Đã xóa quy tắc Email.", "success")
    return redirect(url_for("admin_mail_rules"))


@main_bp.route("/admin/mail-rules/re-evaluate", methods=["POST"])
@admin_required
def re_evaluate_mail_rules():
    result = re_evaluate_existing_messages()
    flash(
        f"Đã đánh giá lại {result['updated']} Email; "
        f"giữ nguyên quarantine của {result['feedback_preserved']} Email có phản hồi.",
        "success",
    )
    return redirect(url_for("admin_mail_rules"))
