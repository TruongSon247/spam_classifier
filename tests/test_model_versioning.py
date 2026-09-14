import hashlib
import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import database.db as db
import services.application_service as application_service
import services.model_registry_service as registry
from app import app


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        digest.update(stream.read())
    return digest.hexdigest()


class ModelVersioningTest(unittest.TestCase):
    def setUp(self):
        self.root = (
            PROJECT_ROOT / "temp" / f"model_versions_test_{os.getpid()}_{uuid.uuid4().hex}"
        )
        self.root.mkdir(parents=True)
        self.original_db_path = db.DB_PATH
        self.original_model_dir = registry.MODEL_DIR
        self.original_versions_dir = registry.VERSIONS_DIR
        self.original_dataset_path = registry.DATASET_PATH

        db.DB_PATH = str(self.root / "database.db")
        registry.MODEL_DIR = self.root / "model"
        registry.VERSIONS_DIR = registry.MODEL_DIR / "versions"
        registry.DATASET_PATH = PROJECT_ROOT / "dataset" / "spam_dataset.csv"
        registry.MODEL_DIR.mkdir(parents=True)
        for filename in registry.ACTIVE_FILENAMES:
            shutil.copy2(PROJECT_ROOT / "model" / filename, registry.MODEL_DIR / filename)

        db.init_db()
        self.admin_id = db.create_user(
            "Admin Test", "admin-version@example.com", "Password123!", "admin"
        )
        self.user_id = db.create_user(
            "User Test", "user-version@example.com", "Password123!", "user"
        )
        app.config.update(TESTING=True, SECRET_KEY="model-version-test")
        self.client = app.test_client()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        registry.MODEL_DIR = self.original_model_dir
        registry.VERSIONS_DIR = self.original_versions_dir
        registry.DATASET_PATH = self.original_dataset_path
        shutil.rmtree(self.root, ignore_errors=True)

    def login(self, email):
        return self.client.post(
            "/login",
            data={"email": email, "password": "Password123!"},
            follow_redirects=True,
        )

    def test_migrate_train_rollback_and_reject_corrupt_version(self):
        original_model_hash = file_hash(registry.MODEL_DIR / "model.pkl")
        original_vectorizer_hash = file_hash(registry.MODEL_DIR / "vectorizer.pkl")

        first = registry.initialize_model_registry()
        self.assertEqual(first["version"], "v0001")
        self.assertTrue(first["is_active"])
        self.assertEqual(len(registry.get_model_versions()), 1)
        registry.initialize_model_registry()
        self.assertEqual(len(registry.get_model_versions()), 1)
        self.assertEqual(
            file_hash(registry.VERSIONS_DIR / "v0001" / "model.pkl"),
            original_model_hash,
        )
        self.assertEqual(
            file_hash(registry.VERSIONS_DIR / "v0001" / "vectorizer.pkl"),
            original_vectorizer_hash,
        )

        trained = registry.train_and_register_model(
            self.admin_id, "Automated version test"
        )
        self.assertEqual(trained["version"], "v0002")
        versions = registry.get_model_versions()
        self.assertEqual(len(versions), 2)
        self.assertEqual(registry.get_active_model_version()["version"], "v0002")
        self.assertEqual(
            file_hash(registry.MODEL_DIR / "model.pkl"),
            file_hash(registry.VERSIONS_DIR / "v0002" / "model.pkl"),
        )

        v1 = next(row for row in versions if row["version"] == "v0001")
        registry.rollback_model(v1["id"], self.admin_id)
        self.assertEqual(registry.get_active_model_version()["version"], "v0001")
        self.assertEqual(file_hash(registry.MODEL_DIR / "model.pkl"), original_model_hash)

        v2 = next(row for row in versions if row["version"] == "v0002")
        with open(registry.VERSIONS_DIR / "v0002" / "model.pkl", "wb") as stream:
            stream.write(b"corrupt")
        active_hash = file_hash(registry.MODEL_DIR / "model.pkl")
        with self.assertRaises(ValueError):
            registry.activate_model_version(v2["id"], self.admin_id)
        self.assertEqual(registry.get_active_model_version()["version"], "v0001")
        self.assertEqual(file_hash(registry.MODEL_DIR / "model.pkl"), active_hash)

    def test_model_routes_are_admin_only(self):
        registry.initialize_model_registry()
        self.login("user-version@example.com")
        response = self.client.get("/models", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")
        self.client.post("/logout")

        self.login("admin-version@example.com")
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"v0001", response.data)

    def test_dataset_hash_change_marks_model_outdated(self):
        active = {"version": "v0001", "dataset_hash": "trained-dataset-hash"}
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "os.path.getmtime",
                side_effect=lambda path: 100 if str(path).startswith("model/") else 50,
            ),
            patch.object(registry, "get_active_model_version", return_value=active),
            patch.object(registry, "calculate_dataset_hash", return_value="new-hash"),
        ):
            status = application_service.get_model_status("dataset/test.csv")
        self.assertTrue(status["trained"])
        self.assertTrue(status["outdated"])
        self.assertEqual(status["version"], "v0001")


if __name__ == "__main__":
    unittest.main()
