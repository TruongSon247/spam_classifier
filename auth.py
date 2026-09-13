from functools import wraps

from flask import flash, redirect, url_for
from flask_login import LoginManager, UserMixin, current_user

from database.db import get_user_by_id


login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Vui lòng đăng nhập để tiếp tục."
login_manager.login_message_category = "warning"


class User(UserMixin):
    def __init__(self, row):
        self.id = str(row["id"])
        self.name = row["name"]
        self.email = row["email"]
        self.role = row["role"]
        self._is_active = bool(row["is_active"])

    @property
    def is_active(self):
        return self._is_active


@login_manager.user_loader
def load_user(user_id):
    try:
        row = get_user_by_id(int(user_id))
    except (TypeError, ValueError):
        return None
    return User(row) if row and bool(row["is_active"]) else None


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if current_user.role != "admin":
            flash("Bạn không có quyền truy cập chức năng này.", "danger")
            return redirect(url_for("index"))
        return view(*args, **kwargs)

    return wrapped_view
