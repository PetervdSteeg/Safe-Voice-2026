"""Find out why records do not reach AllegroGraph. Run from the repository root:

    python -m src.storage.check

Four steps, each reported as OK or FAILED with the reason:
  1. the AG_* settings in .env (the password is never printed)
  2. a dry run of the pipeline on a synthetic record: payload -> cleaning -> RDF (no upload)
  3. a connection to the AllegroGraph repository
  4. a real upload of one synthetic triple through the same code the app uses, then its removal

Steps 1-2 failing means the problem is in the app or the configuration files, not in AllegroGraph.
Step 3 failing means the server, credentials or repository name. Step 4 failing means the upload itself.
Only synthetic data is used; the test triple goes into its own graph (<graph base>/_check).
"""
import os
import sys
import tempfile
from datetime import datetime

from src.storage import ingest

CHECK_SOURCE = "_check"
TEST_TRIPLE = ('<https://safevoice.example.org/check/subject> '
               '<https://safevoice.example.org/check/predicate> "connection test" .\n')


def _report(ok, name, detail=""):
    print(f"[{'OK' if ok else 'FAILED'}] {name}" + (f"\n       {detail}" if detail else ""))
    return ok


def check_settings():
    s, missing = ingest._settings(), ingest.missing_settings()
    shown = (f"host={s['host'] or '-'}  port={s['port']}  repo={s['repo'] or '-'}  user={s['user'] or '-'}  "
             f"password={'set (' + str(len(s['password'])) + ' characters)' if s['password'] else 'MISSING'}  "
             f"create_repo={s['create']}")
    if missing:
        return _report(False, "1. settings in .env", f"missing: {', '.join(missing)}\n       {shown}")
    return _report(True, "1. settings in .env", shown)


def check_dry_run():
    try:
        from src.cleaning import run_clean_pipeline
        from src.orchestrator.payload import build_payload, payload_to_frame
        from src.transform import mapper
        record = {"id": "R-CHECK00001", "topic_id": "T-CHECK", "owner": CHECK_SOURCE, "title": "Connection check",
                  "narrative": "Synthetic record made by src.storage.check", "submitted": datetime.now(),
                  "corrects": None, "reason": "", "data": {}}
        cleaned = run_clean_pipeline(payload_to_frame(build_payload(record)))
        if cleaned.empty:
            return _report(False, "2. pipeline dry run (clean + RDF, no upload)",
                           "the cleaner rejected the synthetic record; see the [CLEANER] lines above")
        triples = mapper.generate_triples(cleaned)
        if not triples:
            return _report(False, "2. pipeline dry run (clean + RDF, no upload)", "no triples were generated")
        from rdflib import Graph
        from src.validation import shacl
        conforms, problems = shacl.validate_graph(Graph().parse(data=triples, format="nt"))
        if not conforms:
            return _report(False, "2. pipeline dry run (clean + RDF, no upload)", f"the graph does not conform to the HDS shapes: {problems}")
        return _report(True, "2. pipeline dry run (clean + RDF, no upload)",
                       f"{len(triples.splitlines())} triples generated, conform to the HDS shapes")
    except Exception as exc:  # noqa: BLE001
        return _report(False, "2. pipeline dry run (clean + RDF, no upload)", f"{type(exc).__name__}: {exc}")


def check_connection():
    try:
        conn = ingest.connect()
    except Exception as exc:  # noqa: BLE001
        return None, _report(False, "3. connection to AllegroGraph", f"{type(exc).__name__}: {exc}")
    try:
        size = conn.size()
    except Exception as exc:  # noqa: BLE001
        conn.close()
        return None, _report(False, "3. connection to AllegroGraph", f"connected, but reading failed: {type(exc).__name__}: {exc}")
    _report(True, "3. connection to AllegroGraph", f"repository '{ingest._settings()['repo']}' has {size} triples")
    return conn, True


def check_upload(conn):
    graph = ingest.graph_for_source(CHECK_SOURCE)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "check.nt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(TEST_TRIPLE)
        ok = ingest.ingest_rdf_file(path, source_id=CHECK_SOURCE)
    if not ok:
        return _report(False, "4. upload of a test triple", ingest.last_error or "see the [INGEST] lines above")
    try:  # best-effort clean-up of the test graph
        ctx = conn.createURI(graph)
        conn.remove(None, None, None, contexts=[ctx])
        cleaned = "test triple removed again"
    except Exception as exc:  # noqa: BLE001
        cleaned = f"could not remove it ({type(exc).__name__}); delete graph <{graph}> by hand"
    return _report(True, "4. upload of a test triple", f"written to graph <{graph}>; {cleaned}")


def main():
    results = [check_settings(), check_dry_run()]
    conn = None
    if results[0]:
        conn, ok = check_connection()
        results.append(ok)
        if conn is not None:
            try:
                results.append(check_upload(conn))
            finally:
                conn.close()
    print("\nAll checks passed." if all(results) and len(results) == 4 else "\nSome checks failed: fix the first FAILED step.")
    return 0 if all(results) and len(results) == 4 else 1


if __name__ == "__main__":
    sys.exit(main())
