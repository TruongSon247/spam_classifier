import hashlib
import json
import os
import shutil
import unittest
import uuid
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import database.db as db
import services.backup_service as backup_service
from app import app


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BackupIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.root = PROJECT_ROOT / "temp" / f"backup_test_{os.getpid()}_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self.originals = {
            "db": db.DB_PATH,
            "backup": backup_service.BACKUP_DIR,
            "temp": backup_service.TEMP_DIR,
            "dataset": backup_service.DATASET_PATH,
            "model": backup_service.MODEL_DIR,
        }
        db.DB_PATH = str(self.root / "database" / "database.db")
        backup_service.BACKUP_DIR = self.root / "backups"
        backup_service.TEMP_DIR = self.root / "temp"
        backup_service.DATASET_PATH = self.root / "dataset" / "spam_dataset.csv"
        backup_service.MODEL_DIR = self.root / "model"
        Path(db.DB_PATH).parent.mkdir(parents=True)
        backup_service.DATASET_PATH.parent.mkdir(parents=True)
        backup_service.DATASET_PATH.write_text(
            'label,text\nspam,"Free prize now"\nham,"Meeting tomorrow"\n',
            encoding="utf-8",
        )
        backup_service.MODEL_DIR.mkdir(parents=True)
        for filename in backup_service.MODEL_FILENAMES:
            shutil.copy2(
                PROJECT_ROOT / "model" / filename,
                backup_service.MODEL_DIR / filename,
            )
        shutil.copytree(
            PROJECT_ROOT / "model" / "versions",
            backup_service.MODEL_DIR / "versions",
        )
        db.init_db()
        self.admin_id = db.create_user(
            "Backup Admin", "backup-admin@example.com", "Password123!", "admin"
        )
        self.user_id = db.create_user(
            "Backup User", "backup-user@example.com", "Password123!", "user"
        )
        app.config.update(TESTING=True, SECRET_KEY="backup-test-secret")
        self.client = app.test_client()

    def tearDown(self):
        db.DB_PATH = self.originals["db"]
        backup_service.BACKUP_DIR = self.originals["backup"]
        backup_service.TEMP_DIR = self.originals["temp"]
        backup_service.DATASET_PATH = self.originals["dataset"]
        backup_service.MODEL_DIR = self.originals["model"]
        shutil.rmtree(self.root, ignore_errors=True)

    def login(self, email="backup-admin@example.com"):
        return self.client.post(
            "/login", data={"email": email, "password": "Password123!"}
        )

    def rewrite_backup(self, source_name, target_name, changes=None, removed=None):
        changes = changes or {}
        removed = set(removed or ())
        source_path = backup_service.get_backup_path(source_name)
        target_path = backup_service.BACKUP_DIR / target_name
        with zipfile.ZipFile(source_path) as source:
            content = {
                info.filename: source.read(info.filename)
                for info in source.infolist()
                if not info.is_dir() and info.filename not in removed
            }
        content.update(changes)
        if "backup_manifest.json" in content:
            manifest = json.loads(content["backup_manifest.json"])
            for entry in manifest.get("files", []):
                if entry["path"] in changes:
                    data = changes[entry["path"]]
                    entry["size"] = len(data)
                    entry["sha256"] = hashlib.sha256(data).hexdigest()
            content["backup_manifest.json"] = json.dumps(manifest).encode()
        with zipfile.ZipFile(target_path, "w") as target:
            target.writestr("model/versions/", b"")
            for name, data in content.items():
                target.writestr(name, data)
        return target_path

    def test_create_archive_contents_manifest_and_no_secrets(self):
        result = backup_service.create_backup(self.admin_id, "Before update")
        path = backup_service.get_backup_path(result["filename"])
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            self.assertTrue(backup_service.REQUIRED_MEMBERS.issubset(names))
            self.assertIn("model/versions/", names)
            self.assertFalse(any(name.endswith(".env") for name in names))
            self.assertFalse(any("token" in name.lower() for name in names))
            manifest = json.loads(archive.read("backup_manifest.json"))
        self.assertEqual(manifest["dataset_samples"], 2)
        self.assertEqual(backup_service.validate_backup(path.name), manifest)
        with closing(db.get_connection()) as conn:
            row = conn.execute(
                "SELECT * FROM backups WHERE filename = ?", (path.name,)
            ).fetchone()
        self.assertEqual(row["status"], "ready")
        self.assertEqual(row["notes"], "Before update")

    def test_rejects_zip_slip_and_checksum_tampering(self):
        bad_path = backup_service.BACKUP_DIR / "backup_bad.zip"
        bad_path.parent.mkdir(parents=True)
        with zipfile.ZipFile(bad_path, "w") as archive:
            archive.writestr("../outside.txt", "bad")
        with self.assertRaises(backup_service.BackupError):
            backup_service.validate_backup(bad_path.name)
        self.assertFalse((self.root / "outside.txt").exists())

        valid = backup_service.create_backup(self.admin_id)
        valid_path = backup_service.get_backup_path(valid["filename"])
        tampered_path = backup_service.BACKUP_DIR / "backup_tampered.zip"
        with zipfile.ZipFile(valid_path) as source, zipfile.ZipFile(tampered_path, "w") as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename == "dataset/spam_dataset.csv":
                    data = b"label,text\nspam,Tampered\n"
                target.writestr(info, data)
        with self.assertRaisesRegex(backup_service.BackupError, "Checksum"):
            backup_service.validate_backup(tampered_path.name)

    def test_restore_recovers_data_and_creates_pre_restore(self):
        original_dataset_hash = file_hash(backup_service.DATASET_PATH)
        original_model_hash = file_hash(backup_service.MODEL_DIR / "model.pkl")
        created = backup_service.create_backup(self.admin_id)
        db.create_user("Later User", "later@example.com", "Password123!", "user")
        backup_service.DATASET_PATH.write_text(
            "label,text\nspam,Changed\n", encoding="utf-8"
        )
        (backup_service.MODEL_DIR / "model.pkl").write_bytes(b"corrupt-current-model")

        result = backup_service.restore_backup(created["filename"], self.admin_id)
        self.assertTrue(result["pre_restore"]["filename"].startswith("pre_restore_"))
        self.assertTrue(backup_service.get_backup_path(result["pre_restore"]["filename"]).is_file())
        self.assertEqual(file_hash(backup_service.DATASET_PATH), original_dataset_hash)
        self.assertEqual(file_hash(backup_service.MODEL_DIR / "model.pkl"), original_model_hash)
        self.assertIsNone(db.get_user_by_email("later@example.com"))
        self.assertIsNotNone(db.get_user_by_email("backup-admin@example.com"))
        with closing(db.get_connection()) as conn:
            statuses = {
                row["filename"]: row["status"]
                for row in conn.execute("SELECT filename, status FROM backups")
            }
        self.assertEqual(statuses[created["filename"]], "restored")
        self.assertEqual(statuses[result["pre_restore"]["filename"]], "ready")

    def test_rejects_missing_model_bad_database_csv_and_model(self):
        created = backup_service.create_backup(self.admin_id)
        self.rewrite_backup(
            created["filename"],
            "backup_missing_model.zip",
            removed={"model/model.pkl"},
        )
        with self.assertRaisesRegex(backup_service.BackupError, "thiếu file"):
            backup_service.validate_backup("backup_missing_model.zip")

        self.rewrite_backup(
            created["filename"],
            "backup_bad_database.zip",
            {"database/database.db": b"not-a-sqlite-database"},
        )
        with self.assertRaisesRegex(backup_service.BackupError, "Database"):
            backup_service.validate_backup("backup_bad_database.zip")

        bad_csv = b"label,text\nunknown,Invalid label\n"
        csv_path = self.rewrite_backup(
            created["filename"],
            "backup_bad_csv.zip",
            {"dataset/spam_dataset.csv": bad_csv},
        )
        with zipfile.ZipFile(csv_path, "a") as archive:
            manifest = json.loads(archive.read("backup_manifest.json"))
        with self.assertRaisesRegex(backup_service.BackupError, "label"):
            backup_service.validate_backup("backup_bad_csv.zip")

        self.rewrite_backup(
            created["filename"],
            "backup_bad_model.zip",
            {"model/model.pkl": b"not-a-joblib-model"},
        )
        with self.assertRaisesRegex(backup_service.BackupError, "mô hình"):
            backup_service.validate_backup("backup_bad_model.zip")

    def test_restore_aborts_when_pre_restore_backup_fails(self):
        created = backup_service.create_backup(self.admin_id)
        dataset_hash = file_hash(backup_service.DATASET_PATH)
        real_create = backup_service.create_backup

        def fail_pre_restore(*args, **kwargs):
            if kwargs.get("prefix") == "pre_restore":
                raise backup_service.BackupError("pre-restore failed")
            return real_create(*args, **kwargs)

        with patch.object(backup_service, "create_backup", side_effect=fail_pre_restore):
            with self.assertRaisesRegex(backup_service.BackupError, "pre-restore"):
                backup_service.restore_backup(created["filename"], self.admin_id)
        self.assertEqual(file_hash(backup_service.DATASET_PATH), dataset_hash)

    def test_admin_routes_download_delete_and_access_control(self):
        self.login("backup-user@example.com")
        self.assertEqual(self.client.get("/admin/backups").status_code, 302)
        self.client.post("/logout")
        self.login()
        page = self.client.get("/admin/backups")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Sao lưu &amp; Khôi phục".encode(), page.data)
        response = self.client.post(
            "/admin/backups/create", data={"notes": "Route test"}
        )
        self.assertEqual(response.status_code, 302)
        item = backup_service.list_backups()[0]
        download = self.client.get(
            f"/admin/backups/{item['filename']}/download"
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.mimetype, "application/zip")
        download.close()
        rejected = self.client.post(
            f"/admin/backups/{item['filename']}/restore",
            data={"confirmation": "wrong"},
        )
        self.assertEqual(rejected.status_code, 302)
        deleted = self.client.post(
            f"/admin/backups/{item['filename']}/delete"
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertFalse((backup_service.BACKUP_DIR / item["filename"]).exists())


if __name__ == "__main__":
    unittest.main()
