"""Look at and clean up the AllegroGraph repository. Run from the repository root:

    python -m src.storage.admin graphs               list the graphs and their sizes
    python -m src.storage.admin drop-user NAME       delete one user's graph (asks you to type the name)

Each SafeVoice user's triples live in their own named graph (see ingest.graph_for_source), so one
user's data can be removed without touching anyone else's. After a CDM or mapping change: drop the
user's graph, then `python -m ui.resync --user NAME` to send the records again.

Triples uploaded by the very first version of the pipeline (before one graph per user) are in the
default graph and are NOT touched here: the repository may be shared with other field labs.
"""
import sys

from src.storage import ingest


def list_graphs(conn):
    """[(graph IRI, number of triples or None)] for every named graph."""
    rows = []
    for ctx in conn.getContextIDs():
        try:
            size = conn.size(ctx)
        except Exception:  # noqa: BLE001
            size = None
        rows.append((str(ctx).strip("<>"), size))
    return sorted(rows)


def drop_user_graph(conn, username):
    """Delete the graph of one user. Raises ValueError for anything but a plain user name."""
    graph = ingest.graph_for_source(username)
    conn.remove(None, None, None, contexts=[conn.createURI(graph)])
    return graph


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("graphs", "drop-user"):
        print(__doc__)
        return 2
    missing = ingest.missing_settings()
    if missing:
        print("Missing in .env:", ", ".join(missing))
        return 1
    conn = ingest.connect()
    try:
        if argv[0] == "graphs":
            for graph, size in list_graphs(conn):
                print(f"{size if size is not None else '?':>8}  {graph}")
            return 0
        if len(argv) < 2:
            print("Usage: python -m src.storage.admin drop-user NAME")
            return 2
        name = argv[1]
        graph = ingest.graph_for_source(name)
        if input(f"This deletes ALL triples in <{graph}>. Type the user name to confirm: ").strip() != name:
            print("Cancelled.")
            return 1
        drop_user_graph(conn, name)
        print(f"Deleted graph <{graph}>.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
