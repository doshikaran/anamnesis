"""
AES-256 token encryption (Fernet). Encrypt OAuth access_token and refresh_token before storing.
Per-user key derivation from master key + user_id. Never store raw OAuth tokens.
"""

import base64
import hashlib
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.config import get_settings
from app.core.exceptions import ValidationError

settings = get_settings()

FERNET_SALT = b"anamnesis-token-encryption-v1"


def _derive_key(user_id: UUID) -> bytes:
    """Derive a Fernet key from master key + user_id."""
    master = settings.ENCRYPTION_MASTER_KEY
    if not master:
        raise ValidationError(code="ENCRYPTION_NOT_CONFIGURED", message="Encryption key not set")
    if isinstance(master, str):
        master = master.encode("utf-8")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=FERNET_SALT,
        iterations=100000,
    )
    key_material = kdf.derive(master + str(user_id).encode("utf-8"))
    return base64.urlsafe_b64encode(key_material)


def encrypt_token(user_id: UUID, plaintext: str) -> str:
    """Encrypt a token for storage. Returns base64-encoded ciphertext."""
    if not plaintext:
        return ""
    key = _derive_key(user_id)
    f = Fernet(key)
    return f.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_token(user_id: UUID, ciphertext: str) -> str:
    """Decrypt a stored token. Returns plaintext."""
    if not ciphertext:
        return ""
    key = _derive_key(user_id)
    f = Fernet(key)
    try:
        return f.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise ValidationError(code="DECRYPT_FAILED", message="Failed to decrypt token")
