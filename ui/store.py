"""Persistent store for topics and records (P3-1, P3-2).

SQLite (standard library) in data/app/safevoice.db keeps what the UI lists: topics, immutable
records, their sync status. AllegroGraph stays the RDF store; every submitted record is
sent through the pipeline (cleaning -> RDF -> AllegroGraph) by submit_record().

The functions below are the interface the screens use. Every read and write is filtered by
the owner (W3-02), so one user can never see or change another user's data.
"""

import json
import os
import sqlite3
import traceback
import uuid
from contextlib import closing
from datetime import date, datetime

from src.orchestrator.payload import build_payload, payload_to_frame
from ui import audit, secure

DB_PATH = os.getenv("SAFEVOICE_DB", os.path.join("data", "app", "safevoice.db"))

SYNCED, NOT_SYNCED = "synced", "not_synced"

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES topics(id), owner TEXT NOT NULL,
    title TEXT NOT NULL, narrative TEXT NOT NULL, submitted TEXT NOT NULL,
    corrects TEXT, reason TEXT NOT NULL DEFAULT '', data TEXT NOT NULL,
    hash TEXT NOT NULL, sync_status TEXT NOT NULL, sync_message TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_records_owner ON records(owner, topic_id);
"""

# Coordinates are generalised to 3 decimals (about 110 m) when a record is saved (W4-02), so the
# stored copy, the screens and the RDF all have the same precision.
COORD_DECIMALS = 3
_COORD_PATHS = [(*base, axis) for base in (("incident", "departure"), ("incident", "destination"),
                                           ("victim", "current_location"))
                for axis in ("latitude", "longitude")]

# Date values inside a record's "data", stored as ISO text and turned back into dates on read.
_DATE_PATHS = [("incident", "departure", "date"), ("incident", "destination", "date"), ("publication", "date")]


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _new_id(prefix):
    """Random ID, e.g. R-3F9A1C7B2D. The table's primary key guarantees uniqueness (W1-04)."""
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _dumps(data):
    return json.dumps(data, default=lambda o: o.isoformat(), ensure_ascii=False)


def _loads(text):
    data = json.loads(text)
    for path in _DATE_PATHS:
        node = data
        for key in path[:-1]:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, dict) and node.get(path[-1]):
            node[path[-1]] = date.fromisoformat(node[path[-1]])
    return data


def round_coordinates(data):
    """Copy of a record's data with every coordinate rounded to COORD_DECIMALS."""
    data = json.loads(_dumps(data))
    for path in _COORD_PATHS:
        node = data
        for key in path[:-1]:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, dict) and isinstance(node.get(path[-1]), (int, float)):
            node[path[-1]] = round(node[path[-1]], COORD_DECIMALS)
    return _loads(json.dumps(data))


def _topic(row):
    return {**dict(row), "created": datetime.fromisoformat(row["created"]),
            "title": secure.decrypt(row["title"]), "description": secure.decrypt(row["description"])}


def _record(row):
    plain = secure.decrypt(row["data"])
    try:
        data = _loads(plain)
    except (ValueError, TypeError, AttributeError):  # unreadable or damaged: show nothing, the hash check fails
        data = {}
    return {**dict(row), "submitted": datetime.fromisoformat(row["submitted"]),
            "title": secure.decrypt(row["title"]), "narrative": secure.decrypt(row["narrative"]),
            "reason": secure.decrypt(row["reason"]), "data": data}


# ---- Topics ----

def get_topics(user):
    """Topics owned by this user, most recently active first."""
    with closing(_connect()) as db:
        topics = [_topic(r) for r in db.execute("SELECT * FROM topics WHERE owner = ?", (user,))]
    return sorted(topics, key=last_activity, reverse=True)


def get_topic(user, topic_id):
    """Return the topic only if this user owns it (ownership check, W3-02)."""
    with closing(_connect()) as db:
        row = db.execute("SELECT * FROM topics WHERE id = ? AND owner = ?", (topic_id, user)).fetchone()
    return _topic(row) if row else None


def create_topic(user, title, description):
    topic = {"id": _new_id("T"), "owner": user, "title": title, "description": description,
             "created": datetime.now()}
    with closing(_connect()) as db, db:
        db.execute("INSERT INTO topics VALUES (?, ?, ?, ?, ?)",
                   (topic["id"], user, secure.encrypt(title), secure.encrypt(description),
                    topic["created"].isoformat()))
    audit.log(user, "topic_created", detail=topic["id"])
    return topic


