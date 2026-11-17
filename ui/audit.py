"""Append-only audit log and record integrity hash (P2-5).

One JSON line per event: time, user, action, record ID, detail. The file is only ever
opened in append mode. Contents of reports are never written to the log.
"""
import hashlib
import json
import os
from datetime import datetime

AUDIT_LOG = os.getenv("SAFEVOICE_AUDIT_LOG", os.path.join("data", "audit", "audit.log"))


def log(user, action, record_id=None, detail=""):
    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    # detail can contain text typed by a user (URL parameters, usernames): keep each line small.
    line = json.dumps({"time": datetime.now().isoformat(timespec="seconds"), "user": user,
                       "action": action, "record_id": record_id, "detail": str(detail)[:200]})
    with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def record_hash(record):
    """SHA-256 over the immutable content of a record. Changes if anything in it is edited later."""
    content = {k: record[k] for k in ("id", "topic_id", "owner", "title", "narrative", "corrects", "reason")}
    content["submitted"] = record["submitted"].isoformat()
    content["data"] = record["data"]
    blob = json.dumps(content, sort_keys=True, default=lambda o: o.isoformat(), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
