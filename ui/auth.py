"""Minimal demo login (P2-1). NOT production authentication.

Allowed users live in the SAFEVOICE_USERS variable in `.env`, as comma-separated
`username:hash` pairs. Passwords are never stored, only salted PBKDF2 hashes.

Create a hash with:  python -m ui.auth
"""

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from getpass import getpass

from dotenv import load_dotenv

ITERATIONS = 200_000
MIN_PASSWORD_LENGTH = 8


def hash_password(password, salt=None, iterations=ITERATIONS):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


# Hashed once at import. Unknown usernames are checked against it, so an unknown and a known
# username cost the same single PBKDF2 run and response time does not reveal which exist (W3-01).
DUMMY_HASH = hash_password("not-a-real-password")


def idle_minutes():
    """Minutes of inactivity before automatic logout (SAFEVOICE_IDLE_MINUTES, default 30)."""
    load_dotenv()
    try:
        return float(os.getenv("SAFEVOICE_IDLE_MINUTES", "30"))
    except ValueError:
        return 30.0


def idle_expired(last_seen, now):
    """True if more than idle_minutes() passed between two timestamps (seconds)."""
    return last_seen is not None and now - last_seen > idle_minutes() * 60


def _verify(password, stored):
    try:
        _, iterations, salt, _ = stored.split("$")
        expected = hash_password(password, salt, int(iterations))
    except ValueError:
        return False
    return hmac.compare_digest(expected, stored)


def _allowed_users():
    load_dotenv()
    users = {}
    for pair in os.getenv("SAFEVOICE_USERS", "").split(","):
        name, sep, stored = pair.strip().partition(":")
        name = name.strip().lower()
        # The username becomes source_id, which ends up in file names and IRIs (P2-3).
        if sep and re.fullmatch(r"[a-z0-9_-]{1,32}", name):
            users[name] = stored.strip()
    return users


def check_login(username, password):
    """Return the canonical username if the credentials are valid, else None."""
    name = username.strip().lower()
    stored = _allowed_users().get(name)
    # Verify even for unknown users so response time does not reveal which usernames exist.
    ok = _verify(password, stored or DUMMY_HASH)
    return name if stored and ok else None


# ---------------------------------------------------------------- brute-force protection
# Failed logins are counted per username in this process (all browser sessions share the count).
# After SAFEVOICE_MAX_ATTEMPTS failures within SAFEVOICE_LOCKOUT_MINUTES the username is locked
# until the oldest counted failure expires. Unknown usernames are counted too, so the lock
# message does not reveal which usernames exist. The counts are lost when the app restarts.

_failures = {}
_failures_lock = threading.Lock()
_MAX_TRACKED = 10_000


def _int_env(name, default):
    load_dotenv()
    try:
        return max(1, int(os.getenv(name, default)))
    except ValueError:
        return default


def max_attempts():
    return _int_env("SAFEVOICE_MAX_ATTEMPTS", 5)


def lockout_seconds():
    return _int_env("SAFEVOICE_LOCKOUT_MINUTES", 15) * 60


def _key(username):
    return username.strip().lower()[:32]


def _recent_failures(key, now, window):
    return sorted(t for t in _failures.get(key, []) if now - t < window)


def lockout_remaining(username, now=None):
    """Seconds until this username may try again (0 = not locked)."""
    now = time.time() if now is None else now
    window, limit = lockout_seconds(), max_attempts()
    with _failures_lock:
        recent = _recent_failures(_key(username), now, window)
    if len(recent) < limit:
        return 0
    return max(1, int(recent[-limit] + window - now))


def _record_failure(username, now, window):
    with _failures_lock:
        if len(_failures) >= _MAX_TRACKED:  # an attacker must not be able to grow this forever
            for k in [k for k in _failures if not _recent_failures(k, now, window)]:
                del _failures[k]
            if len(_failures) >= _MAX_TRACKED:
                _failures.clear()
        key = _key(username)
        _failures[key] = _recent_failures(key, now, window) + [now]


def attempt_login(username, password, now=None):
    """Check a login with lockout. Returns (username or None, status, seconds_to_wait).

    status is "ok", "invalid" or "locked". While locked the password is not even checked.
    """
    now = time.time() if now is None else now
    wait = lockout_remaining(username, now)
    if wait:
        return None, "locked", wait
    user = check_login(username, password)
    if user:
        with _failures_lock:
            _failures.pop(_key(username), None)
        return user, "ok", 0
    _record_failure(username, now, lockout_seconds())
    return None, "invalid", 0


def end_session(state, notice=None):
    """Forget everything held for the logged-in user: identity, half-typed forms, flash messages.

    `state` is st.session_state (or any dict). Clearing only the "user" key would leave one
    user's unsent narrative and form values in the session for whoever logs in next.
    """
    state.clear()
    if notice:
        state["notice"] = notice


if __name__ == "__main__":
    user = input("Username: ").strip().lower()
    password = getpass("Password: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if password != getpass("Repeat password: "):
        raise SystemExit("Passwords do not match.")
    print(f"\nAdd to SAFEVOICE_USERS in .env (separate several users with commas):\n{user}:{hash_password(password)}")