def last_activity(topic):
    with closing(_connect()) as db:
        row = db.execute("SELECT MAX(submitted) FROM records WHERE topic_id = ? AND owner = ?",
                         (topic["id"], topic["owner"])).fetchone()
    return max(datetime.fromisoformat(row[0]), topic["created"]) if row[0] else topic["created"]


# ---- Records ----

def get_records(user, topic_id):
    """All records in a topic for this user, oldest first."""
    with closing(_connect()) as db:
        rows = db.execute("SELECT * FROM records WHERE topic_id = ? AND owner = ? ORDER BY submitted",
                          (topic_id, user)).fetchall()
    return [_record(r) for r in rows]


def get_record(user, record_id):
    with closing(_connect()) as db:
        row = db.execute("SELECT * FROM records WHERE id = ? AND owner = ?", (record_id, user)).fetchone()
    return _record(row) if row else None


def get_corrections(user, record_id):
    """Corrections that directly correct this record, oldest first."""
    with closing(_connect()) as db:
        rows = db.execute("SELECT * FROM records WHERE corrects = ? AND owner = ? ORDER BY submitted",
                          (record_id, user)).fetchall()
    return [_record(r) for r in rows]


def get_root(user, record):
    """Follow 'corrects' links back to the original record."""
    seen = set()  # stops a loop if the corrects links were ever damaged
    while record and record["corrects"] and record["id"] not in seen:
        seen.add(record["id"])
        record = get_record(user, record["corrects"])
    return record


def get_chain(user, record):
    """Original record followed by all its corrections, in time order."""
    root = get_root(user, record)
    if root is None:  # the corrected record is missing (or not this user's): show only this one
        return [record]
    chain, todo, seen = [], [root], set()
    while todo:
        r = todo.pop(0)
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        chain.append(r)
        todo.extend(get_corrections(user, r["id"]))
    return sorted(chain, key=lambda r: r["submitted"])


def verify_record(record):
    """True if the stored content still matches the hash taken at submission (W3-05)."""
    return audit.hash_matches(record, record["hash"])


def submit_record(user, topic_id, title, narrative, data, corrects=None, reason=""):
    """Store a new immutable record and send it through the pipeline.

    ID and timestamp are generated here. The record is saved first; if the pipeline or the
    database is unavailable it stays saved with sync_status "not_synced" and can be retried
    with retry_sync(). Raises PermissionError if the topic (or the corrected record) is not the user's.
    """
    if not get_topic(user, topic_id):
        raise PermissionError("Topic not found or not owned by this user.")
    if corrects:
        original = get_record(user, corrects)
        if not original or original["topic_id"] != topic_id:
            raise PermissionError("Corrected record not found in this topic.")

    data = round_coordinates(data)
    record = {"topic_id": topic_id, "owner": user, "title": title, "narrative": narrative,
              "submitted": datetime.now(), "corrects": corrects, "reason": reason, "data": data}
    while True:
        record["id"] = _new_id("R")
        record["hash"] = audit.record_hash(record)
        try:
            with closing(_connect()) as db, db:
                db.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (record["id"], topic_id, user, secure.encrypt(title), secure.encrypt(narrative),
                            record["submitted"].isoformat(), corrects, secure.encrypt(reason),
                            secure.encrypt(_dumps(data)), record["hash"], NOT_SYNCED, ""))
            break
        except sqlite3.IntegrityError:
            continue  # ID collision (vanishingly rare): draw another
    audit.log(user, "record_submitted", record["id"], f"topic {topic_id}")
    return _sync(get_record(user, record["id"]))


def encrypt_existing():
    """Encrypt rows still stored as plain text. Returns (topics, records) changed. Needs SAFEVOICE_DB_KEY.

    The integrity hash covers the readable content, so it stays valid.
    """
    if not secure.enabled():
        raise secure.KeyMissingError("Set SAFEVOICE_DB_KEY in .env first (python -m ui.secure newkey).")
    counts = []
    with closing(_connect()) as db, db:
        for table, columns in (("topics", ("title", "description")),
                               ("records", ("title", "narrative", "reason", "data"))):
            changed = 0
            for row in db.execute(f"SELECT * FROM {table}").fetchall():
                new = {c: secure.encrypt(row[c]) for c in columns if not row[c].startswith(secure.PREFIX)}
                if new:
                    sets = ", ".join(f"{c} = ?" for c in new)
                    db.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*new.values(), row["id"]))
                    changed += 1
            counts.append(changed)
    audit.log("system", "db_encrypted", detail=f"topics {counts[0]}, records {counts[1]}")
    return tuple(counts)


