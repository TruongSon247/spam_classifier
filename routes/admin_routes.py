import re

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.security import generate_password_hash

from auth import admin_required
from database.db import (
    count_active_admins,
    create_user,
    get_all_users,
    get_user_by_id,
    set_user_active,
    reset_user_password,
    update_user,
    update_user_role,
)
from routes import main_bp
from services.audit_service import log_audit


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validated_user_fields():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    role = request.form.get("role", "").strip().lower()
    if not name:
        raise ValueError("Họ tên không được để trống.")
    if len(name) > 100:
        raise ValueError("Họ tên không được vượt quá 100 ký tự.")
    if not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("Địa chỉ Email không hợp lệ.")
    if len(email) > 200:
        raise ValueError("Địa chỉ Email không được vượt quá 200 ký tự.")
    if role not in {"admin", "user"}:
        raise ValueError("Vai trò không hợp lệ.")
    return name, email, role


@main_bp.route("/users")
@admin_required
def users():
    return render_template("users.html", users=get_all_users())


@main_bp.route("/users/create", methods=["POST"])
@admin_required
def create_user_route():
    try:
        name, email, role = _validated_user_fields()
        user_id = create_user(
            name,
            email,
            request.form.get("password", ""),
            role,
        )
        log_audit("USER_CREATE", "user", user_id=int(current_user.id), target_type="user", target_id=user_id, description=f"Created user #{user_id} with role {role}.")
        flash("Đã tạo tài khoản mới.", "success")
    except ValueError as error:
        flash(str(error), "danger")
    return redirect(url_for("users"))


@main_bp.post("/users/<int:user_id>/edit")
@admin_required
def edit_user(user_id):
    row = get_user_by_id(user_id)
    if not row:
        abort(404)
    try:
        name, email, role = _validated_user_fields()
        if (
            row["role"] == "admin"
            and row["is_active"]
            and role == "user"
            and count_active_admins(exclude_user_id=user_id) == 0
        ):
            raise ValueError("Hệ thống phải còn ít nhất một Admin đang hoạt động.")
        update_user(user_id, name, email, role)
        log_audit("USER_UPDATE", "user", user_id=int(current_user.id), target_type="user", target_id=user_id, description=f"Updated user #{user_id}.")
        flash("Đã cập nhật thông tin người dùng.", "success")
    except ValueError as error:
        flash(str(error), "danger")
    return redirect(url_for("users"))


@main_bp.post("/users/<int:user_id>/reset-password")
@admin_required
def reset_user_password_route(user_id):
    if not get_user_by_id(user_id):
        abort(404)
    password = request.form.get("password", "")
    confirmation = request.form.get("password_confirmation", "")
    if len(password) < 8:
        flash("Mật khẩu phải có ít nhất 8 ký tự.", "danger")
    elif password != confirmation:
        flash("Mật khẩu xác nhận không khớp.", "danger")
    else:
        reset_user_password(user_id, generate_password_hash(password))
        log_audit("USER_PASSWORD_RESET", "user", user_id=int(current_user.id), target_type="user", target_id=user_id, description=f"Reset password for user #{user_id}.")
        flash("Đã đặt lại mật khẩu cho người dùng.", "success")
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
        enabled = not bool(row["is_active"])
        set_user_active(user_id, enabled)
        log_audit("USER_ENABLE" if enabled else "USER_DISABLE", "user", user_id=int(current_user.id), target_type="user", target_id=user_id, description=f"{'Enabled' if enabled else 'Disabled'} user #{user_id}.")
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
        log_audit("USER_ROLE_CHANGE", "user", user_id=int(current_user.id), target_type="user", target_id=user_id, description=f"Changed user #{user_id} role from {row['role']} to {role}.")
        flash("Đã cập nhật vai trò tài khoản.", "success")
    return redirect(url_for("users"))
