import hashlib
import secrets
import sqlite3
from functools import wraps

from flask import current_app, g, jsonify, request

from database.db import (
    create_api_key,
    get_api_key_by_hash,
    update_api_key_last_used,
)


def hash_api_key(api_key):
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generate_api_key(name, created_by):
    name = (name or "").strip()
    if not name:
        raise ValueError("Tên API Key không được để trống.")
    if len(name) > 100:
        raise ValueError("Tên API Key không được vượt quá 100 ký tự.")
    for _ in range(3):
        full_key = f"spam_{secrets.token_urlsafe(32)}"
        key_prefix = full_key[:13]
        try:
            api_key_id = create_api_key(
                name,
                key_prefix,
                hash_api_key(full_key),
                int(created_by),
            )
            break
        except sqlite3.IntegrityError:
            continue
    else:
        raise RuntimeError("Không thể tạo API Key duy nhất.")
    return {
        "id": api_key_id,
        "name": name,
        "key_prefix": key_prefix,
        "full_key": full_key,
    }


def api_error(message, status_code):
    return jsonify({"success": False, "error": message}), status_code


def api_key_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        supplied_key = request.headers.get("X-API-Key", "").strip()
        if not supplied_key:
            return api_error("API key is required.", 401)
        try:
            key_record = get_api_key_by_hash(hash_api_key(supplied_key))
        except Exception:
            current_app.logger.exception("API key authentication failed")
            return api_error("Unable to authenticate API key.", 500)
        if not key_record:
            return api_error("Invalid API key.", 401)
        if not key_record["is_active"]:
            return api_error("API key is disabled.", 403)
        try:
            update_api_key_last_used(key_record["id"])
        except Exception:
            current_app.logger.exception(
                "Unable to update API key usage for prefix %s",
                key_record["key_prefix"],
            )
            return api_error("Unable to authenticate API key.", 500)
        g.api_key_id = key_record["id"]
        g.api_key_prefix = key_record["key_prefix"]
        return view(*args, **kwargs)

    return wrapped_view
