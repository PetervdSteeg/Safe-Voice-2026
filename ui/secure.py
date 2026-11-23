"""App-level encryption of the sensitive columns in the SQLite database (W4-01).

Titles, narratives, correction reasons and the structured data are stored as Fernet tokens
("enc:v1:..."). The key is SAFEVOICE_DB_KEY in .env. Without a key, new data is stored as plain
text (as before) and existing plain rows stay readable, so switching it on is safe.

    python -m ui.secure newkey     make a key to put in .env
    python -m ui.secure migrate    encrypt rows that are still stored as plain text

Keep the key apart from the database file and back it up: without it encrypted rows cannot be read.
This protects the file at rest; it does not replace disk encryption by the host (W4-04).
"""
import functools
import os
import sys

from dotenv import load_dotenv

PREFIX = "enc:v1:"
UNREADABLE = "[unreadable: modified, or wrong SAFEVOICE_DB_KEY]"


class KeyMissingError(RuntimeError):
    pass


def _key():
    key = os.getenv("SAFEVOICE_DB_KEY", "").strip()
    if not key:
        load_dotenv()
        key = os.getenv("SAFEVOICE_DB_KEY", "").strip()
    return key


@functools.lru_cache(maxsize=4)
def _fernet(key):
    from cryptography.fernet import Fernet
    return Fernet(key.encode())


def enabled():
    return bool(_key())


def encrypt(text):
    """Encrypt a string if a key is configured; otherwise return it unchanged."""
    key = _key()
    if not key or text is None or text.startswith(PREFIX):
        return text
    return PREFIX + _fernet(key).encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(text):
    """Plain text passes through. A token that cannot be decrypted is reported, not raised."""
    if text is None or not text.startswith(PREFIX):
        return text
    key = _key()
    if not key:
        raise KeyMissingError("The database has encrypted records but SAFEVOICE_DB_KEY is not set in .env.")
    from cryptography.fernet import InvalidToken
    try:
        return _fernet(key).decrypt(text[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        return UNREADABLE


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "newkey":
        from cryptography.fernet import Fernet
        print("Add this line to .env (and keep a backup of the key somewhere safe):")
        print(f"SAFEVOICE_DB_KEY={Fernet.generate_key().decode()}")
    elif command == "migrate":
        from ui import store
        print("Encrypted rows: %d topics, %d records." % store.encrypt_existing())
    else:
        print(__doc__)
