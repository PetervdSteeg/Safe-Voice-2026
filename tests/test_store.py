"""Phase 2 and 3 tests: ownership, persistence, pipeline hookup, safe paths, audit, idle logout."""
import json
from datetime import date

import pytest

from src.orchestrator import pipeline
from src.transform import mapper
from ui import audit, auth, store

DATA = {
    "victim": {"number_of_victims": 3, "nationality": "Eritrea", "gender": None, "age": 17, "situation": None},
    "incident": {"departure": {"country": "Sudan", "town": "Kassala", "date": date(2026, 1, 5),
                               "latitude": 15.4512, "longitude": 36.4},
                 "destination": {"country": None, "town": "Tripoli", "date": None,
                                 "latitude": None, "longitude": None}},
    "trafficker": {"number_of_traffickers": 2, "name": "", "nationality": None, "description": ""},
    "publication": {"name": "News", "link": "https://example.org", "date": date(2026, 2, 1)},
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Temp database, audit log and RDF folders; the real pipeline runs but AllegroGraph is faked."""
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "app" / "t.db"))
    monkeypatch.setattr(audit, "AUDIT_LOG", str(tmp_path / "audit" / "audit.log"))
    monkeypatch.setattr(mapper, "INTERMEDIATE_DIR", str(tmp_path / "intermediate"))
    monkeypatch.setattr(pipeline, "PROCESSED_NT_DIR", str(tmp_path / "processed"))
    (tmp_path / "processed").mkdir()
    uploads = []
    monkeypatch.setattr(pipeline, "ingest_rdf_file", lambda path, source_id: uploads.append(open(path).read()) or True)
    return uploads


def _submit(user="alice", data=DATA, **kw):
    topic = store.create_topic(user, "Topic", "")
    return topic, store.submit_record(user, topic["id"], "Title", "Narrative text", data, **kw)


# ---------------------------------------------------------------- P2-2 ownership

def test_users_cannot_see_each_others_topics_or_records():
    topic, rec = _submit("alice")
    assert store.get_topic("alice", topic["id"]) and store.get_record("alice", rec["id"])
    assert store.get_topic("bob", topic["id"]) is None
    assert store.get_record("bob", rec["id"]) is None
    assert store.get_topics("bob") == [] and store.get_records("bob", topic["id"]) == []


def test_cannot_submit_into_or_correct_another_users_data():
    topic, rec = _submit("alice")
    with pytest.raises(PermissionError):
        store.submit_record("bob", topic["id"], "x", "y", DATA)
    with pytest.raises(PermissionError):
        store.retry_sync("bob", rec["id"])
    other_topic = store.create_topic("alice", "Other", "")
    with pytest.raises(PermissionError):  # correction must stay in the original's topic
        store.submit_record("alice", other_topic["id"], "x", "y", DATA, corrects=rec["id"])


# ---------------------------------------------------------------- P3-2 persistence

def test_data_round_trips_through_the_database_including_dates():
    topic, rec = _submit("alice")
    back = store.get_record("alice", rec["id"])
    assert back["data"] == DATA
    assert isinstance(back["data"]["incident"]["departure"]["date"], date)
    assert store.get_topics("alice")[0]["id"] == topic["id"]


def test_corrections_form_a_chain():
    topic, first = _submit("alice")
    second = store.submit_record("alice", topic["id"], "T2", "N2", DATA, corrects=first["id"], reason="typo")
    assert [r["id"] for r in store.get_chain("alice", second)] == [first["id"], second["id"]]


# ---------------------------------------------------------------- P3-3 / P3-4 pipeline

def test_submit_sends_the_record_through_the_pipeline(isolated):
    _, rec = _submit("alice")
    assert rec["sync_status"] == store.SYNCED
    nt = isolated[0]
    assert rec["id"] in nt and "Kassala" in nt and "Tripoli" in nt
    assert "<NA>" not in nt and "NaT" not in nt
    assert "2026-01-05" in nt


def test_failure_keeps_the_record_and_retry_succeeds(monkeypatch):
    monkeypatch.setattr(pipeline, "ingest_rdf_file", lambda path, source_id: False)
    _, rec = _submit("alice")
    assert rec["sync_status"] == store.NOT_SYNCED and "database" in rec["sync_message"]
    monkeypatch.setattr(pipeline, "ingest_rdf_file", lambda path, source_id: True)
    assert store.retry_sync("alice", rec["id"])["sync_status"] == store.SYNCED


def test_unexpected_error_is_not_raised_to_the_user(monkeypatch):
    def boom(df):
        raise RuntimeError("secret internals")
    monkeypatch.setattr(store, "run_pipeline", boom)
    _, rec = _submit("alice")
    assert rec["sync_status"] == store.NOT_SYNCED and "secret" not in rec["sync_message"]


def test_minimal_record_passes_and_ids_are_generated():
    topic = store.create_topic("alice", "T", "")
    rec = store.submit_record("alice", topic["id"], "Title", "Narrative", {})
    assert rec["sync_status"] == store.SYNCED
    from src.orchestrator.payload import build_payload
    p = build_payload(rec)["data"]
    assert p["victim"]["victim_id"].startswith("V-") and p["incident"]["incident_id"].startswith("I-")
    assert p["record"]["source_id"] == "alice"


# ---------------------------------------------------------------- P2-3 safe paths

@pytest.mark.parametrize("name", ["../../x.nt", "a/b.nt", "..\\x.nt", "x.nt\0", "a b.nt", "x.txt"])
def test_mapper_refuses_unsafe_filenames(name):
    import pandas as pd
    with pytest.raises(ValueError):
        mapper.save_triples_to_file(pd.DataFrame([{"a": 1}]), filename=name)


def test_pipeline_refuses_an_unsafe_source_id(isolated):
    topic = store.create_topic("alice", "T", "")
    rec = store.submit_record("alice", topic["id"], "T", "N", {})
    from src.orchestrator.payload import build_payload, payload_to_frame
    payload = build_payload(rec)
    payload["data"]["record"]["source_id"] = "../../evil"
    uploads_before = len(isolated)
    _, status = pipeline.run_full_pipeline(payload_to_frame(payload))
    assert status == "Failed: Invalid ID" and len(isolated) == uploads_before


def test_usernames_with_odd_characters_are_ignored(monkeypatch):
    monkeypatch.setattr(auth, "load_dotenv", lambda: None)
    monkeypatch.setenv("SAFEVOICE_USERS", f"../evil:{auth.hash_password('p')}")
    assert auth.check_login("../evil", "p") is None


# ---------------------------------------------------------------- P2-4 idle logout

def test_idle_expiry(monkeypatch):
    monkeypatch.setattr(auth, "load_dotenv", lambda: None)
    monkeypatch.setenv("SAFEVOICE_IDLE_MINUTES", "30")
    assert not auth.idle_expired(None, 1000)
    assert not auth.idle_expired(1000, 1000 + 29 * 60)
    assert auth.idle_expired(1000, 1000 + 31 * 60)


# ---------------------------------------------------------------- P2-5 audit and integrity

def test_audit_log_records_events_without_report_content(tmp_path):
    topic, rec = _submit("alice")
    lines = [json.loads(l) for l in open(audit.AUDIT_LOG, encoding="utf-8")]
    actions = [l["action"] for l in lines]
    assert {"topic_created", "record_submitted", "record_synced"} <= set(actions)
    assert all(l["user"] == "alice" for l in lines)
    assert "Narrative text" not in open(audit.AUDIT_LOG, encoding="utf-8").read()


def test_integrity_hash_detects_tampering():
    _, rec = _submit("alice")
    assert store.verify_record(store.get_record("alice", rec["id"]))
    import sqlite3
    with sqlite3.connect(store.DB_PATH) as db:
        db.execute("UPDATE records SET narrative = 'changed' WHERE id = ?", (rec["id"],))
    assert not store.verify_record(store.get_record("alice", rec["id"]))
