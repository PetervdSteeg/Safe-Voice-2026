"""Access-control hardening tests (W3-01, W3-02, W3-03, W3-05): login lockout, timing,
session clean-up, record-chain safety, audit log size, per-source graphs in AllegroGraph.

Self-contained: needs no AllegroGraph, no pipeline and no real .env.
"""
import json
import sqlite3

import pytest

from src.storage import ingest
from ui import audit, auth, store


# ---------------------------------------------------------------- shared setup

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "app" / "t.db"))
    monkeypatch.setattr(audit, "AUDIT_LOG", str(tmp_path / "audit" / "audit.log"))
    monkeypatch.setattr(store, "run_pipeline", lambda df: (df, "Success"))  # no pipeline needed here
    monkeypatch.setattr(auth, "load_dotenv", lambda: None)
    monkeypatch.setenv("SAFEVOICE_USERS", f"alice:{auth.hash_password('s3cret-pass')}")
    for var in ("SAFEVOICE_MAX_ATTEMPTS", "SAFEVOICE_LOCKOUT_MINUTES"):
        monkeypatch.delenv(var, raising=False)
    auth._failures.clear()
    yield
    auth._failures.clear()


# ---------------------------------------------------------------- W3-01 login

def test_unknown_and_known_users_cost_the_same_hashing_work(monkeypatch):
    calls = []
    real = auth.hash_password
    monkeypatch.setattr(auth, "hash_password", lambda *a, **k: calls.append(1) or real(*a, **k))
    auth.check_login("alice", "wrong")
    known = len(calls)
    calls.clear()
    auth.check_login("mallory", "wrong")
    assert known == len(calls) == 1


def test_lockout_after_repeated_failures_even_with_the_right_password():
    for i in range(5):
        assert auth.attempt_login("alice", "wrong", now=1000 + i)[1] == "invalid"
    user, status, wait = auth.attempt_login("alice", "s3cret-pass", now=1010)
    assert (user, status) == (None, "locked") and 0 < wait <= 15 * 60


def test_lockout_expires():
    for i in range(5):
        auth.attempt_login("alice", "wrong", now=1000 + i)
    assert auth.attempt_login("alice", "s3cret-pass", now=1000 + 15 * 60 + 10)[:2] == ("alice", "ok")


def test_success_resets_the_counter():
    for i in range(4):
        auth.attempt_login("alice", "wrong", now=1000 + i)
    assert auth.attempt_login("alice", "s3cret-pass", now=1010)[1] == "ok"
    for i in range(4):  # four more failures are still below the limit of five
        assert auth.attempt_login("alice", "wrong", now=1020 + i)[1] == "invalid"


def test_unknown_usernames_are_throttled_too_and_do_not_lock_others():
    for i in range(5):
        auth.attempt_login("mallory", "x", now=1000 + i)
    assert auth.attempt_login("mallory", "x", now=1010)[1] == "locked"  # same message as for a real user
    assert auth.attempt_login("alice", "s3cret-pass", now=1010)[1] == "ok"


def test_limits_can_be_configured(monkeypatch):
    monkeypatch.setenv("SAFEVOICE_MAX_ATTEMPTS", "2")
    auth.attempt_login("alice", "wrong", now=1000)
    auth.attempt_login("alice", "wrong", now=1001)
    assert auth.attempt_login("alice", "s3cret-pass", now=1002)[1] == "locked"


def test_failure_table_cannot_grow_without_limit(monkeypatch):
    monkeypatch.setattr(auth, "_MAX_TRACKED", 50)
    for i in range(120):
        auth.attempt_login(f"user{i}", "x", now=1000)
    assert len(auth._failures) <= 50


# ---------------------------------------------------------------- session clean-up

def test_end_session_removes_user_and_half_typed_form_data():
    state = {"user": "alice", "last_seen": 1.0, "rec_narrative": "private text", "flash": "x"}
    auth.end_session(state)
    assert state == {}


def test_end_session_can_leave_a_notice_for_the_login_page():
    state = {"user": "alice", "rec_narrative": "private text"}
    auth.end_session(state, "You were logged out.")
    assert state == {"notice": "You were logged out."}


# ---------------------------------------------------------------- W3-02 ownership edge cases

def _record(user="alice", **kw):
    topic = store.create_topic(user, "T", "")
    return topic, store.submit_record(user, topic["id"], "Title", "Narrative", {}, **kw)


