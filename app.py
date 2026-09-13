import getpass
import os

import click
from dotenv import load_dotenv
from flask import Flask


load_dotenv()

from auth import login_manager
from database.db import create_user, init_db
from routes import main_bp
from services.application_service import get_model_status


def register_cli_commands(app):
    @app.cli.command("create-admin")
    def create_admin_command():
        """Create the first administrator without storing a plain-text password."""
        name = click.prompt("Tên Admin").strip()
        email = click.prompt("Email").strip().lower()
        click.echo(
            "Lưu ý: mật khẩu sẽ không hiện ký tự hoặc dấu * khi nhập. "
            "Hãy gõ bình thường rồi nhấn Enter."
        )
        try:
            password = getpass.getpass("Mật khẩu (tối thiểu 8 ký tự): ")
            confirmation = getpass.getpass("Nhập lại mật khẩu: ")
        except (EOFError, KeyboardInterrupt) as error:
            raise click.ClickException(
                "Không thể đọc mật khẩu. Hãy chạy lệnh trong Terminal PowerShell "
                "của VS Code, không chạy trong Output hoặc Debug Console."
            ) from error

        if password != confirmation:
            raise click.ClickException("Mật khẩu xác nhận không khớp.")
        try:
            create_user(name, email, password, "admin")
        except ValueError as error:
            raise click.ClickException(str(error)) from error
        click.echo(f"Đã tạo tài khoản Admin: {email}")


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get(
        "FLASK_SECRET_KEY",
        os.environ.get("SECRET_KEY", "dev-change-this-secret-key"),
    )
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    login_manager.init_app(app)
    init_db()
    app.register_blueprint(main_bp, name="")

    @app.context_processor
    def inject_global_data():
        return {"global_model_status": get_model_status()}

    register_cli_commands(app)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
