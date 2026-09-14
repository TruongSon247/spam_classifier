import hashlib
import json
import os
import shutil
import sqlite3
import stat
import threading
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath

import joblib
import pandas as pd

import database.db as db


BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE_DIR / "backups"
TEMP_DIR = BASE_DIR / "temp"
DATASET_PATH = BASE_DIR / "dataset" / "spam_dataset.csv"
MODEL_DIR = BASE_DIR / "model"
MODEL_FILENAMES = ("model.pkl", "vectorizer.pkl", "model_info.json")
REQUIRED_MEMBERS = {
    "database/database.db",
    "dataset/spam_dataset.csv",
    "model/model.pkl",
    "model/vectorizer.pkl",
    "model/model_info.json",
    "backup_manifest.json",
}
MAX_ARCHIVE_FILES = 5000
MAX_ARCHIVE_SIZE = 2 * 1024 * 1024 * 1024
_LOCK = threading.RLock()
_RESTORING = set()


class BackupError(ValueError):
    pass


@contextmanager
def _temporary_folder(prefix):
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    path = TEMP_DIR / f"{prefix}{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _now_stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_filename(filename):
    name = str(filename or "")
    if (
        not name.endswith(".zip")
        or Path(name).name != name
        or "/" in name
        or "\\" in name
        or "\x00" in name
        or not name.startswith(("backup_", "pre_restore_"))
    ):
        raise BackupError("Tên file sao lưu không hợp lệ.")
    return name


def get_backup_path(filename, must_exist=True):
    name = _safe_filename(filename)
    root = BACKUP_DIR.resolve()
    path = (root / name).resolve()
    if path.parent != root:
        raise BackupError("Đường dẫn file sao lưu không hợp lệ.")
    if must_exist and not path.is_file():
        raise BackupError("Không tìm thấy file sao lưu.")
    return path


def _unique_backup_path(prefix):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    base = f"{prefix}_{_now_stamp()}"
    candidate = BACKUP_DIR / f"{base}.zip"
    suffix = 1
    while candidate.exists():
        candidate = BACKUP_DIR / f"{base}_{suffix}.zip"
        suffix += 1
    return candidate


