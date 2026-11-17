"""Demo login tests (P2-1)."""
from ui import auth


def _users(monkeypatch, value):
    monkeypatch.setattr(auth, "load_dotenv", lambda: None)  # don't let the real .env interfere
    monkeypatch.setenv("SAFEVOICE_USERS", value)


def test_valid_login_and_case_insensitive_username(monkeypatch):
    _users(monkeypatch, f"alice:{auth.hash_password('s3cret')},bob:{auth.hash_password('other')}")
    assert auth.check_login("alice", "s3cret") == "alice"
    assert auth.check_login(" Bob ", "other") == "bob"


def test_wrong_password_unknown_user_and_empty_config(monkeypatch):
    _users(monkeypatch, f"alice:{auth.hash_password('s3cret')}")
    assert auth.check_login("alice", "wrong") is None
    assert auth.check_login("mallory", "s3cret") is None
    _users(monkeypatch, "")
    assert auth.check_login("alice", "s3cret") is None


def test_malformed_hash_is_rejected(monkeypatch):
    _users(monkeypatch, "alice:notahash")
    assert auth.check_login("alice", "x") is None
