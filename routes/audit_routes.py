import math

from flask import render_template, request

from auth import admin_required
from database.db import get_all_users, get_audit_logs, get_audit_statistics
from routes import main_bp
from services.audit_service import AUDIT_CATEGORIES, AUDIT_STATUSES


@main_bp.get("/admin/audit-logs")
@admin_required
def audit_logs():
    category = request.args.get("category", "all").strip().lower()
    status = request.args.get("status", "all").strip().lower()
    search = request.args.get("search", "").strip()
    user_value = request.args.get("user_id", "all").strip()
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 20
    if category not in {"all", *AUDIT_CATEGORIES}:
        category = "all"
    if status not in {"all", *AUDIT_STATUSES}:
        status = "all"
    try:
        user_id = int(user_value) if user_value != "all" else None
    except ValueError:
        user_id = None
        user_value = "all"
    entries, total = get_audit_logs(category, status, user_id, search, page, per_page)
    total_pages = max(1, math.ceil(total / per_page))
    if page > total_pages:
        page = total_pages
        entries, total = get_audit_logs(category, status, user_id, search, page, per_page)
    return render_template(
        "audit_logs.html", entries=entries, statistics=get_audit_statistics(),
        users=get_all_users(), categories=AUDIT_CATEGORIES, category=category,
        status=status, user_value=user_value, search=search, page=page,
        total_pages=total_pages, total=total,
    )
