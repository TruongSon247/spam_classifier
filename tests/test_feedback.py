import csv
import os
import unittest
from contextlib import closing

import app as app_module
import database.db as db
from services.encryption_service import encrypt_value


class FeedbackIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db.DB_PATH
        self.original_dataset_path = app_module.FEEDBACK_DATASET_PATH
        db.DB_PATH = os.path.join(os.path.dirname(__file__), "test_feedback.db")
        self.dataset_path = os.path.join(
            os.path.dirname(__file__), "test_feedback_dataset.csv"
        )
        for path in (db.DB_PATH, self.dataset_path):
            if os.path.exists(path):
                os.remove(path)
        with open(self.dataset_path, "w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["label", "text"])
            writer.writerow(["ham", "Existing meeting message"])

        app_module.FEEDBACK_DATASET_PATH = self.dataset_path
        db.init_db()
        self.admin_id = db.create_user(
            "Admin", "feedback-admin@example.com", "Admin123!", "admin"
        )
        self.user_a = db.create_user(
            "User A", "feedback-a@example.com", "Password123!", "user"
        )
        self.user_b = db.create_user(
            "User B", "feedback-b@example.com", "Password123!", "user"
        )
        self.account_a = db.create_email_account(
            self.user_a, "imap", "a@example.com", encrypt_value("secret")
        )
        self.account_b = db.create_email_account(
            self.user_b, "imap", "b@example.com", encrypt_value("secret")
        )
        self.spam_message = self.save_message(
            self.user_a, self.account_a, "spam-1", "Free prize", "spam"
        )
        self.ham_message = self.save_message(
            self.user_a, self.account_a, "ham-1", "Team meeting", "ham"
        )
        self.foreign_message = self.save_message(
            self.user_b, self.account_b, "foreign-1", "Private B", "spam"
        )
        app_module.app.config.update(TESTING=True, SECRET_KEY="feedback-test")
        self.client = app_module.app.test_client()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        app_module.FEEDBACK_DATASET_PATH = self.original_dataset_path
        for path in (
            os.path.join(os.path.dirname(__file__), "test_feedback.db"),
            self.dataset_path,
        ):
            if os.path.exists(path):
                os.remove(path)

    def save_message(self, user_id, account_id, provider_id, subject, prediction):
        db.save_mail_message({
            "user_id": user_id,
            "account_id": account_id,
            "provider_message_id": provider_id,
            "subject": subject,
            "sender_name": "Sender",
            "sender_email": "sender@example.com",
            "snippet": "Preview",
            "body_text": f"Training body for {subject}",
            "received_at": "2026-09-13T10:00:00+07:00",
            "prediction": prediction,
            "spam_probability": 0.92 if prediction == "spam" else 0.08,
            "ham_probability": 0.08 if prediction == "spam" else 0.92,
            "confidence": 0.92,
            "is_read": 0,
        })
        with closing(db.get_connection()) as conn:
            return conn.execute(
                "SELECT id FROM mail_messages WHERE account_id = ? "
                "AND provider_message_id = ?",
                (account_id, provider_id),
            ).fetchone()["id"]

    def login(self, email, password="Password123!"):
        return self.client.post(
            "/login", data={"email": email, "password": password}
        )

    def logout(self):
        return self.client.post("/logout")

    def test_quarantine_feedback_privacy_and_original_prediction(self):
        self.login("feedback-a@example.com")
        quarantine = self.client.get("/quarantine")
        self.assertIn(b"Free prize", quarantine.data)
        self.assertNotIn(b"Team meeting", quarantine.data)
        self.assertNotIn(b"Private B", quarantine.data)

        response = self.client.post(
            f"/mail/message/{self.spam_message}/feedback",
            data={"label": "ham"},
            follow_redirects=True,
        )
        self.assertIn("Đã ghi nhận phản hồi".encode(), response.data)
        message = db.get_mail_message_for_user(self.spam_message, self.user_a)
        self.assertEqual(message["prediction"], "spam")
        self.assertEqual(message["user_label"], "ham")
        self.assertEqual(message["is_quarantined"], 0)
        self.assertNotIn(b"Free prize", self.client.get("/quarantine").data)
        self.assertIn(b"Free prize", self.client.get("/mail").data)

        self.client.post(
            f"/mail/message/{self.ham_message}/feedback",
            data={"label": "spam", "allow_training": "1"},
        )
        marked = db.get_mail_message_for_user(self.ham_message, self.user_a)
        self.assertEqual(marked["prediction"], "ham")
        self.assertEqual(marked["user_label"], "spam")
        self.assertEqual(marked["is_quarantined"], 1)
        self.assertIn(b"Team meeting", self.client.get("/quarantine").data)

        foreign = self.client.post(
            f"/mail/message/{self.foreign_message}/feedback",
            data={"label": "ham"},
        )
        self.assertEqual(foreign.status_code, 403)
        self.assertIsNone(
            db.get_feedback_by_message(self.user_a, self.foreign_message)
        )

    def test_training_consent_approval_duplicate_and_rejection(self):
        self.login("feedback-a@example.com")
        self.client.post(
            f"/mail/message/{self.spam_message}/feedback",
            data={"label": "ham"},
        )
        self.logout()
        self.login("feedback-admin@example.com", "Admin123!")
        self.assertNotIn(b"Free prize", self.client.get("/admin/feedback").data)

        self.logout()
        self.login("feedback-a@example.com")
        self.client.post(
            f"/mail/message/{self.spam_message}/feedback",
            data={"label": "ham", "allow_training": "1"},
        )
        self.client.post(
            f"/mail/message/{self.ham_message}/feedback",
            data={"label": "spam", "allow_training": "1"},
        )
        self.logout()
        self.login("feedback-admin@example.com", "Admin123!")

        review = self.client.get("/admin/feedback")
        self.assertIn(b"Free prize", review.data)
        spam_feedback = db.get_feedback_by_message(self.user_a, self.spam_message)
        ham_feedback = db.get_feedback_by_message(self.user_a, self.ham_message)

        before = self.read_dataset()
        approved = self.client.post(
            f"/admin/feedback/{spam_feedback['id']}/approve",
            follow_redirects=True,
        )
        self.assertIn("Đã duyệt".encode(), approved.data)
        after = self.read_dataset()
        self.assertEqual(len(after), len(before) + 1)
        self.assertEqual(after[-1]["label"], "ham")
        self.assertTrue(app_module.get_model_status()["outdated"])
        self.assertEqual(
            db.get_feedback_by_message(self.user_a, self.spam_message)["status"],
            "approved",
        )

        second = self.client.post(
            f"/admin/feedback/{spam_feedback['id']}/approve"
        )
        self.assertEqual(second.status_code, 404)
        self.assertEqual(len(self.read_dataset()), len(after))

        before_reject = self.read_dataset()
        self.client.post(f"/admin/feedback/{ham_feedback['id']}/reject")
        self.assertEqual(len(self.read_dataset()), len(before_reject))
        self.assertEqual(
            db.get_feedback_by_message(self.user_a, self.ham_message)["status"],
            "rejected",
        )

    def test_safe_migration_preserves_existing_rows(self):
        with closing(db.get_connection()) as conn:
            counts_before = tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("users", "email_accounts", "mail_messages")
            )
        db.init_db()
        with closing(db.get_connection()) as conn:
            counts_after = tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("users", "email_accounts", "mail_messages")
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(mail_messages)")
            }
        self.assertEqual(counts_before, counts_after)
        self.assertTrue({"is_quarantined", "user_label", "feedback_at"} <= columns)

    def read_dataset(self):
        with open(self.dataset_path, encoding="utf-8", newline="") as file:
            return list(csv.DictReader(file))


if __name__ == "__main__":
    unittest.main()
