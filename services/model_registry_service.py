import hashlib
import json
import logging
import os
import shutil
import sqlite3
import uuid
from pathlib import Path

import joblib

from database.db import (
    create_model_version,
    get_active_model_version as get_active_model_version_from_db,
    get_max_model_version_number,
    get_model_events,
    get_model_version as get_model_version_from_db,
    get_model_versions as get_model_versions_from_db,
    set_active_model_version,
)
from ml.train import train_model


logger = logging.getLogger(__name__)


BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = BASE_DIR / "model"
VERSIONS_DIR = MODEL_DIR / "versions"
DATASET_PATH = BASE_DIR / "dataset" / "spam_dataset.csv"
ACTIVE_FILENAMES = ("model.pkl", "vectorizer.pkl", "model_info.json")


def calculate_file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def calculate_dataset_hash(dataset_path=None):
    return calculate_file_hash(dataset_path or DATASET_PATH)


def get_next_version():
    return f"v{get_max_model_version_number() + 1:04d}"


def get_model_versions():
    return get_model_versions_from_db()


def get_model_version(version_id):
    return get_model_version_from_db(version_id)


def get_active_model_version():
    return get_active_model_version_from_db()


def get_recent_model_events(limit=20):
    return get_model_events(limit)


def _relative_path(path):
    return Path(path).resolve().relative_to(BASE_DIR).as_posix()


def _resolve_version_path(stored_path):
    path = (BASE_DIR / stored_path).resolve()
    versions_root = VERSIONS_DIR.resolve()
    if os.path.commonpath((str(path), str(versions_root))) != str(versions_root):
        raise ValueError("Đường dẫn phiên bản mô hình không hợp lệ.")
    return path


