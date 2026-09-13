import os

from cryptography.fernet import Fernet, InvalidToken


class CredentialConfigurationError(RuntimeError):
    pass


def _get_fernet():
    key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if not key:
        raise CredentialConfigurationError(
            "Thiếu CREDENTIAL_ENCRYPTION_KEY. Hãy cấu hình biến môi trường trước."
        )
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as error:
        raise CredentialConfigurationError(
            "CREDENTIAL_ENCRYPTION_KEY không phải Fernet key hợp lệ."
        ) from error


def encrypt_value(value):
    if not value:
        raise ValueError("Credential không được để trống.")
    return _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(value):
    if not value:
        raise CredentialConfigurationError("Tài khoản không còn credential.")
    try:
        return _get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as error:
        raise CredentialConfigurationError(
            "Không thể giải mã credential. Hãy kiểm tra encryption key."
        ) from error