def seal_hashes():
    """Turn plain integrity hashes into keyed ones (needs SAFEVOICE_INTEGRITY_KEY). Returns (sealed, skipped).

    Only records that still match their plain hash are sealed; a record that already fails the check is
    left alone (skipped) so tampering is not hidden by re-hashing.
    """
    if not audit.integrity_key():
        raise secure.KeyMissingError("Set SAFEVOICE_INTEGRITY_KEY in .env first (python -m ui.secure newkey).")
    sealed = skipped = 0
    with closing(_connect()) as db, db:
        for row in db.execute("SELECT * FROM records").fetchall():
            if row["hash"].startswith("hmac:"):
                continue
            record = _record(row)
            if audit.plain_hash(record) != row["hash"]:
                skipped += 1
                continue
            db.execute("UPDATE records SET hash = ? WHERE id = ?", (audit.record_hash(record), row["id"]))
            sealed += 1
    audit.log("system", "hashes_sealed", detail=f"sealed {sealed}, skipped {skipped}")
    return sealed, skipped


def resync_all(user=None, only_unsynced=False):
    """Send stored records through the pipeline again (for example after the mapping or the CDM changed).

    All users unless `user` is given. Returns (synced, failed). The uploads ADD triples to the user's
    graph: drop it first (python -m src.storage.admin drop-user NAME) to get rid of the old terms.
    """
    query, args = "SELECT * FROM records", []
    clauses = (["owner = ?"] if user else []) + (["sync_status != 'synced'"] if only_unsynced else [])
    if user:
        args.append(user)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    with closing(_connect()) as db:
        rows = db.execute(query + " ORDER BY submitted", args).fetchall()
    synced = failed = 0
    for row in rows:
        result = _sync(_record(row))
        synced += result["sync_status"] == SYNCED
        failed += result["sync_status"] != SYNCED
    audit.log(user or "system", "records_resynced", detail=f"synced {synced}, failed {failed}")
    return synced, failed


def run_pipeline(df):
    """Indirection so tests can replace the pipeline (it needs a live AllegroGraph)."""
    from src.orchestrator import run_full_pipeline
    return run_full_pipeline(df)


def _failure_reason(status):
    """Why the last upload or validation failed (settings, properties; never report content)."""
    try:
        if "Ingestion" in status:
            from src.storage import ingest
            return ingest.last_error or ""
        if "Validation" in status:
            from src.validation import shacl
            return shacl.last_report or ""
    except Exception:  # noqa: BLE001
        pass
    return ""


def _sync(record):
    """Run the pipeline for a stored record and save the outcome. Never raises."""
    try:
        _, status = run_pipeline(payload_to_frame(build_payload(record)))
    except Exception as exc:  # noqa: BLE001 - shown to the user as a plain message, details go to the log
        status = "Failed: unexpected error"
        # Exception type and place only: the message could contain report content.
        where = traceback.extract_tb(exc.__traceback__)[-1] if exc.__traceback__ else None
        place = f" at {os.path.basename(where.filename)}:{where.lineno}" if where else ""
        audit.log(record["owner"], "record_sync_error", record["id"], type(exc).__name__ + place)
    reason = _failure_reason(status)
    if status == "Success":
        state, message = SYNCED, ""
    elif "Ingestion" in status and reason.startswith("Missing in .env"):
        state, message = NOT_SYNCED, "The database settings in .env are incomplete."
    elif "Ingestion" in status:
        state, message = NOT_SYNCED, "The database could not be reached."
    else:
        state, message = NOT_SYNCED, "The record could not be prepared for the database."
    with closing(_connect()) as db, db:
        db.execute("UPDATE records SET sync_status = ?, sync_message = ? WHERE id = ? AND owner = ?",
                   (state, message, record["id"], record["owner"]))
    audit.log(record["owner"], "record_synced" if state == SYNCED else "record_not_synced", record["id"],
              f"{status}: {reason}" if reason else status)
    return get_record(record["owner"], record["id"])


def retry_sync(user, record_id):
    """Send a record that is not yet in the database through the pipeline again."""
    record = get_record(user, record_id)
    if record is None:
        raise PermissionError("Record not found.")
    return record if record["sync_status"] == SYNCED else _sync(record)