def _load_info(path):
    with open(path, "r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("Metadata mô hình không hợp lệ.")
    return value


def verify_model_version(record):
    try:
        model_path = _resolve_version_path(record["model_path"])
        vectorizer_path = _resolve_version_path(record["vectorizer_path"])
        info_path = _resolve_version_path(record["info_path"])
        for path in (model_path, vectorizer_path, info_path):
            if not path.is_file():
                raise ValueError("Thiếu file của phiên bản mô hình.")
        model = joblib.load(model_path)
        vectorizer = joblib.load(vectorizer_path)
        info = _load_info(info_path)
        if not callable(getattr(model, "predict", None)):
            raise ValueError("File model không thể dự đoán.")
        if not callable(getattr(vectorizer, "transform", None)):
            raise ValueError("File vectorizer không hợp lệ.")
        if info.get("version") != record["version"]:
            raise ValueError("Metadata không khớp phiên bản.")
        expected_hashes = {
            model_path: info.get("model_hash"),
            vectorizer_path: info.get("vectorizer_hash"),
        }
        for path, expected in expected_hashes.items():
            if expected and calculate_file_hash(path) != expected:
                raise ValueError("Checksum file mô hình không khớp.")
        return model_path, vectorizer_path, info_path
    except Exception as error:
        raise ValueError(
            "Phiên bản mô hình không hợp lệ hoặc bị hỏng."
        ) from error


def _install_and_activate(record, user_id, event_type):
    sources = verify_model_version(record)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temporary = []
    backups = []
    replaced = []
    try:
        for source, filename in zip(sources, ACTIVE_FILENAMES):
            target = MODEL_DIR / filename
            temp = MODEL_DIR / f".{filename}.{token}.tmp"
            backup = MODEL_DIR / f".{filename}.{token}.bak"
            shutil.copy2(source, temp)
            temporary.append(temp)
            if target.exists():
                shutil.copy2(target, backup)
                backups.append((target, backup, True))
            else:
                backups.append((target, backup, False))
        for temp, filename in zip(temporary, ACTIVE_FILENAMES):
            target = MODEL_DIR / filename
            os.replace(temp, target)
            replaced.append(target)
        set_active_model_version(record["id"], user_id, event_type)
    except Exception:
        for target, backup, existed in backups:
            if existed and backup.exists():
                os.replace(backup, target)
            elif not existed and target in replaced and target.exists():
                target.unlink()
        raise
    finally:
        for path in temporary:
            if path.exists():
                path.unlink()
        for _, backup, _ in backups:
            if backup.exists():
                backup.unlink()


def activate_model_version(version_id, admin_id, event_type="activate"):
    record = get_model_version(version_id)
    if not record:
        raise ValueError("Phiên bản mô hình không tồn tại.")
    if record["is_active"]:
        return record
    _install_and_activate(record, admin_id, event_type)
    return get_model_version(version_id)


def rollback_model(version_id, admin_id):
    return activate_model_version(version_id, admin_id, event_type="rollback")


def _build_record(info, snapshot_dir, created_by, notes):
    ngram_range = info.get("ngram_range") or [1, 2]
    return {
        "version": info["version"],
        "model_name": info.get("model_name", "Multinomial Naive Bayes"),
        "vectorizer": info.get("vectorizer", "TF-IDF"),
        "accuracy": info.get("accuracy"),
        "precision": info.get("precision"),
        "recall": info.get("recall"),
        "f1": info.get("f1"),
        "tn": info.get("tn"),
        "fp": info.get("fp"),
        "fn": info.get("fn"),
        "tp": info.get("tp"),
        "train_size": info.get("train_size"),
        "test_size": info.get("test_size"),
        "dataset_size": info.get("total"),
        "vocabulary_size": info.get("vocabulary_size"),
        "training_time": info.get("training_time"),
        "alpha": info.get("alpha", 1.0),
        "ngram_min": int(ngram_range[0]),
        "ngram_max": int(ngram_range[-1]),
        "dataset_hash": info.get("dataset_hash"),
        "model_path": _relative_path(snapshot_dir / "model.pkl"),
        "vectorizer_path": _relative_path(snapshot_dir / "vectorizer.pkl"),
        "info_path": _relative_path(snapshot_dir / "model_info.json"),
        "created_by": created_by,
        "notes": notes,
    }


def _write_info(path, info):
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(info, stream, ensure_ascii=False, indent=4)


def _finalize_snapshot(staging_dir, version):
    snapshot_dir = VERSIONS_DIR / version
    if snapshot_dir.exists():
        raise ValueError("Thư mục phiên bản đã tồn tại.")
    os.replace(staging_dir, snapshot_dir)
    return snapshot_dir


def train_and_register_model(created_by, notes=""):
    notes = (notes or "").strip()
    if len(notes) > 500:
        raise ValueError("Ghi chú không được vượt quá 500 ký tự.")
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    version = get_next_version()
    dataset_hash = calculate_dataset_hash()
    staging_dir = VERSIONS_DIR / f".staging-{version}-{uuid.uuid4().hex}"
    snapshot_dir = None
    registered = False
    try:
        result = train_model(
            output_dir=str(staging_dir),
            metadata_updates={
                "version": version,
                "dataset_hash": dataset_hash,
                "created_by": int(created_by),
            },
        )
        if calculate_dataset_hash() != dataset_hash:
            raise RuntimeError("Dataset đã thay đổi trong lúc huấn luyện.")
        info_path = staging_dir / "model_info.json"
        info = _load_info(info_path)
        info["model_hash"] = calculate_file_hash(staging_dir / "model.pkl")
        info["vectorizer_hash"] = calculate_file_hash(
            staging_dir / "vectorizer.pkl"
        )
        _write_info(info_path, info)
        snapshot_dir = _finalize_snapshot(staging_dir, version)
        record = _build_record(info, snapshot_dir, int(created_by), notes)
        version_id = create_model_version(record)
        registered = True
        activate_model_version(version_id, int(created_by), event_type="train")
        return {**result, **info, "id": version_id, "is_active": True}
    except sqlite3.IntegrityError as error:
        raise RuntimeError(
            "Không thể tạo phiên bản model do trùng số phiên bản."
        ) from error
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        if snapshot_dir and snapshot_dir.exists() and not registered:
            shutil.rmtree(snapshot_dir, ignore_errors=True)


def initialize_model_registry():
    if get_model_versions():
        return get_active_model_version()
    canonical = [MODEL_DIR / filename for filename in ACTIVE_FILENAMES]
    if not all(path.is_file() for path in canonical):
        return None

    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    version = "v0001"
    staging_dir = VERSIONS_DIR / f".staging-{version}-{uuid.uuid4().hex}"
    snapshot_dir = None
    registered = False
    try:
        staging_dir.mkdir(parents=True)
        shutil.copy2(canonical[0], staging_dir / ACTIVE_FILENAMES[0])
        shutil.copy2(canonical[1], staging_dir / ACTIVE_FILENAMES[1])
        info = _load_info(canonical[2])
        try:
            from ml.evaluate import evaluate_model

            info.update(evaluate_model())
        except Exception:
            logger.exception("Initial model metrics could not be calculated")
        info.update({
            "version": version,
            "dataset_hash": calculate_dataset_hash(),
            "created_by": None,
            "model_hash": calculate_file_hash(staging_dir / "model.pkl"),
            "vectorizer_hash": calculate_file_hash(
                staging_dir / "vectorizer.pkl"
            ),
        })
        _write_info(staging_dir / "model_info.json", info)
        snapshot_dir = _finalize_snapshot(staging_dir, version)
        version_id = create_model_version(
            _build_record(info, snapshot_dir, None, "Model hiện có được đăng ký tự động."),
        )
        registered = True
        return activate_model_version(version_id, None, event_type="activate")
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        if snapshot_dir and snapshot_dir.exists() and not registered:
            shutil.rmtree(snapshot_dir, ignore_errors=True)