def test_chain_survives_a_missing_corrected_record():
    _, rec = _record()
    with sqlite3.connect(store.DB_PATH) as db:
        db.execute("UPDATE records SET corrects = 'R-GONE' WHERE id = ?", (rec["id"],))
    assert [r["id"] for r in store.get_chain("alice", store.get_record("alice", rec["id"]))] == [rec["id"]]


def test_chain_survives_a_loop_in_the_links():
    topic, a = _record()
    b = store.submit_record("alice", topic["id"], "T2", "N2", {}, corrects=a["id"])
    with sqlite3.connect(store.DB_PATH) as db:
        db.execute("UPDATE records SET corrects = ? WHERE id = ?", (b["id"], a["id"]))
    ids = [r["id"] for r in store.get_chain("alice", store.get_record("alice", a["id"]))]
    assert sorted(ids) == sorted([a["id"], b["id"]])


def test_chain_never_includes_another_users_records():
    topic, a = _record("alice")
    with sqlite3.connect(store.DB_PATH) as db:  # a foreign row that claims to correct alice's record
        db.execute("INSERT INTO records VALUES ('R-EVIL', ?, 'bob', 't', 'n', '2026-01-01T00:00:00', ?, '', '{}', 'x', 'synced', '')",
                   (topic["id"], a["id"]))
    assert [r["id"] for r in store.get_chain("alice", a)] == [a["id"]]


# ---------------------------------------------------------------- W3-05 audit log

def test_audit_detail_is_truncated_and_stays_one_json_line():
    audit.log("alice", "access_denied", detail="topic=" + "x\n" * 500)
    lines = open(audit.AUDIT_LOG, encoding="utf-8").read().splitlines()
    assert len(lines) == 1 and len(json.loads(lines[0])["detail"]) <= 200


# ---------------------------------------------------------------- W3-03 AllegroGraph isolation

class _FakeConn:
    def __init__(self):
        self.added = []
        self.closed = False

    def createURI(self, iri):
        return ("URI", iri)

    def addFile(self, path, base=None, format=None, context=None):
        self.added.append(context)

    def size(self):
        return 1

    def close(self):
        self.closed = True


def _ag_env(monkeypatch, **overrides):
    """A complete, fake AllegroGraph configuration; the real .env must never leak into tests."""
    monkeypatch.setattr(ingest, "load_dotenv", lambda *a, **k: None)
    values = {"AG_BASE_URL": "https://ag.example.com/", "AG_REPO": "repo", "AG_USER": "u", "AG_PASSWORD": "pw",
              "AG_PORT": None, "AG_CREATE_REPO": None, **overrides}
    for name, value in values.items():
        monkeypatch.delenv(name, raising=False) if value is None else monkeypatch.setenv(name, value)


@pytest.fixture
def fake_ag(monkeypatch, tmp_path):
    _ag_env(monkeypatch)
    conn, seen = _FakeConn(), {}
    monkeypatch.setattr(ingest, "ag_connect", lambda **kw: seen.update(kw) or conn)
    nt = tmp_path / "x.nt"
    nt.write_text("<a> <b> <c> .\n")
    return conn, seen, str(nt)


def test_each_source_gets_its_own_named_graph(fake_ag):
    conn, _, nt = fake_ag
    assert ingest.ingest_rdf_file(nt, source_id="alice")
    assert ingest.ingest_rdf_file(nt, source_id="bob")
    assert conn.added == [("URI", ingest.graph_for_source("alice")), ("URI", ingest.graph_for_source("bob"))]
    assert ingest.graph_for_source("alice") != ingest.graph_for_source("bob")


@pytest.mark.parametrize("bad", ["../../x", "a/b", "", "a b", "x>y", None])
def test_unsafe_source_id_is_refused_before_connecting(fake_ag, bad):
    conn, seen, nt = fake_ag
    assert ingest.ingest_rdf_file(nt, source_id=bad) is False
    assert seen == {} and conn.added == []


def test_repository_is_not_created_unless_enabled(fake_ag, monkeypatch):
    _, seen, nt = fake_ag
    ingest.ingest_rdf_file(nt, source_id="alice")
    assert seen["create"] is False
    monkeypatch.setattr(ingest, "AG_CREATE_REPO", True)
    ingest.ingest_rdf_file(nt, source_id="alice")
    assert seen["create"] is True


