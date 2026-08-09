import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# AES-256-GCM, not Fernet: encryption happens in the submit-provider-key Deno
# Edge Function, decryption happens here in Python — raw AES-GCM via each
# platform's native crypto (Web Crypto API / `cryptography`) is the thing
# that's actually cross-compatible, rather than porting Python's
# Fernet-specific token format to Deno.
NONCE_SIZE = 12


def _key() -> bytes:
    return base64.b64decode(os.environ["SETTINGS_ENCRYPTION_KEY"])


def encrypt_key(raw_key: str) -> str:
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = AESGCM(_key()).encrypt(nonce, raw_key.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt_key(encrypted_key: str) -> str:
    blob = base64.b64decode(encrypted_key)
    nonce, ciphertext = blob[:NONCE_SIZE], blob[NONCE_SIZE:]
    return AESGCM(_key()).decrypt(nonce, ciphertext, None).decode()


def mask_key(raw_key: str) -> str:
    return f"****{raw_key[-4:]}" if len(raw_key) >= 4 else "****"
