"""Clean-up, resend, mock data and FDP metadata tools. All use the real mapping and the real HDS shapes;
only AllegroGraph is faked."""
import pytest
from rdflib import Graph
from rdflib.namespace import DCTERMS, RDF

from src.fdp import metadata
from src.orchestrator import pipeline
from src.storage import admin, ingest
from src.transform import mapper
from src.validation import shacl
from ui import audit, auth, mockdata, resync, store


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "app" / "t.db"))
    monkeypatch.setattr(audit, "AUDIT_LOG", str(tmp_path / "audit" / "audit.log"))
    monkeypatch.setattr(mapper, "INTERMEDIATE_DIR", str(tmp_path / "intermediate"))
    monkeypatch.setattr(pipeline, "PROCESSED_NT_DIR", str(tmp_path / "processed"))
    (tmp_path / "processed").mkdir()
    uploads = []
    monkeypatch.setattr(pipeline, "ingest_rdf_file", lambda path, source_id: uploads.append((source_id, open(path).read())) or True)
    return uploads


# ---------------------------------------------------------------- mock data

def test_mock_records_pass_the_whole_pipeline_including_the_hds_shapes(isolated):
    stored = mockdata.generate("alice", records=12)
    assert len(stored) == 12 and all(r["sync_status"] == store.SYNCED for r in stored)
    assert len(isolated) == 12 and all(source == "alice" for source, _ in isolated)
    assert all(r["title"].startswith("[MOCK]") and "not based on a real case" in r["narrative"] for r in stored)
    assert any(r["corrects"] for r in stored)  # some corrections are included
    assert any(not r["data"].get("incident") for r in stored)  # some records are minimal


def test_mock_data_is_repeatable_and_belongs_to_one_user():
    a = [r["data"] for r in mockdata.generate("alice", 6, seed=3)]
    b = [r["data"] for r in mockdata.generate("bob", 6, seed=3)]
    assert a == b and store.get_topics("alice") and len(store.get_topics("bob")) == 2
    assert all(t["owner"] == "alice" for t in store.get_topics("alice"))


def test_mock_data_can_be_created_without_uploading(isolated):
    stored = mockdata.generate("alice", records=4, upload=False)
    assert isolated == [] and all(r["sync_status"] == store.NOT_SYNCED for r in stored)
    store.resync_all("alice")
    assert len(isolated) == 4


# ---------------------------------------------------------------- resend

def test_resync_sends_everything_again_or_only_what_is_missing(isolated, monkeypatch):
    mockdata.generate("alice", records=3)
    mockdata.generate("bob", records=2)
    isolated.clear()
    assert store.resync_all() == (5, 0) and len(isolated) == 5
    isolated.clear()
    assert store.resync_all("bob") == (2, 0) and {s for s, _ in isolated} == {"bob"}
    isolated.clear()
    assert store.resync_all(only_unsynced=True) == (0, 0) and isolated == []


def test_resync_reports_failures(isolated, monkeypatch):
    mockdata.generate("alice", records=2)
    monkeypatch.setattr(pipeline, "ingest_rdf_file", lambda path, source_id: False)
    assert store.resync_all() == (0, 2)
    monkeypatch.setattr(pipeline, "ingest_rdf_file", lambda path, source_id: True)
    assert store.resync_all(only_unsynced=True) == (2, 0)


def test_resync_command_line(isolated, capsys):
    mockdata.generate("alice", records=2)
    assert resync.main(["--user", "alice"]) == 0
    assert "2 in the database" in capsys.readouterr().out


# ---------------------------------------------------------------- AllegroGraph admin

class _Conn:
    def __init__(self):
        self.removed, self.closed = [], False

    def createURI(self, iri):
        return ("URI", iri)

    def getContextIDs(self):
        return ["<https://x/graph/bob>", "<https://x/graph/alice>"]

    def size(self, ctx):
        if ctx == "<https://x/graph/bob>":
            raise RuntimeError("no size")
        return 7

    def remove(self, s, p, o, contexts=None):
        self.removed.append(contexts)

    def close(self):
        self.closed = True


def test_graphs_are_listed_even_when_a_size_is_unavailable():
    assert admin.list_graphs(_Conn()) == [("https://x/graph/alice", 7), ("https://x/graph/bob", None)]


def test_only_the_named_users_graph_is_dropped():
    conn = _Conn()
    graph = admin.drop_user_graph(conn, "alice")
    assert conn.removed == [[("URI", ingest.graph_for_source("alice"))]] and graph.endswith("/alice")


@pytest.mark.parametrize("bad", ["../x", "a b", "", "*", "x>y"])
def test_drop_refuses_anything_but_a_plain_user_name(bad):
    conn = _Conn()
    with pytest.raises(ValueError):
        admin.drop_user_graph(conn, bad)
    assert conn.removed == []


def test_drop_command_asks_for_the_name_and_cancels_otherwise(monkeypatch, capsys):
    conn = _Conn()
    monkeypatch.setattr(ingest, "missing_settings", lambda: [])
    monkeypatch.setattr(ingest, "connect", lambda: conn)
    monkeypatch.setattr("builtins.input", lambda prompt: "wrong")
    assert admin.main(["drop-user", "alice"]) == 1 and conn.removed == [] and conn.closed
    monkeypatch.setattr("builtins.input", lambda prompt: "alice")
    assert admin.main(["drop-user", "alice"]) == 0 and len(conn.removed) == 1


# ---------------------------------------------------------------- FDP metadata

def test_fdp_metadata_conforms_to_the_hds_shapes():
    g = metadata.build_metadata(["alice", "bob"], publisher="Test lab", license_iri="https://example.org/rights/restricted",
                                endpoint="https://ag.example.com/repositories/R", now="2026-11-25T10:00:00Z")
    assert shacl.validate_graph(g) == (True, "")
    assert len(list(g.subjects(RDF.type, metadata.DCAT.Dataset))) == 2
    assert len(list(g.subjects(RDF.type, metadata.DCAT.Catalog))) == 1
    assert (metadata.EX.catalog_safevoice, DCTERMS.publisher, metadata.EX.agent_publisher) in g


def test_fdp_metadata_works_without_licence_and_endpoint_and_never_contains_content():
    g = metadata.build_metadata(["alice"], license_iri="", endpoint="", now="2026-11-25T10:00:00Z")
    assert shacl.validate_graph(g)[0] and not list(g.objects(None, DCTERMS.license))
    text = g.serialize(format="turtle")
    assert "narrative" not in text.lower() and "password" not in text.lower()


def test_fdp_metadata_rejects_an_unsafe_user_name():
    with pytest.raises(ValueError):
        metadata.build_metadata(["../evil"])


def test_fdp_metadata_with_a_licence_that_is_not_a_rights_statement_is_caught():
    g = metadata.build_metadata(["alice"], license_iri="https://example.org/rights/x", endpoint="")
    from rdflib import URIRef
    g.remove((URIRef("https://example.org/rights/x"), RDF.type, DCTERMS.RightsStatement))
    assert not shacl.validate_graph(g)[0]
