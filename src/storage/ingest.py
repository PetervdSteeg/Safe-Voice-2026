# src/storage/ingest.py

import os
import re
from typing import Optional
from dotenv import load_dotenv, find_dotenv
from franz.openrdf.connect import ag_connect
from franz.openrdf.rio.rdfformat import RDFFormat

# Automatically locate the .env file in parent directories and load its variables
load_dotenv(find_dotenv())

# --- Server Configuration Constants ---
# Kept for backwards compatibility; the connection itself re-reads .env on every call
# (see _settings), so a corrected .env works without importing this module again.
AG_BASE_URL = os.getenv("AG_BASE_URL")
AG_REPO = os.getenv("AG_REPO")
AG_USER = os.getenv("AG_USER")
AG_PASSWORD = os.getenv("AG_PASSWORD")

# W3-03: each source's triples go into its own named graph, and the application account does not
# create repositories unless AG_CREATE_REPO=true is set (first-time setup only).
GRAPH_BASE = os.getenv("SAFEVOICE_GRAPH_BASE", "https://safevoice.example.org/graph/")
AG_CREATE_REPO = os.getenv("AG_CREATE_REPO", "false").strip().lower() in ("1", "true", "yes")
_SAFE_SOURCE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
REQUIRED_SETTINGS = ("AG_BASE_URL", "AG_REPO", "AG_USER", "AG_PASSWORD")

# Reason for the most recent failure. For the audit log and src.storage.check only: it holds no
# report content, and the app never shows it to users.
last_error = ""


def graph_for_source(source_id: str) -> str:
    """Named-graph IRI for one source. Raises ValueError for anything but a plain ID."""
    if not isinstance(source_id, str) or not _SAFE_SOURCE.fullmatch(source_id):
        raise ValueError(f"Unsafe source_id for a graph IRI: {source_id!r}")
    return GRAPH_BASE.rstrip("/") + "/" + source_id


def _load_env():
    load_dotenv(find_dotenv() or find_dotenv(usecwd=True))


def missing_settings():
    """Names of the AG_* settings that are not set in .env or the environment."""
    _load_env()
    return [name for name in REQUIRED_SETTINGS if not (os.getenv(name) or "").strip()]


def _host(url):
    """AllegroGraph wants a bare host name: drop a pasted https:// and any trailing slash."""
    return re.sub(r"^https?://", "", (url or "").strip()).rstrip("/")


def _settings():
    _load_env()
    return {
        "host": _host(os.getenv("AG_BASE_URL")),
        "port": int((os.getenv("AG_PORT") or "443").strip()),
        "repo": (os.getenv("AG_REPO") or "").strip(),
        "user": (os.getenv("AG_USER") or "").strip(),
        "password": os.getenv("AG_PASSWORD") or "",
        "create": os.getenv("AG_CREATE_REPO", str(AG_CREATE_REPO)).strip().lower() in ("1", "true", "yes"),
    }


def connect():
    """Open a connection to the AllegroGraph repository from the .env settings. Caller closes it."""
    s = _settings()
    return ag_connect(
        repo=s["repo"],
        host=s["host"],
        port=s["port"], # Default secure port for AllegroGraph
        protocol='https', # Force connection to use secure HTTPS protocol
        user=s["user"],
        password=s["password"],
        create=s["create"] # off by default (W3-03); set AG_CREATE_REPO=true to create a missing repository
    )


def ingest_rdf_file(file_path: str, source_id: str, context_uri: Optional[str] = None) -> bool:
    """
    Ingests an N-Triples (.nt) file directly into the AllegroGraph repository.
    """
    global last_error
    last_error = ""

    # 1. Validate File Existence
    if not os.path.exists(file_path):
        last_error = "RDF file not found"
        print(f"[INGEST] ERROR: File not found at {file_path}")
        return False

    missing = missing_settings()
    if missing:
        last_error = f"Missing in .env: {', '.join(missing)}"
        print(f"[INGEST] ERROR: {last_error}")
        return False

    if context_uri is None:
        try:
            context_uri = graph_for_source(source_id)
        except ValueError as e:
            last_error = "Unsafe source_id"
            print(f"[INGEST] ERROR: {e}")
            return False

    print(f"[INGEST] Connecting to AllegroGraph at {_settings()['host']}...")

    try:
        # 2. Connect directly to the Server and Repository
        conn = connect()

        print(f"[INGEST] Connection established. Uploading file: {file_path}")

        # 3. Ingest nt file using addFile
        conn.addFile(file_path, base=None, format=RDFFormat.NTRIPLES, context=conn.createURI(context_uri))
        total_triples = conn.size()
        print(f"[INGEST] SUCCESS: File loaded. Repository '{_settings()['repo']}' now contains {total_triples} triples.")

        return True

    except Exception as e:
        last_error = f"{type(e).__name__}: {e}"[:300]
        print(f"[INGEST] FAILURE: Data loading failed. Error: {e}")
        return False

    finally:
        # 4. Ensure connection is closed
        if 'conn' in locals() and conn:
            conn.close()
            # print("[INGEST] Connection closed.")