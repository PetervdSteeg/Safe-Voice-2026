"""Audit log hash chain and keyed record hashes (W3-05)."""
import json
import sqlite3

import pytest

from ui import audit, secure, store


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_LOG", str(tmp_path / "audit" / "audit.log"))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "app" / "t.db"))
    monkeypatch.setattr(store, "run_pipeline", lambda df: (df, "Success"))
    monkeypatch.setattr(audit, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(secure, "load_dotenv", lambda *a, **k: None)
    for var in ("SAFEVOICE_INTEGRITY_KEY", "SAFEVOICE_INTEGRITY_STRICT", "SAFEVOICE_DB_KEY"):
        monkeypatch.delenv(var, raising=False)


def _lines():
    return open(audit.AUDIT_LOG, encoding="utf-8").read().splitlines()


def _write(lines):
    import os
    os.makedirs(os.path.dirname(audit.AUDIT_LOG), exist_ok=True)
    open(audit.AUDIT_LOG, "w", encoding="utf-8").write("\n".join(lines) + "\n")


def _log(n=5):
    for i in range(n):
        audit.log("alice", "action", f"R-{i}", f"detail {i}")


# ---------------------------------------------------------------- audit log chain

def test_an_untouched_log_verifies():
    _log()
    assert audit.verify_log() == (True, None, 5)
    assert json.loads(_lines()[0])["prev"] == "" and json.loads(_lines()[1])["prev"] != ""


def test_an_empty_or_missing_log_verifies():
    assert audit.verify_log() == (True, None, 0)


def test_an_edited_line_is_found():
    _log()
    lines = _lines()
    lines[2] = lines[2].replace("detail 2", "detail X")
    _write(lines)
    assert audit.verify_log() == (False, 4, 5)  # the line after the edited one no longer matches


def test_a_removed_line_is_found():
    _log()
    lines = _lines()
    del lines[1]
    _write(lines)
    ok, bad, _ = audit.verify_log()
    assert not ok and bad == 2


def test_an_inserted_line_is_found():
    _log()
    lines = _lines()
    lines.insert(2, json.dumps({"time": "x", "user": "mallory", "action": "login", "record_id": None, "detail": ""}))
    _write(lines)
    assert audit.verify_log()[0] is False


def test_old_lines_without_a_chain_are_accepted_and_the_chain_starts_after_them():
    _write([json.dumps({"time": "t", "user": "a", "action": "old", "record_id": None, "detail": ""})] * 2)
    _log(3)
    assert audit.verify_log() == (True, None, 5)


def test_a_garbled_line_is_found():
    _log(2)
    _write(_lines() + ["not json"])
    assert audit.verify_log()[:2] == (False, 3)


def test_concurrent_writers_keep_the_chain_intact():
    import threading
    threads = [threading.Thread(target=_log, args=(10,)) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert audit.verify_log() == (True, None, 40)


# ---------------------------------------------------------------- keyed record hashes

def _submit():
    topic = store.create_topic("alice", "T", "")
    return store.submit_record("alice", topic["id"], "Title", "Narrative", {"victim": {"age": 3}})


def _tamper(record_id):
    with sqlite3.connect(store.DB_PATH) as db:
        db.execute("UPDATE records SET narrative = 'changed' WHERE id = ?", (record_id,))


def test_without_a_key_hashes_are_plain_as_before():
    rec = _submit()
    assert not rec["hash"].startswith("hmac:") and len(rec["hash"]) == 64 and store.verify_record(rec)


def test_with_a_key_new_records_get_a_keyed_hash(monkeypatch):
    monkeypatch.setenv("SAFEVOICE_INTEGRITY_KEY", "k" * 32)
    rec = _submit()
    assert rec["hash"].startswith("hmac:") and store.verify_record(store.get_record("alice", rec["id"]))
    _tamper(rec["id"])
    assert not store.verify_record(store.get_record("alice", rec["id"]))


def test_a_keyed_hash_cannot_be_recomputed_without_the_key(monkeypatch):
    monkeypatch.setenv("SAFEVOICE_INTEGRITY_KEY", "k" * 32)
    rec = _submit()
    _tamper(rec["id"])
    forged = audit.plain_hash(store.get_record("alice", rec["id"]))  # what someone with only the database can do
    with sqlite3.connect(store.DB_PATH) as db:
        db.execute("UPDATE records SET hash = ? WHERE id = ?", (forged, rec["id"]))
    assert store.verify_record(store.get_record("alice", rec["id"]))  # non-strict mode still accepts a plain hash
    monkeypatch.setenv("SAFEVOICE_INTEGRITY_STRICT", "true")
    assert not store.verify_record(store.get_record("alice", rec["id"]))  # strict mode does not


def test_wrong_or_missing_key_fails_the_check(monkeypatch):
    monkeypatch.setenv("SAFEVOICE_INTEGRITY_KEY", "k" * 32)
    rec = _submit()
    monkeypatch.setenv("SAFEVOICE_INTEGRITY_KEY", "z" * 32)
    assert not store.verify_record(store.get_record("alice", rec["id"]))
    monkeypatch.delenv("SAFEVOICE_INTEGRITY_KEY")
    assert not store.verify_record(store.get_record("alice", rec["id"]))


def test_sealing_converts_good_plain_hashes_and_skips_tampered_ones(monkeypatch):
    good, bad = _submit(), _submit()
    _tamper(bad["id"])
    with pytest.raises(secure.KeyMissingError):
        store.seal_hashes()
    monkeypatch.setenv("SAFEVOICE_INTEGRITY_KEY", "k" * 32)
    assert store.seal_hashes() == (1, 1)
    assert store.get_record("alice", good["id"])["hash"].startswith("hmac:")
    assert store.verify_record(store.get_record("alice", good["id"]))
    assert not store.get_record("alice", bad["id"])["hash"].startswith("hmac:")  # not hidden by re-hashing
    assert not store.verify_record(store.get_record("alice", bad["id"]))
    assert store.seal_hashes() == (0, 1)
