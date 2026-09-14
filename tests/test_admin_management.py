import os
import unittest
from contextlib import closing

import database.db as db
from app import app


class UserAdministrationTest(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db.DB_PATH
        self.db_path = os.path.join(os.path.dirname(__file__), "test_admin_management.db")
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        db.DB_PATH = self.db_path
        db.init_db()
        self.admin_id = db.create_user(
            "Admin", "admin-manage@example.com", "Admin123!", "admin"
        )
        self.user_id = db.create_user(
            "Original User", "original@example.com", "Password123!", "user"
        )
        self.other_id = db.create_user(
            "Other User", "other@example.com", "Password123!", "user"
        )
        app.config.update(TESTING=True, SECRET_KEY="admin-management-test")
        self.client = app.test_client()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def login(self, email, password):
        return self.client.post(
            "/login", data={"email": email, "password": password},
            follow_redirects=True,
        )

    def test_admin_edits_user_and_duplicate_email_is_rejected(self):
        self.login("admin-manage@example.com", "Admin123!")
        response = self.client.post(
            f"/users/{self.user_id}/edit",
            data={"name": "  Updated User  ", "email": " UPDATED@EXAMPLE.COM ", "role": "user"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        updated = db.get_user_by_id(self.user_id)
        self.assertEqual(updated["name"], "Updated User")
        self.assertEqual(updated["email"], "updated@example.com")

        duplicate = self.client.post(
            f"/users/{self.user_id}/edit",
            data={"name": "Duplicate", "email": "other@example.com", "role": "user"},
            follow_redirects=True,
        )
        self.assertIn("đã tồn tại".encode(), duplicate.data)
        self.assertEqual(db.get_user_by_id(self.user_id)["email"], "updated@example.com")
        invalid = self.client.post(
            f"/users/{self.user_id}/edit",
            data={"name": "Invalid", "email": "not-an-email", "role": "admin"},
            follow_redirects=True,
        )
        self.assertIn("Email không hợp lệ".encode(), invalid.data)
        self.assertEqual(db.get_user_by_id(self.user_id)["role"], "user")
        with closing(db.get_connection()) as conn:
            audit = conn.execute(
                "SELECT * FROM audit_logs WHERE action = 'USER_UPDATE'"
            ).fetchone()
        self.assertIsNotNone(audit)

    def test_password_reset_replaces_old_password_without_logging_it(self):
        new_password = "NewPassword456!"
        self.login("admin-manage@example.com", "Admin123!")
        mismatch = self.client.post(
            f"/users/{self.user_id}/reset-password",
            data={"password": "Mismatch123!", "password_confirmation": "Different123!"},
            follow_redirects=True,
        )
        self.assertIn("xác nhận không khớp".encode(), mismatch.data)
        response = self.client.post(
            f"/users/{self.user_id}/reset-password",
            data={"password": new_password, "password_confirmation": new_password},
            follow_redirects=True,
        )
        self.assertIn("Đã đặt lại mật khẩu".encode(), response.data)
        self.client.post("/logout")
        old_login = self.login("original@example.com", "Password123!")
        self.assertEqual(old_login.request.path, "/login")
        new_login = self.login("original@example.com", new_password)
        self.assertNotEqual(new_login.request.path, "/login")
        with closing(db.get_connection()) as conn:
            audit = conn.execute(
                "SELECT description FROM audit_logs WHERE action = 'USER_PASSWORD_RESET'"
            ).fetchone()
        self.assertNotIn(new_password, audit["description"])

    def test_last_admin_cannot_demote_or_disable_self(self):
        self.login("admin-manage@example.com", "Admin123!")
        self.client.post(
            f"/users/{self.admin_id}/edit",
            data={"name": "Admin", "email": "admin-manage@example.com", "role": "user"},
        )
        self.client.post(f"/users/{self.admin_id}/toggle-active")
        admin = db.get_user_by_id(self.admin_id)
        self.assertEqual(admin["role"], "admin")
        self.assertEqual(admin["is_active"], 1)
        self.assertEqual(db.count_active_admins(), 1)

    def test_regular_user_cannot_edit_or_reset_another_user(self):
        self.login("original@example.com", "Password123!")
        edit = self.client.post(
            f"/users/{self.other_id}/edit",
            data={"name": "Hacked", "email": "hacked@example.com", "role": "admin"},
            follow_redirects=False,
        )
        reset = self.client.post(
            f"/users/{self.other_id}/reset-password",
            data={"password": "Changed123!", "password_confirmation": "Changed123!"},
            follow_redirects=False,
        )
        self.assertEqual(edit.status_code, 302)
        self.assertEqual(reset.status_code, 302)
        self.assertEqual(db.get_user_by_id(self.other_id)["name"], "Other User")


if __name__ == "__main__":
    unittest.main()
