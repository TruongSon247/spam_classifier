from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from auth import admin_required
from database.db import (
    count_active_admins,
    create_user,
    get_all_users,
    get_user_by_id,
    set_user_active,
    update_user_role,
)
from routes import main_bp


@main_bp.route("/users")
@admin_required
def users():
    return render_template("users.html", users=get_all_users())


@main_bp.route("/users/create", methods=["POST"])
@admin_required
def create_user_route():
    try:
        create_user(
            request.form.get("name", ""),
            request.form.get("email", ""),
            request.form.get("password", ""),
            request.form.get("role", "user"),
        )
        flash("Đã tạo tài khoản mới.", "success")
    except ValueError as error:
        flash(str(error), "danger")
    return redirect(url_for("users"))


@main_bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@admin_required
def toggle_user_active(user_id):
    row = get_user_by_id(user_id)
    if not row:
        flash("Không tìm thấy tài khoản.", "danger")
    elif user_id == int(current_user.id):
        flash("Bạn không thể vô hiệu hóa tài khoản đang đăng nhập.", "danger")
    elif row["role"] == "admin" and row["is_active"] and count_active_admins() <= 1:
        flash("Hệ thống phải còn ít nhất một Admin đang hoạt động.", "danger")
    else:
        set_user_active(user_id, not bool(row["is_active"]))
        flash("Đã cập nhật trạng thái tài khoản.", "success")
    return redirect(url_for("users"))


@main_bp.route("/users/<int:user_id>/role", methods=["POST"])
@admin_required
def change_user_role(user_id):
    row = get_user_by_id(user_id)
    role = request.form.get("role", "").strip().lower()
    if not row:
        flash("Không tìm thấy tài khoản.", "danger")
    elif role not in {"admin", "user"}:
        flash("Vai trò không hợp lệ.", "danger")
    elif (
        user_id == int(current_user.id)
        and role == "user"
        and count_active_admins(exclude_user_id=user_id) == 0
    ):
        flash("Không thể hạ quyền Admin cuối cùng của hệ thống.", "danger")
    else:
        update_user_role(user_id, role)
        flash("Đã cập nhật vai trò tài khoản.", "success")
    return redirect(url_for("users"))
