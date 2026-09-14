import getpass
import os

import click
from dotenv import load_dotenv
from flask import Flask


load_dotenv()

from auth import login_manager
from config import load_security_config
from database.db import create_user, init_db
from extensions import limiter
from routes import main_bp
from routes.api_routes import api_bp
from services.application_service import get_model_status
from services.audit_service import configure_application_logging
from services.model_registry_service import initialize_model_registry
from services.security_service import register_security, validate_credential_key


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
    configure_application_logging(app)
    load_security_config(app)

    login_manager.init_app(app)
    limiter.init_app(app)
    validate_credential_key(app)
    init_db()
    try:
        initialize_model_registry()
    except Exception:
        app.logger.exception("Model registry initialization failed")
    app.register_blueprint(main_bp, name="")
    app.register_blueprint(api_bp)
    register_security(app, api_bp)

    @app.context_processor
    def inject_global_data():
        return {"global_model_status": get_model_status()}

    register_cli_commands(app)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
