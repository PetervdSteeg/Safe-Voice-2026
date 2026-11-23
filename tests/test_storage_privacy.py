"""Privacy of the local database: coordinate rounding (W4-02) and encryption of sensitive columns (W4-01)."""
import sqlite3

import pytest
from cryptography.fernet import Fernet

from ui import audit, secure, store

DATA = {"incident": {"departure": {"country": "Sudan", "latitude": 15.45678, "longitude": -36.123456},
                     "destination": {"town": "Tripoli", "latitude": None, "longitude": None}},
        "victim": {"age": 17, "current_location": {"latitude": 1.23456, "longitude": 2.34567}}}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "app" / "t.db"))
    monkeypatch.setattr(audit, "AUDIT_LOG", str(tmp_path / "audit" / "audit.log"))
    monkeypatch.setattr(store, "run_pipeline", lambda df: (df, "Success"))
    monkeypatch.setattr(secure, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("SAFEVOICE_DB_KEY", raising=False)


def _enable(monkeypatch):
    monkeypatch.setenv("SAFEVOICE_DB_KEY", Fernet.generate_key().decode())


def _submit(user="alice", **kw):
    topic = store.create_topic(user, "Secret topic", "Secret description")
    return topic, store.submit_record(user, topic["id"], "Secret title", "Secret narrative", DATA, reason="why", **kw)


def _raw(table="records"):
    with sqlite3.connect(store.DB_PATH) as db:
        db.row_factory = sqlite3.Row
        return db.execute(f"SELECT * FROM {table}").fetchone()


# ---------------------------------------------------------------- W4-02 rounding

def test_coordinates_are_rounded_to_three_decimals_when_saved():
    _, rec = _submit()
    got = store.get_record("alice", rec["id"])["data"]
    assert got["incident"]["departure"]["latitude"] == 15.457
    assert got["incident"]["departure"]["longitude"] == -36.123
    assert got["victim"]["current_location"] == {"latitude": 1.235, "longitude": 2.346}
    assert got["incident"]["destination"]["latitude"] is None
    assert store.verify_record(store.get_record("alice", rec["id"]))  # hash covers the rounded data


def test_rounding_ignores_missing_and_odd_data():
    assert store.round_coordinates({}) == {}
    assert store.round_coordinates({"incident": None, "victim": {"current_location": "x"}}) == {
        "incident": None, "victim": {"current_location": "x"}}


def test_the_caller_s_data_is_not_modified():
    original = {"incident": {"departure": {"latitude": 15.45678, "longitude": 1.0}}}
    store.round_coordinates(original)
    assert original["incident"]["departure"]["latitude"] == 15.45678


# ---------------------------------------------------------------- W4-01 encryption

def test_nothing_changes_without_a_key():
    _, rec = _submit()
    assert _raw()["narrative"] == "Secret narrative" and not secure.enabled()


def test_sensitive_columns_are_encrypted_and_read_back(monkeypatch):
    _enable(monkeypatch)
    topic, rec = _submit()
    row, trow = _raw(), _raw("topics")
    for value in (row["title"], row["narrative"], row["reason"], row["data"], trow["title"], trow["description"]):
        assert value.startswith(secure.PREFIX) and "Secret" not in value and "Sudan" not in value
    back = store.get_record("alice", rec["id"])
    assert (back["title"], back["narrative"], back["reason"]) == ("Secret title", "Secret narrative", "why")
    assert back["data"]["incident"]["departure"]["country"] == "Sudan"
    assert store.get_topic("alice", topic["id"])["title"] == "Secret topic"
    assert store.verify_record(back)


def test_ownership_still_applies_to_encrypted_rows(monkeypatch):
    _enable(monkeypatch)
    topic, rec = _submit("alice")
    assert store.get_record("bob", rec["id"]) is None and store.get_topics("bob") == []


def test_the_pipeline_receives_readable_data(monkeypatch):
    _enable(monkeypatch)
    seen = []
    monkeypatch.setattr(store, "run_pipeline", lambda df: seen.append(df.iloc[0]["data_record_narrative"]) or (df, "Success"))
    _submit()
    assert seen == ["Secret narrative"]


def test_old_plain_rows_stay_readable_and_can_be_migrated(monkeypatch):
    topic, rec = _submit()  # stored as plain text
    _enable(monkeypatch)
    assert store.get_record("alice", rec["id"])["narrative"] == "Secret narrative"
    assert store.encrypt_existing() == (1, 1)
    assert _raw()["narrative"].startswith(secure.PREFIX)
    back = store.get_record("alice", rec["id"])
    assert back["narrative"] == "Secret narrative" and store.verify_record(back)
    assert store.encrypt_existing() == (0, 0)  # nothing left to do


def test_migration_needs_a_key():
    _submit()
    with pytest.raises(secure.KeyMissingError):
        store.encrypt_existing()


def test_tampering_with_an_encrypted_value_is_detected(monkeypatch):
    _enable(monkeypatch)
    _, rec = _submit()
    with sqlite3.connect(store.DB_PATH) as db:
        db.execute("UPDATE records SET narrative = 'changed' WHERE id = ?", (rec["id"],))
    assert not store.verify_record(store.get_record("alice", rec["id"]))  # plain text where a token belongs
    with sqlite3.connect(store.DB_PATH) as db:
        token = db.execute("SELECT title FROM records").fetchone()[0]
        db.execute("UPDATE records SET narrative = ? WHERE id = ?", (token, rec["id"]))  # a valid token, wrong place
    assert not store.verify_record(store.get_record("alice", rec["id"]))
    with sqlite3.connect(store.DB_PATH) as db:
        db.execute("UPDATE records SET narrative = ? WHERE id = ?", (secure.PREFIX + "garbage", rec["id"]))
    back = store.get_record("alice", rec["id"])
    assert back["narrative"] == secure.UNREADABLE and not store.verify_record(back)


def test_wrong_key_and_missing_key_are_reported_clearly(monkeypatch):
    _enable(monkeypatch)
    _, rec = _submit()
    monkeypatch.setenv("SAFEVOICE_DB_KEY", Fernet.generate_key().decode())
    assert store.get_record("alice", rec["id"])["narrative"] == secure.UNREADABLE
    monkeypatch.delenv("SAFEVOICE_DB_KEY")
    with pytest.raises(secure.KeyMissingError):
        store.get_record("alice", rec["id"])
