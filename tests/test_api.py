import os
import re
import unittest
from contextlib import closing
from unittest.mock import patch

import database.db as db
from app import app
from ml.predict import predict_email
from services.api_key_service import generate_api_key


class RestApiIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(os.path.dirname(__file__), "test_api.db")
        if os.path.exists(db.DB_PATH):
            os.remove(db.DB_PATH)
        db.init_db()
        self.admin_id = db.create_user(
            "API Admin", "api-admin@example.com", "Password123!", "admin"
        )
        self.user_id = db.create_user(
            "API User", "api-user@example.com", "Password123!", "user"
        )
        db.create_model_version({
            "version": "v0002",
            "model_name": "Multinomial Naive Bayes",
            "vectorizer": "TF-IDF",
            "model_path": "model/versions/v0002/model.pkl",
            "vectorizer_path": "model/versions/v0002/vectorizer.pkl",
            "info_path": "model/versions/v0002/model_info.json",
            "dataset_hash": "test-dataset-hash",
        }, is_active=True)
        self.key = generate_api_key("Test Client", self.admin_id)
        self.headers = {"X-API-Key": self.key["full_key"]}
        app.config.update(TESTING=True, SECRET_KEY="api-test-secret")
        self.client = app.test_client()

    def tearDown(self):
        if os.path.exists(db.DB_PATH):
            os.remove(db.DB_PATH)
        db.DB_PATH = self.original_db_path

    def login(self, email):
        return self.client.post(
            "/login",
            data={"email": email, "password": "Password123!"},
            follow_redirects=True,
        )

    def post_prediction(self, payload, headers=None):
        return self.client.post(
            "/api/v1/predict",
            json=payload,
            headers=self.headers if headers is None else headers,
        )

    def test_health_authentication_and_validation(self):
        health = self.client.get("/api/v1/health")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json["success"])
        self.assertEqual(health.json["service"], "Naive Bayes Spam Classifier")

        missing = self.post_prediction({"text": "hello"}, headers={})
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json["error"], "API key is required.")
        invalid = self.post_prediction(
            {"text": "hello"}, headers={"X-API-Key": "spam_invalid"}
        )
        self.assertEqual(invalid.status_code, 401)

        db.set_api_key_active(self.key["id"], False)
        disabled = self.post_prediction({"text": "hello"})
        self.assertEqual(disabled.status_code, 403)
        db.set_api_key_active(self.key["id"], True)

        non_json = self.client.post(
            "/api/v1/predict", data="text=hello", headers=self.headers
        )
        self.assertEqual(non_json.status_code, 415)
        malformed = self.client.post(
            "/api/v1/predict",
            data="{bad-json",
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(malformed.status_code, 400)
        for payload in ({}, {"text": ""}, {"text": "   "}):
            self.assertEqual(self.post_prediction(payload).status_code, 400)
        self.assertEqual(self.post_prediction({"text": 123}).status_code, 400)
        self.assertEqual(
            self.post_prediction({"text": "x" * 50001}).status_code, 413
        )
        self.assertEqual(
            self.post_prediction({"text": "hello", "subject": "x" * 1001}).status_code,
            413,
        )

    def test_predictions_match_direct_model_and_log_no_email_text(self):
        samples = (
            "Congratulations! You won a free prize",
            "Hello, please send me the report before tomorrow.",
            "CHÚC MỪNG! Bạn đã trúng thưởng tiền mặt",
            "Chào bạn, vui lòng gửi báo cáo trước ngày mai",
        )
        for text in samples:
            with self.subTest(text=text):
                direct = predict_email(text)
                response = self.post_prediction({"subject": "Ignored", "text": text})
                self.assertEqual(response.status_code, 200)
                body = response.json
                self.assertEqual(body["prediction"], direct["prediction"])
                self.assertEqual(body["spam_probability"], direct["spam_probability"])
                self.assertEqual(body["ham_probability"], direct["ham_probability"])
                self.assertEqual(body["confidence"], direct["confidence"])
                self.assertEqual(body["model_version"], "v0002")

        with closing(db.get_connection()) as conn:
            logs = conn.execute("SELECT * FROM api_prediction_logs").fetchall()
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(api_prediction_logs)")
            }
            predictions = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        self.assertEqual(len(logs), len(samples))
        self.assertNotIn("text", columns)
        self.assertNotIn("subject", columns)
        self.assertEqual(predictions, 0)

    def test_model_unavailable_returns_503(self):
        with patch(
            "routes.api_routes.get_model_status",
            return_value={"trained": False, "outdated": True},
        ):
            response = self.post_prediction({"text": "hello"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["error"], "Model is not available.")

    def test_admin_key_management_shows_secret_once_and_never_stores_plaintext(self):
        self.login("api-user@example.com")
        denied = self.client.get("/admin/api-keys", follow_redirects=False)
        self.assertEqual(denied.status_code, 302)
        self.assertEqual(denied.headers["Location"], "/")
        self.client.post("/logout")

        self.login("api-admin@example.com")
        response = self.client.post(
            "/admin/api-keys/create", data={"name": "Website Demo"}
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        match = re.search(r'id="newApiKey"[^>]+value="([^"]+)"', html)
        self.assertIsNotNone(match)
        full_key = match.group(1)
        self.assertTrue(full_key.startswith("spam_"))

        refreshed = self.client.get("/admin/api-keys").get_data(as_text=True)
        self.assertNotIn(full_key, refreshed)
        self.assertIn(
            "API Key này sẽ không thể tiếp tục gọi REST API. Bạn có chắc chắn?",
            refreshed,
        )
        with closing(db.get_connection()) as conn:
            saved = conn.execute(
                "SELECT * FROM api_keys WHERE name = ?", ("Website Demo",)
            ).fetchone()
        self.assertIsNotNone(saved)
        self.assertNotEqual(saved["key_hash"], full_key)
        with open(db.DB_PATH, "rb") as database_file:
            self.assertNotIn(full_key.encode("utf-8"), database_file.read())

        self.client.post(f"/admin/api-keys/{saved['id']}/toggle")
        self.assertFalse(db.get_api_key(saved["id"])["is_active"])
        disabled = self.client.post(
            "/api/v1/predict",
            json={"text": "Meeting tomorrow"},
            headers={"X-API-Key": full_key},
        )
        self.assertEqual(disabled.status_code, 403)
        self.assertIsNotNone(db.get_api_key(saved["id"]))
        self.client.post(f"/admin/api-keys/{saved['id']}/toggle")
        self.assertTrue(db.get_api_key(saved["id"])["is_active"])
        enabled = self.client.post(
            "/api/v1/predict",
            json={"text": "Meeting tomorrow"},
            headers={"X-API-Key": full_key},
        )
        self.assertEqual(enabled.status_code, 200)
        docs = self.client.get("/api-docs")
        self.assertEqual(docs.status_code, 200)
        self.assertIn(b"X-API-Key", docs.data)


if __name__ == "__main__":
    unittest.main()
