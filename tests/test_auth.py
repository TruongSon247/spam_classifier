import os
import unittest
from contextlib import closing

import database.db as db
from app import app


class AuthenticationIntegrationTest(unittest.TestCase):
    def setUp(self):
        db.DB_PATH = os.path.join(os.path.dirname(__file__), "test_auth.db")
        if os.path.exists(db.DB_PATH):
            os.remove(db.DB_PATH)
        db.init_db()
        self.admin_id = db.create_user(
            "Admin Test", "admin@example.com", "Admin123!", "admin"
        )
        self.user_a_id = db.create_user(
            "User A", "usera@example.com", "Password123!", "user"
        )
        self.user_b_id = db.create_user(
            "User B", "userb@example.com", "Password123!", "user"
        )
        self.disabled_id = db.create_user(
            "Disabled", "disabled@example.com", "Password123!", "user"
        )
        db.set_user_active(self.disabled_id, False)
        app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = app.test_client()

    def tearDown(self):
        if os.path.exists(db.DB_PATH):
            os.remove(db.DB_PATH)

    def login(self, email, password="Password123!"):
        return self.client.post(
            "/login",
            data={"email": email, "password": password},
            follow_redirects=True,
        )

    def logout(self):
        return self.client.post("/logout", follow_redirects=True)

    def test_auth_roles_and_scoped_history(self):
        for path in ("/", "/predict", "/history", "/algorithm"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/login", response.headers["Location"])

        response = self.login("usera@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Quản lý người dùng".encode(), response.data)
        self.assertNotIn("Quản lý Dataset".encode(), response.data)

        for admin_path in ("/dataset", "/train", "/evaluate", "/compare", "/users"):
            response = self.client.get(admin_path, follow_redirects=False)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers["Location"], "/")

        result = self.client.post(
            "/predict",
            data={"subject": "Test A", "message": "Meeting tomorrow morning"},
        )
        self.assertEqual(result.status_code, 200)
        with closing(db.get_connection()) as conn:
            saved = conn.execute(
                "SELECT * FROM predictions WHERE subject = ?", ("Test A",)
            ).fetchone()
        self.assertIsNotNone(saved)
        self.assertEqual(saved["user_id"], self.user_a_id)

        db.save_prediction("Only B", "hello", "ham", 0.1, 0.9, self.user_b_id)
        history_a = self.client.get("/history")
        self.assertIn(b"Test A", history_a.data)
        self.assertNotIn(b"Only B", history_a.data)
        self.logout()

        self.login("userb@example.com")
        history_b = self.client.get("/history")
        self.assertIn(b"Only B", history_b.data)
        self.assertNotIn(b"Test A", history_b.data)
        self.logout()

        admin = self.client.post(
            "/login",
            data={"email": "admin@example.com", "password": "Admin123!"},
            follow_redirects=True,
        )
        self.assertEqual(admin.status_code, 200)
        self.assertIn("Quản lý người dùng".encode(), admin.data)
        for path in (
            "/",
            "/predict",
            "/predict/batch",
            "/dataset",
            "/train",
            "/evaluate",
            "/compare",
            "/history",
            "/algorithm",
            "/users",
        ):
            self.assertEqual(self.client.get(path).status_code, 200, path)

        self.client.post(f"/users/{self.admin_id}/toggle-active")
        self.client.post(
            f"/users/{self.admin_id}/role",
            data={"role": "user"},
        )
        protected_admin = db.get_user_by_id(self.admin_id)
        self.assertEqual(protected_admin["is_active"], 1)
        self.assertEqual(protected_admin["role"], "admin")
        admin_history = self.client.get("/history")
        self.assertIn(b"Test A", admin_history.data)
        self.assertIn(b"Only B", admin_history.data)
        self.logout()

        disabled = self.login("disabled@example.com")
        self.assertIn("vô hiệu hóa".encode(), disabled.data)
        self.assertEqual(disabled.request.path, "/login")


if __name__ == "__main__":
    unittest.main()