def test_connection_is_closed_even_when_upload_fails(fake_ag, monkeypatch):
    conn, _, nt = fake_ag
    monkeypatch.setattr(conn, "addFile", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert ingest.ingest_rdf_file(nt, source_id="alice") is False and conn.closed


# ---------------------------------------------------------------- AllegroGraph connection settings

def test_host_is_normalised_and_settings_are_read_at_call_time(fake_ag, monkeypatch):
    _, seen, nt = fake_ag
    assert ingest.ingest_rdf_file(nt, source_id="alice")
    assert seen["host"] == "ag.example.com" and seen["port"] == 443 and seen["protocol"] == "https"
    monkeypatch.setenv("AG_REPO", "other_repo")  # .env corrected after the app started
    monkeypatch.setenv("AG_PORT", "10035")
    ingest.ingest_rdf_file(nt, source_id="alice")
    assert seen["repo"] == "other_repo" and seen["port"] == 10035


def test_missing_settings_are_named_and_no_connection_is_tried(fake_ag, monkeypatch):
    conn, seen, nt = fake_ag
    monkeypatch.delenv("AG_PASSWORD")
    assert ingest.missing_settings() == ["AG_PASSWORD"]
    assert ingest.ingest_rdf_file(nt, source_id="alice") is False
    assert "AG_PASSWORD" in ingest.last_error and seen == {}


def test_connection_error_is_kept_for_the_log_but_resets_on_success(fake_ag, monkeypatch):
    conn, seen, nt = fake_ag
    monkeypatch.setattr(ingest, "ag_connect", lambda **kw: (_ for _ in ()).throw(ConnectionError("no route to host")))
    assert ingest.ingest_rdf_file(nt, source_id="alice") is False
    assert "ConnectionError" in ingest.last_error and "no route" in ingest.last_error
    monkeypatch.setattr(ingest, "ag_connect", lambda **kw: conn)
    assert ingest.ingest_rdf_file(nt, source_id="alice") is True and ingest.last_error == ""


def test_audit_log_gets_the_reason_but_the_user_gets_a_plain_message(monkeypatch):
    monkeypatch.setattr(store, "run_pipeline", lambda df: (df, "Failed: Ingestion Error"))
    monkeypatch.setattr(ingest, "last_error", "ConnectionError: no route to host")
    _, rec = _record()
    assert rec["sync_status"] == store.NOT_SYNCED and "database" in rec["sync_message"]
    assert "no route to host" not in rec["sync_message"]
    log = open(audit.AUDIT_LOG, encoding="utf-8").read()
    assert "no route to host" in log and "Narrative" not in log


def test_missing_settings_give_a_specific_user_message(monkeypatch):
    monkeypatch.setattr(store, "run_pipeline", lambda df: (df, "Failed: Ingestion Error"))
    monkeypatch.setattr(ingest, "last_error", "Missing in .env: AG_PASSWORD")
    _, rec = _record()
    assert "settings" in rec["sync_message"] and "database" in rec["sync_message"]


def test_unexpected_error_is_logged_with_type_and_place_but_never_its_message(monkeypatch):
    def boom(df):
        raise RuntimeError("secret narrative text")
    monkeypatch.setattr(store, "run_pipeline", boom)
    _record()
    log = open(audit.AUDIT_LOG, encoding="utf-8").read()
    assert "RuntimeError at " in log and "secret narrative text" not in log


# ---------------------------------------------------------------- python -m src.storage.check

def test_check_script_reports_every_step(fake_ag, monkeypatch, capsys):
    from src.storage import check
    conn, _, _ = fake_ag
    removed = []
    monkeypatch.setattr(conn, "remove", lambda *a, **k: removed.append(k["contexts"]), raising=False)
    monkeypatch.setattr(check, "check_dry_run", lambda: True)  # needs the repo's config files
    assert check.main() == 0
    out = capsys.readouterr().out
    assert "[OK] 1." in out and "[OK] 3." in out and "[OK] 4." in out and "pw" not in out.replace("password", "")
    assert removed == [[("URI", ingest.graph_for_source("_check"))]]


def test_check_script_stops_at_missing_settings(fake_ag, monkeypatch, capsys):
    from src.storage import check
    monkeypatch.delenv("AG_REPO")
    monkeypatch.setattr(check, "check_dry_run", lambda: True)
    assert check.main() == 1
    out = capsys.readouterr().out
    assert "[FAILED] 1." in out and "AG_REPO" in out and "3." not in out


def test_check_script_names_the_failing_upload_step(fake_ag, monkeypatch, capsys):
    from src.storage import check
    conn, _, _ = fake_ag
    monkeypatch.setattr(conn, "addFile", lambda *a, **k: (_ for _ in ()).throw(PermissionError("no write access")))
    monkeypatch.setattr(check, "check_dry_run", lambda: True)
    assert check.main() == 1
    out = capsys.readouterr().out
    assert "[OK] 3." in out and "[FAILED] 4." in out and "no write access" in out