def _sqlite_backup(source_path, destination_path):
    source = sqlite3.connect(str(source_path))
    destination = sqlite3.connect(str(destination_path))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def _active_model_version(database_path):
    try:
        with sqlite3.connect(str(database_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT version FROM model_versions WHERE is_active = 1 "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row["version"] if row else None
    except sqlite3.Error:
        return None


def _source_files(database_snapshot):
    files = {
        "database/database.db": database_snapshot,
        "dataset/spam_dataset.csv": DATASET_PATH,
    }
    for filename in MODEL_FILENAMES:
        files[f"model/{filename}"] = MODEL_DIR / filename

    versions_dir = MODEL_DIR / "versions"
    if not versions_dir.is_dir():
        raise BackupError("Không tìm thấy thư mục phiên bản mô hình.")
    for path in sorted(versions_dir.rglob("*")):
        if path.is_file() and not path.is_symlink():
            relative = path.relative_to(versions_dir).as_posix()
            files[f"model/versions/{relative}"] = path
    return files


def create_backup(user_id=None, notes="", prefix="backup"):
    if prefix not in {"backup", "pre_restore"}:
        raise BackupError("Loại sao lưu không hợp lệ.")
    notes = (notes or "").strip()
    if len(notes) > 500:
        raise BackupError("Ghi chú không được vượt quá 500 ký tự.")

    with _LOCK:
        required_sources = [
            Path(db.DB_PATH),
            DATASET_PATH,
            *(MODEL_DIR / name for name in MODEL_FILENAMES),
            MODEL_DIR / "versions",
        ]
        if not all(path.exists() for path in required_sources):
            raise BackupError("Thiếu dữ liệu bắt buộc để tạo bản sao lưu.")

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        destination = _unique_backup_path(prefix)
        temporary_zip = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            with _temporary_folder("backup-") as folder:
                database_snapshot = folder / "database.db"
                _sqlite_backup(Path(db.DB_PATH), database_snapshot)
                files = _source_files(database_snapshot)

                dataset = pd.read_csv(DATASET_PATH)
                manifest_files = []
                for archive_name, source in files.items():
                    manifest_files.append({
                        "path": archive_name,
                        "size": source.stat().st_size,
                        "sha256": _sha256(source),
                    })
                manifest = {
                    "format_version": 1,
                    "app_version": "step-48",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "created_by": int(user_id) if user_id is not None else None,
                    "database": "database/database.db",
                    "dataset": "dataset/spam_dataset.csv",
                    "dataset_samples": int(len(dataset)),
                    "dataset_hash": _sha256(DATASET_PATH),
                    "active_model_version": _active_model_version(database_snapshot),
                    "files": manifest_files,
                }
                manifest_path = folder / "backup_manifest.json"
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                with zipfile.ZipFile(
                    temporary_zip, "w", compression=zipfile.ZIP_DEFLATED
                ) as archive:
                    archive.write(manifest_path, "backup_manifest.json")
                    archive.writestr("model/versions/", b"")
                    for archive_name, source in files.items():
                        archive.write(source, archive_name)
            os.replace(temporary_zip, destination)
            db.save_backup_record(
                destination.name,
                destination.stat().st_size,
                created_by=user_id,
                status="ready",
                notes=notes,
            )
            return get_backup_info(destination.name)
        except Exception as error:
            temporary_zip.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            if isinstance(error, BackupError):
                raise
            raise BackupError("Không thể tạo bản sao lưu.") from error


def _validate_member(info, seen):
    name = info.filename
    if not name or "\x00" in name or "\\" in name or name in seen:
        raise BackupError("Cấu trúc ZIP không hợp lệ.")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise BackupError("ZIP chứa đường dẫn không an toàn.")
    if stat.S_ISLNK(info.external_attr >> 16):
        raise BackupError("ZIP không được chứa symbolic link.")
    allowed = (
        name == "backup_manifest.json"
        or name in REQUIRED_MEMBERS
        or name.startswith("model/versions/")
    )
    if not allowed:
        raise BackupError("ZIP chứa file không thuộc phạm vi sao lưu.")
    seen.add(name)


def _read_manifest(archive):
    try:
        manifest = json.loads(archive.read("backup_manifest.json"))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise BackupError("Manifest của bản sao lưu không hợp lệ.") from error
    if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
        raise BackupError("Phiên bản manifest không được hỗ trợ.")
    return manifest


def _extract_archive(archive_path, destination):
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_FILES:
                raise BackupError("Bản sao lưu chứa quá nhiều file.")
            if sum(item.file_size for item in infos) > MAX_ARCHIVE_SIZE:
                raise BackupError("Dung lượng giải nén vượt giới hạn cho phép.")
            seen = set()
            for info in infos:
                _validate_member(info, seen)
            if not REQUIRED_MEMBERS.issubset(seen):
                raise BackupError("Bản sao lưu thiếu file bắt buộc.")
            if not any(name.startswith("model/versions/") for name in seen):
                raise BackupError("Bản sao lưu thiếu thư mục phiên bản mô hình.")

            manifest = _read_manifest(archive)
            root = destination.resolve()
            for info in infos:
                target = (root / PurePosixPath(info.filename)).resolve()
                if root not in target.parents and target != root:
                    raise BackupError("ZIP chứa đường dẫn không an toàn.")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, open(target, "wb") as output:
                    shutil.copyfileobj(source, output)
            return manifest
    except zipfile.BadZipFile as error:
        raise BackupError("File sao lưu không phải ZIP hợp lệ.") from error


def _validate_database(path):
    try:
        with sqlite3.connect(str(path)) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise BackupError("Database trong bản sao lưu bị lỗi.")
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not {"users", "predictions", "model_versions"}.issubset(tables):
                raise BackupError("Database trong bản sao lưu thiếu bảng bắt buộc.")
    except sqlite3.Error as error:
        raise BackupError("Database trong bản sao lưu không hợp lệ.") from error


def _validate_dataset(path):
    try:
        frame = pd.read_csv(path)
    except Exception as error:
        raise BackupError("Dataset trong bản sao lưu không đọc được.") from error
    if not {"label", "text"}.issubset(frame.columns) or frame.empty:
        raise BackupError("Dataset phải có hai cột label, text và có dữ liệu.")
    labels = frame["label"].astype(str).str.strip().str.lower()
    if not labels.isin({"spam", "ham"}).all():
        raise BackupError("Dataset chứa label không hợp lệ.")
    if frame["text"].isna().any():
        raise BackupError("Dataset chứa nội dung Email rỗng.")
    return len(frame)


def _validate_models(root, manifest, database_path):
    model_path = root / "model" / "model.pkl"
    vectorizer_path = root / "model" / "vectorizer.pkl"
    info_path = root / "model" / "model_info.json"
    try:
        model = joblib.load(model_path)
        vectorizer = joblib.load(vectorizer_path)
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except Exception as error:
        raise BackupError("File mô hình trong bản sao lưu không hợp lệ.") from error
    if not callable(getattr(model, "predict", None)):
        raise BackupError("Model trong bản sao lưu không thể dự đoán.")
    if not callable(getattr(vectorizer, "transform", None)):
        raise BackupError("Vectorizer trong bản sao lưu không hợp lệ.")
    if not isinstance(info, dict):
        raise BackupError("Thông tin mô hình không hợp lệ.")

    active_version = _active_model_version(database_path)
    manifest_version = manifest.get("active_model_version")
    info_version = info.get("version")
    if active_version and manifest_version and active_version != manifest_version:
        raise BackupError("Phiên bản model trong manifest không khớp database.")
    if active_version and info_version and active_version != info_version:
        raise BackupError("Model đang hoạt động không khớp database.")


def _validate_manifest_files(root, manifest):
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise BackupError("Danh sách checksum trong manifest không hợp lệ.")
    expected = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise BackupError("Checksum trong manifest không hợp lệ.")
        name = entry["path"]
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise BackupError("Manifest chứa đường dẫn không an toàn.")
        expected[name] = entry
    if not (REQUIRED_MEMBERS - {"backup_manifest.json"}).issubset(expected):
        raise BackupError("Manifest thiếu file bắt buộc.")
    for name, entry in expected.items():
        path = root / path_from_posix(name)
        if not path.is_file():
            raise BackupError("Manifest tham chiếu tới file không tồn tại.")
        if path.stat().st_size != entry.get("size") or _sha256(path) != entry.get("sha256"):
            raise BackupError("Checksum của bản sao lưu không khớp.")


def path_from_posix(value):
    return Path(*PurePosixPath(value).parts)


def _validate_extracted(root, manifest):
    _validate_manifest_files(root, manifest)
    database_path = root / "database" / "database.db"
    _validate_database(database_path)
    samples = _validate_dataset(root / "dataset" / "spam_dataset.csv")
    if manifest.get("dataset_samples") != samples:
        raise BackupError("Số mẫu Dataset không khớp manifest.")
    _validate_models(root, manifest, database_path)


def validate_backup(filename):
    archive_path = get_backup_path(filename)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    with _temporary_folder("validate-") as root:
        manifest = _extract_archive(archive_path, root)
        _validate_extracted(root, manifest)
        return manifest


def get_backup_info(filename):
    path = get_backup_path(filename)
    manifest = {}
    status = "ready"
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = _read_manifest(archive)
    except BackupError:
        status = "failed"
    except zipfile.BadZipFile:
        status = "failed"
    return {
        "filename": path.name,
        "file_size": path.stat().st_size,
        "created_at": manifest.get("created_at")
        or datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        "created_by": manifest.get("created_by"),
        "dataset_samples": manifest.get("dataset_samples"),
        "active_model_version": manifest.get("active_model_version"),
        "status": status,
    }


def list_backups():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    records = {row["filename"]: dict(row) for row in db.get_backup_records()}
    backups = []
    for path in BACKUP_DIR.glob("*.zip"):
        try:
            item = get_backup_info(path.name)
        except BackupError:
            continue
        record = records.get(path.name, {})
        item["status"] = "failed" if item["status"] == "failed" else record.get("status", "ready")
        item["notes"] = record.get("notes")
        item["creator_name"] = record.get("creator_name")
        item["creator_email"] = record.get("creator_email")
        backups.append(item)
    return sorted(backups, key=lambda item: item["created_at"], reverse=True)


def _replace_from_staging(root):
    token = uuid.uuid4().hex
    targets = {
        Path(db.DB_PATH): root / "database" / "database.db",
        DATASET_PATH: root / "dataset" / "spam_dataset.csv",
        **{
            MODEL_DIR / filename: root / "model" / filename
            for filename in MODEL_FILENAMES
        },
    }
    rollback_dir = TEMP_DIR / f"restore-rollback-{uuid.uuid4().hex}"
    rollback_dir.mkdir(parents=True)
    staged = []
    versions_old = MODEL_DIR / f".versions.old-{token}"
    versions_staged = MODEL_DIR / f".versions.restore-{token}"
    replaced = []
    try:
        for index, (target, source) in enumerate(targets.items()):
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = rollback_dir / f"file-{index}"
            existed = target.is_file()
            if existed:
                shutil.copy2(target, backup)
            temp = target.parent / f".{target.name}.restore-{token}"
            shutil.copy2(source, temp)
            staged.append((target, temp, backup, existed))

        shutil.copytree(root / "model" / "versions", versions_staged)
        current_versions = MODEL_DIR / "versions"
        if current_versions.exists():
            os.replace(current_versions, versions_old)
        os.replace(versions_staged, current_versions)

        for target, temp, _, _ in staged:
            os.replace(temp, target)
            replaced.append(target)
        for suffix in ("-wal", "-shm"):
            Path(f"{db.DB_PATH}{suffix}").unlink(missing_ok=True)
        db.init_db()
    except Exception:
        current_versions = MODEL_DIR / "versions"
        if versions_old.exists():
            if current_versions.exists():
                shutil.rmtree(current_versions, ignore_errors=True)
            os.replace(versions_old, current_versions)
        for target, _, backup, existed in reversed(staged):
            if existed and backup.exists():
                os.replace(backup, target)
            elif not existed and target in replaced:
                target.unlink(missing_ok=True)
        raise
    finally:
        for _, temp, _, _ in staged:
            temp.unlink(missing_ok=True)
        if versions_staged.exists():
            shutil.rmtree(versions_staged, ignore_errors=True)
        if versions_old.exists():
            shutil.rmtree(versions_old, ignore_errors=True)
        shutil.rmtree(rollback_dir, ignore_errors=True)


def restore_backup(filename, user_id=None):
    name = _safe_filename(filename)
    archive_path = get_backup_path(name)
    with _LOCK:
        if name in _RESTORING:
            raise BackupError("Bản sao lưu đang được khôi phục.")
        _RESTORING.add(name)
        try:
            TEMP_DIR.mkdir(parents=True, exist_ok=True)
            with _temporary_folder("restore-") as root:
                manifest = _extract_archive(archive_path, root)
                _validate_extracted(root, manifest)
                pre_restore = create_backup(
                    user_id=user_id,
                    notes=f"Tự động tạo trước khi khôi phục {name}",
                    prefix="pre_restore",
                )
                try:
                    _replace_from_staging(root)
                except Exception as error:
                    raise BackupError(
                        "Khôi phục thất bại; dữ liệu hiện tại đã được giữ nguyên."
                    ) from error
            db.save_backup_record(
                name,
                archive_path.stat().st_size,
                created_by=user_id,
                status="restored",
                notes=None,
            )
            pre_path = get_backup_path(pre_restore["filename"])
            db.save_backup_record(
                pre_path.name,
                pre_path.stat().st_size,
                created_by=user_id,
                status="ready",
                notes=f"Tự động tạo trước khi khôi phục {name}",
            )
            return {"backup": get_backup_info(name), "pre_restore": pre_restore}
        finally:
            _RESTORING.discard(name)


def delete_backup(filename):
    name = _safe_filename(filename)
    with _LOCK:
        if name in _RESTORING:
            raise BackupError("Không thể xóa bản sao lưu đang được khôi phục.")
        path = get_backup_path(name)
        path.unlink()
        db.delete_backup_record(name)
        return name


def format_file_size(value):
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
