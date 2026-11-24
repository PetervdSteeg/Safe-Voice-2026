"""Append-only audit log and record integrity hash (P2-5).

One JSON line per event: time, user, action, record ID, detail. The file is only ever
opened in append mode. Contents of reports are never written to the log.
"""
import hashlib
import hmac
import json
import os
import threading
from datetime import datetime

from dotenv import load_dotenv

AUDIT_LOG = os.getenv("SAFEVOICE_AUDIT_LOG", os.path.join("data", "audit", "audit.log"))


_lock = threading.Lock()


def _line_hash(raw):
    return hashlib.sha256(raw if isinstance(raw, bytes) else raw.encode("utf-8")).hexdigest()


def _last_line_hash():
    """Hash of the last line already in the log ("" for an empty log): the next line points back to it."""
    if not os.path.exists(AUDIT_LOG):
        return ""
    with open(AUDIT_LOG, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        fh.seek(max(0, fh.tell() - 8192))
        lines = fh.read().splitlines()
    return _line_hash(lines[-1]) if lines else ""


def log(user, action, record_id=None, detail=""):
    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    with _lock:
        # Every line carries the hash of the line before it, so an edited, removed or inserted line
        # in the middle of the log is found by verify_log() (W3-05).
        # detail can contain text typed by a user (URL parameters, usernames): keep each line small.
        line = json.dumps({"time": datetime.now().isoformat(timespec="seconds"), "user": user,
                           "action": action, "record_id": record_id, "detail": str(detail)[:200],
                           "prev": _last_line_hash()})
        with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def verify_log(path=None):
    """Check the hash chain. Returns (ok, first_bad_line_number or None, number_of_lines).

    Lines written before the chain existed are accepted as they are. Cutting lines off the END of the
    log cannot be seen from the log itself; keep a copy of the last line's hash elsewhere if needed.
    """
    path = path or AUDIT_LOG
    if not os.path.exists(path):
        return True, None, 0
    with open(path, "rb") as fh:
        lines = fh.read().splitlines()
    count, prev, chained = len(lines), "", False
    for number, raw in enumerate(lines, start=1):
        try:
            entry = json.loads(raw)
        except ValueError:
            return False, number, count
        if "prev" in entry:
            chained = True
            if entry["prev"] != prev:
                return False, number, count
        elif chained:  # a line without the chain after chained ones was inserted
            return False, number, count
        prev = _line_hash(raw)
    return True, None, count


def _blob(record):
    content = {k: record[k] for k in ("id", "topic_id", "owner", "title", "narrative", "corrects", "reason")}
    content["submitted"] = record["submitted"].isoformat()
    content["data"] = record["data"]
    return json.dumps(content, sort_keys=True, default=lambda o: o.isoformat(), ensure_ascii=False).encode("utf-8")


def integrity_key():
    """SAFEVOICE_INTEGRITY_KEY from .env (empty = plain SHA-256 hashes, as before)."""
    key = os.getenv("SAFEVOICE_INTEGRITY_KEY", "").strip()
    if not key:
        load_dotenv()
        key = os.getenv("SAFEVOICE_INTEGRITY_KEY", "").strip()
    return key


def strict_integrity():
    """With SAFEVOICE_INTEGRITY_STRICT=true only keyed hashes count, so a plain hash someone computed
    after editing a record is not accepted. Turn it on after `python -m ui.secure sealhash`."""
    return os.getenv("SAFEVOICE_INTEGRITY_STRICT", "").strip().lower() in ("1", "true", "yes")


def plain_hash(record):
    """SHA-256 over the immutable content of a record. Changes if anything in it is edited later."""
    return hashlib.sha256(_blob(record)).hexdigest()


def record_hash(record):
    """The hash stored with a new record: keyed (HMAC, "hmac:...") when a key is set, else plain.

    A plain hash lives in the same database as the record, so someone who can edit the database can
    recompute it. A keyed hash needs the key from .env as well.
    """
    key = integrity_key()
    if key:
        return "hmac:" + hmac.new(key.encode("utf-8"), _blob(record), hashlib.sha256).hexdigest()
    return plain_hash(record)


def hash_matches(record, stored):
    """True if the record's content still matches the stored hash (plain or keyed)."""
    if stored.startswith("hmac:"):
        return bool(integrity_key()) and hmac.compare_digest(record_hash(record), stored)
    if strict_integrity() and integrity_key():
        return False
    return hmac.compare_digest(plain_hash(record), stored)


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["verify"]:
        ok, line, count = verify_log()
        print(f"Audit log OK: {count} lines, chain intact." if ok else f"Audit log CHANGED: first bad line is {line} (of {count}).")
        sys.exit(0 if ok else 1)
    print("Usage: python -m ui.audit verify")
