import io
import os
import re
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from flask import Flask

import database.db as db
from app import app
from config import load_security_config
from extensions import limiter
from routes import dataset_routes
from services.api_key_service import generate_api_key
from services.security_service import validate_credential_key


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSRF_PATTERN = re.compile(rb'name="csrf_token" value="([^"]+)"')


class SecurityHardeningTest(unittest.TestCase):
    def setUp(self):
        self.root = PROJECT_ROOT / "temp" / f"security_test_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self.original_db_path = db.DB_PATH
        self.original_dataset_path = dataset_routes.DATASET_PATH
        db.DB_PATH = str(self.root / "database.db")
        dataset_routes.DATASET_PATH = str(self.root / "dataset.csv")
        Path(dataset_routes.DATASET_PATH).write_text(
            "label,text\nham,Existing safe sample\nspam,Free prize now\n",
            encoding="utf-8",
        )
        db.init_db()
        self.admin_id = db.create_user(
            "Security Admin", "security-admin@example.com", "Password123!", "admin"
        )
        self.user_id = db.create_user(
            "Security User", "security-user@example.com", "Password123!", "user"
        )
        app.config.update(
            TESTING=True,
            WTF_CSRF_TEST_ENABLED=False,
            RATELIMIT_TEST_ENABLED=False,
        )
        limiter.reset()
        self.client = app.test_client()

    def tearDown(self):
        limiter.reset()
        app.config.update(
            WTF_CSRF_TEST_ENABLED=False,
            RATELIMIT_TEST_ENABLED=False,
        )
        db.DB_PATH = self.original_db_path
        dataset_routes.DATASET_PATH = self.original_dataset_path
        shutil.rmtree(self.root, ignore_errors=True)

    def csrf_token(self, client=None):
        response = (client or self.client).get("/login")
        match = CSRF_PATTERN.search(response.data)
        self.assertIsNotNone(match)
        return match.group(1).decode()

    def login(self, email="security-admin@example.com"):
        return self.client.post(
            "/login", data={"email": email, "password": "Password123!"}
        )

    def test_csrf_rejects_missing_token_and_accepts_valid_token(self):
        app.config["WTF_CSRF_TEST_ENABLED"] = True
        rejected = self.client.post(
            "/login",
            data={"email": "security-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(rejected.status_code, 400)

        token = self.csrf_token()
        accepted = self.client.post(
            "/login",
            data={
                "email": "security-admin@example.com",
                "password": "Password123!",
                "csrf_token": token,
                "remember": "on",
            },
        )
        self.assertEqual(accepted.status_code, 302)
        cookies = accepted.headers.getlist("Set-Cookie")
        remember_cookie = next(value for value in cookies if value.startswith("remember_token="))
        self.assertIn("HttpOnly", remember_cookie)
        self.assertIn("SameSite=Lax", remember_cookie)
        self.assertNotIn("; Secure", remember_cookie)

    def test_every_post_form_contains_csrf_token(self):
        pattern = re.compile(
            r'<form\b[^>]*\bmethod=["\']POST["\'][^>]*>(.*?)</form>',
            re.IGNORECASE | re.DOTALL,
        )
        count = 0
        missing = []
        for path in (PROJECT_ROOT / "templates").glob("*.html"):
            content = path.read_text(encoding="utf-8")
            for match in pattern.finditer(content):
                count += 1
                if 'name="csrf_token"' not in match.group(1):
                    missing.append(path.name)
        self.assertGreaterEqual(count, 30)
        self.assertEqual(missing, [])

    def test_login_and_api_rate_limits_have_correct_responses(self):
        app.config["RATELIMIT_TEST_ENABLED"] = True
        login_client = app.test_client()
        for _ in range(5):
            response = login_client.post(
                "/login",
                data={"email": "nobody@example.com", "password": "wrong"},
                environ_base={"REMOTE_ADDR": "198.51.100.41"},
            )
            self.assertEqual(response.status_code, 200)
        limited = login_client.post(
            "/login",
            data={"email": "nobody@example.com", "password": "wrong"},
            environ_base={"REMOTE_ADDR": "198.51.100.41"},
        )
        self.assertEqual(limited.status_code, 429)

        api_client = app.test_client()
        for _ in range(60):
            response = api_client.post(
                "/api/v1/predict",
                json={"text": "hello"},
                environ_base={"REMOTE_ADDR": "198.51.100.42"},
            )
            self.assertEqual(response.status_code, 401)
        limited = api_client.post(
            "/api/v1/predict",
            json={"text": "hello"},
            environ_base={"REMOTE_ADDR": "198.51.100.42"},
        )
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(
            limited.get_json(), {"success": False, "error": "Too many requests."}
        )

    def test_rest_api_is_csrf_exempt_but_still_requires_api_key(self):
        app.config["WTF_CSRF_TEST_ENABLED"] = True
        missing = self.client.post("/api/v1/predict", json={"text": "hello"})
        self.assertEqual(missing.status_code, 401)
        api_key = generate_api_key("Security test", self.admin_id)["full_key"]
        accepted = self.client.post(
            "/api/v1/predict",
            json={"text": "Hello, please send the report tomorrow."},
            headers={"X-API-Key": api_key},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(accepted.get_json()["success"])

    def test_upload_validation_limit_and_csv_formula_escape(self):
        self.login()
        before = Path(dataset_routes.DATASET_PATH).read_bytes()
        renamed_executable = self.client.post(
            "/dataset/import",
            data={"file": (io.BytesIO(b"MZ\x00\x01 executable"), "sample.csv")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(renamed_executable.status_code, 200)
        self.assertEqual(Path(dataset_routes.DATASET_PATH).read_bytes(), before)

        malformed = self.client.post(
            "/dataset/import",
            data={"file": (io.BytesIO(b"name,message\na,b\n"), "bad.csv")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn("label và text".encode(), malformed.data)

        oversized = self.client.post(
            "/dataset/import",
            data={"file": (
                io.BytesIO(b"x" * (app.config["MAX_CONTENT_LENGTH"] + 1)),
                "large.csv",
            )},
            content_type="multipart/form-data",
        )
        self.assertEqual(oversized.status_code, 413)

        batch = self.client.post(
            "/predict/batch",
            data={"file": (
                io.BytesIO(b"subject,text\n=cmd,+dangerous content\n"),
                "batch.csv",
            )},
            content_type="multipart/form-data",
        )
        match = re.search(rb"batch_result_[0-9a-f-]+\.csv", batch.data)
        self.assertIsNotNone(match)
        export_path = PROJECT_ROOT / "temp" / match.group().decode()
        try:
            exported = export_path.read_text(encoding="utf-8-sig")
            self.assertIn("'=cmd", exported)
            self.assertIn("'+dangerous content", exported)
        finally:
            export_path.unlink(missing_ok=True)

    def test_xss_is_escaped_and_security_headers_are_present(self):
        self.login("security-user@example.com")
        payload = "<script>alert(1)</script>"
        self.client.post("/predict", data={"subject": payload, "message": payload})
        history = self.client.get("/history")
        self.assertNotIn(payload.encode(), history.data)
        self.assertIn(b"&lt;script&gt;alert(1)&lt;/script&gt;", history.data)
        login_page = app.test_client().get("/login")
        self.assertEqual(login_page.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(login_page.headers["X-Frame-Options"], "DENY")
        self.assertIn("camera=()", login_page.headers["Permissions-Policy"])
        self.assertIn("default-src 'self'", login_page.headers["Content-Security-Policy"])
        self.assertIn("no-store", login_page.headers["Cache-Control"])
        self.assertNotIn("Strict-Transport-Security", login_page.headers)

    def test_secret_and_fernet_production_configuration(self):
        development = Flask("development-security-test")
        with patch.dict(os.environ, {"APP_ENV": "development", "FLASK_SECRET_KEY": ""}):
            load_security_config(development)
        self.assertFalse(development.config["SESSION_COOKIE_SECURE"])

        production = Flask("production-security-test")
        with patch.dict(os.environ, {"APP_ENV": "production", "FLASK_SECRET_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "FLASK_SECRET_KEY"):
                load_security_config(production)

        invalid_fernet = Flask("fernet-security-test")
        with patch.dict(os.environ, {"CREDENTIAL_ENCRYPTION_KEY": "invalid"}):
            with self.assertRaisesRegex(RuntimeError, "Fernet"):
                validate_credential_key(invalid_fernet)


if __name__ == "__main__":
    unittest.main()
