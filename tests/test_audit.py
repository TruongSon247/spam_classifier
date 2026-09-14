import io
import os
import re
import unittest
from contextlib import closing

import database.db as db
from app import app
from routes import dataset_routes
from services.audit_service import (
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    configure_application_logging,
    log_audit,
)


class AuditIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db.DB_PATH
        self.original_dataset_path = dataset_routes.DATASET_PATH
        self.db_path = os.path.join(os.path.dirname(__file__), "test_audit.db")
        self.dataset_path = os.path.join(os.path.dirname(__file__), "test_audit_dataset.csv")
        for path in (self.db_path, self.dataset_path):
            if os.path.exists(path):
                os.remove(path)
        db.DB_PATH = self.db_path
        dataset_routes.DATASET_PATH = self.dataset_path
        with open(self.dataset_path, "w", encoding="utf-8") as stream:
            stream.write("label,text\nham,Existing sample\n")
        db.init_db()
        self.admin_id = db.create_user(
            "Audit Admin", "audit-admin@example.com", "Admin123!", "admin"
        )
        self.user_id = db.create_user(
            "Audit User", "audit-user@example.com", "Password123!", "user"
        )
        app.config.update(TESTING=True, SECRET_KEY="audit-test-secret")
        self.client = app.test_client()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        dataset_routes.DATASET_PATH = self.original_dataset_path
        for path in (self.db_path, self.dataset_path):
            if os.path.exists(path):
                os.remove(path)

    def login(self, email, password):
        return self.client.post(
            "/login", data={"email": email, "password": password}
        )

    def actions(self):
        with closing(db.get_connection()) as conn:
            return conn.execute(
                "SELECT * FROM audit_logs ORDER BY id ASC"
            ).fetchall()

    def test_login_logout_and_admin_access(self):
        self.login("audit-user@example.com", "wrong-password")
        self.login("audit-user@example.com", "Password123!")
        denied = self.client.get("/admin/audit-logs", follow_redirects=False)
        self.assertEqual(denied.status_code, 302)
        self.client.post("/logout")

        actions = self.actions()
        self.assertEqual(
            [row["action"] for row in actions],
            ["LOGIN_FAILED", "LOGIN_SUCCESS", "LOGOUT"],
        )
        self.assertEqual(actions[0]["status"], "failed")
        self.assertEqual(actions[1]["user_id"], self.user_id)
        self.assertEqual(actions[1]["ip_address"], "127.0.0.1")

        self.login("audit-admin@example.com", "Admin123!")
        page = self.client.get("/admin/audit-logs?category=auth&status=success")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Nhật ký hệ thống".encode(), page.data)
        self.assertIn(b"LOGIN_SUCCESS", page.data)
        self.assertNotIn(b"LOGIN_FAILED", page.data)

    def test_dataset_import_filter_and_pagination(self):
        self.login("audit-admin@example.com", "Admin123!")
        response = self.client.post(
            "/dataset/import",
            data={"file": (io.BytesIO(b"label,text\nspam,Free prize\nham,Team meeting\n"), "samples.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        for index in range(25):
            log_audit(
                "TEST_EVENT", "system", user_id=self.admin_id,
                target_type="test", target_id=index,
                description=f"Pagination event {index}.",
            )
        rows, total = db.get_audit_logs("dataset", "success")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["action"], "DATASET_IMPORT")
        self.assertIn("2 valid samples", rows[0]["description"])
        page = self.client.get("/admin/audit-logs?category=system&page=2")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Trang 2 / 2", page.data)

    def test_api_key_audit_never_contains_full_key(self):
        self.login("audit-admin@example.com", "Admin123!")
        response = self.client.post(
            "/admin/api-keys/create", data={"name": "Audit client"}
        )
        self.assertEqual(response.status_code, 200)
        full_key = re.search(rb'value="(spam_[^"]+)"', response.data).group(1).decode()
        with closing(db.get_connection()) as conn:
            key = conn.execute("SELECT * FROM api_keys").fetchone()
            audit = conn.execute(
                "SELECT * FROM audit_logs WHERE action = 'API_KEY_CREATE'"
            ).fetchone()
        self.assertIsNotNone(audit)
        self.assertIn(key["key_prefix"], audit["description"])
        self.assertNotIn(key["key_hash"], audit["description"])
        self.assertNotIn(full_key, audit["description"])

    def test_file_logging_is_rotating_and_contains_no_secret_sentinel(self):
        configure_application_logging(app)
        handlers = [
            handler for handler in app.logger.handlers
            if hasattr(handler, "maxBytes") and handler.maxBytes == LOG_MAX_BYTES
        ]
        self.assertTrue(handlers)
        self.assertEqual(handlers[0].backupCount, LOG_BACKUP_COUNT)
        app.logger.info("Audit logging test event")
        handlers[0].flush()
        with open(handlers[0].baseFilename, encoding="utf-8") as stream:
            log_content = stream.read()
        self.assertIn("Audit logging test event", log_content)
        self.assertNotIn("step47-secret-sentinel", log_content)


if __name__ == "__main__":
    unittest.main()
