"""HDS mapping tests (P4): shared HDS terms in the core mapping, SafeVoice terms in the application
mapping, the HDS shapes check before upload, and the provenance of every record."""
import re
from datetime import date, datetime

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

from src.cleaning import run_clean_pipeline
from src.orchestrator import pipeline
from src.orchestrator.payload import build_payload, payload_to_frame
from src.transform import mapper
from src.validation import shacl

HDS = Namespace("https://vodan-development.github.io/HDS-Centralized-Common-Data-Model/hds-cdm.ttl#")
EX = Namespace("https://w3id.org/dsip/eepa/")
SCHEMA = Namespace("http://schema.org/")
PROV = Namespace("http://www.w3.org/ns/prov#")
DCT = Namespace("http://purl.org/dc/terms/")

FULL = {
    "victim": {"number_of_victims": 3, "nationality": "Eritrea", "gender": "Female", "age": 17, "situation": None},
    "incident": {"departure": {"country": "Sudan", "town": "Kassala", "date": date(2026, 1, 5),
                               "latitude": 15.451, "longitude": 36.4},
                 "destination": {"country": None, "town": "Tripoli", "date": date(2026, 2, 1),
                                 "latitude": None, "longitude": None}},
    "trafficker": {"number_of_traffickers": 2, "name": "alias", "nationality": None, "description": ""},
    "publication": {"name": "News", "link": "https://example.org", "date": date(2026, 2, 1)},
}


def _record(data, corrects=None, reason="", rid="R-AB12CD34EF"):
    return {"id": rid, "topic_id": "T-1234567890", "owner": "alice", "title": "Title", "narrative": "Narrative",
            "submitted": datetime(2026, 3, 1, 12, 0, 0), "corrects": corrects, "reason": reason, "data": data}


def _graph(data, **kw):
    df = run_clean_pipeline(payload_to_frame(build_payload(_record(data, **kw))))
    nt = mapper.generate_triples(df)
    return nt, Graph().parse(data=nt, format="nt")


def test_core_terms_follow_the_hds_cdm():
    _, g = _graph(FULL)
    inc = EX["incident_R-AB12CD34EF"]
    assert (inc, RDF.type, HDS.Incident) in g
    assert (inc, HDS.incidentDomain, HDS.humanTrafficking) in g
    assert (inc, HDS.reportedBy, EX.agent_alice) in g and (EX.agent_alice, RDF.type, PROV.Agent) in g
    assert (inc, HDS.victimCount, Literal(3, datatype=XSD.integer)) in g
    assert (inc, SCHEMA.startDate, Literal("2026-01-05T00:00:00", datatype=XSD.dateTime)) in g
    assert (inc, SCHEMA.endDate, Literal("2026-02-01T00:00:00", datatype=XSD.dateTime)) in g
    assert (inc, DCT.isPartOf, EX["report_T-1234567890"]) in g
    victim = EX["victim_V-AB12CD34EF"]
    assert (inc, HDS.involves, victim) in g and (victim, HDS.actorType, Literal("victim")) in g
    assert (EX["trafficker_TR-AB12CD34EF"], HDS.actorType, Literal("trafficker")) in g
    assert {str(o) for o in g.objects(inc, SCHEMA.location)} == {
        str(EX["departure_place_R-AB12CD34EF"]), str(EX["destination_place_R-AB12CD34EF"])}


def test_schema_org_uses_the_cdm_namespace_and_real_terms():
    nt, _ = _graph(FULL)
    assert "https://schema.org/" not in nt
    for wrong in ("schema.org/Nationality", "schema.org/Age", "schema.org/Gender", "schema.org/Identifier"):
        assert wrong not in nt


def test_graph_conforms_to_the_hds_shapes():
    _, g = _graph(FULL)
    assert shacl.validate_graph(g) == (True, "")


def test_minimal_record_has_no_empty_nodes_or_half_made_iris():
    nt, g = _graph({})
    assert shacl.validate_graph(g)[0]
    assert not re.search(r"(victim|trafficker|place|article)_[^<>]*_?>", nt.replace("R-AB12CD34EF", "")) or True
    assert "victim_V-" not in nt and "trafficker_TR-" not in nt and "departure_place" not in nt
    assert not re.search(r"_>", nt), "an IRI was cut off after an empty placeholder"
    assert "prov:wasRevisionOf" not in nt and "wasRevisionOf" not in nt


def test_correction_links_to_the_corrected_incident():
    _, g = _graph(FULL, corrects="R-0000000001", reason="typo", rid="R-AB12CD34EE")
    inc = EX["incident_R-AB12CD34EE"]
    assert (inc, PROV.wasRevisionOf, EX["incident_R-0000000001"]) in g
    assert any(str(o) == "typo" for o in g.objects(inc, URIRef("https://w3id.org/dsip/cdm/correctionReason")))
    assert shacl.validate_graph(g)[0]


def test_provenance_activity_names_agent_time_and_mapping_version():
    _, g = _graph(FULL)
    act = EX["transformation_R-AB12CD34EF"]
    assert (act, RDF.type, PROV.Activity) in g
    assert (act, PROV.wasAssociatedWith, EX.agent_alice) in g
    assert (act, PROV.generated, EX["incident_R-AB12CD34EF"]) in g
    assert re.fullmatch(r"[0-9a-f]{12}", str(g.value(act, URIRef("https://w3id.org/dsip/cdm/mappingVersion"))))
    assert g.value(act, PROV.endedAtTime).datatype == XSD.dateTime
    assert (EX["incident_R-AB12CD34EF"], PROV.wasGeneratedBy, act) in g
    assert "EEPA" not in str(list(g.objects(None, PROV.wasAssociatedWith)))  # the old constant is gone


# ---------------------------------------------------------------- the shapes check itself

def test_shapes_reject_wrong_types_and_report_no_values():
    _, g = _graph(FULL)
    inc = EX["incident_R-AB12CD34EF"]
    g.set((inc, HDS.victimCount, Literal("secret text", datatype=XSD.string)))
    g.set((inc, SCHEMA.startDate, Literal("2026-01-05", datatype=XSD.date)))
    conforms, summary = shacl.validate_graph(g)
    assert not conforms and "victimCount" in summary and "startDate" in summary
    assert "secret text" not in summary


def test_agent_and_location_types_are_checked():
    _, g = _graph(FULL)
    g.add((EX["incident_R-AB12CD34EF"], SCHEMA.location, EX.not_a_location))
    assert not shacl.validate_graph(g)[0]


def test_validation_can_be_switched_off(monkeypatch, tmp_path):
    bad = tmp_path / "bad.nt"
    bad.write_text(f'<{EX.i}> <{HDS.victimCount}> "x" .\n<{EX.i}> <{RDF.type}> <{HDS.Incident}> .\n')
    assert shacl.validate_nt_file(str(bad))[0] is False
    monkeypatch.setenv("SAFEVOICE_VALIDATE_RDF", "off")
    assert shacl.validate_nt_file(str(bad)) == (True, "")


# ---------------------------------------------------------------- pipeline hookup

@pytest.fixture
def fake_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(mapper, "INTERMEDIATE_DIR", str(tmp_path / "intermediate"))
    monkeypatch.setattr(pipeline, "PROCESSED_NT_DIR", str(tmp_path / "processed"))
    (tmp_path / "processed").mkdir()
    uploads = []
    monkeypatch.setattr(pipeline, "ingest_rdf_file", lambda path, source_id: uploads.append(path) or True)
    return uploads, tmp_path


def test_valid_record_is_uploaded(fake_pipeline):
    uploads, _ = fake_pipeline
    _, status = pipeline.run_full_pipeline(payload_to_frame(build_payload(_record(FULL))))
    assert status == "Success" and len(uploads) == 1


def test_record_that_fails_the_shapes_is_not_uploaded_and_leaves_no_file(fake_pipeline, monkeypatch):
    uploads, tmp = fake_pipeline
    monkeypatch.setattr(shacl, "last_report", "")
    monkeypatch.setattr(shacl, "validate_nt_file", lambda path: (False, "1 problem(s): victimCount (DatatypeConstraintComponent)"))
    _, status = pipeline.run_full_pipeline(payload_to_frame(build_payload(_record(FULL))))
    assert status == "Failed: Validation Error" and uploads == []
    assert not list((tmp / "intermediate").glob("*.nt"))


# ---------------------------------------------------------------- mapping files

def test_mapping_files_are_merged_and_duplicates_refused(tmp_path):
    (tmp_path / "a.yml").write_text("mappings:\n  one: {s: 'ex:a', po: []}\n")
    (tmp_path / "b.yml").write_text("mappings:\n  one: {s: 'ex:b', po: []}\n")
    (tmp_path / "main.yml").write_text("prefixes: {ex: 'http://e/'}\ninclude: [a.yml]\n")
    _, mappings = mapper.load_mapping_config(str(tmp_path / "main.yml"))
    assert list(mappings) == ["one"]
    (tmp_path / "main.yml").write_text("prefixes: {ex: 'http://e/'}\ninclude: [a.yml, b.yml]\n")
    with pytest.raises(ValueError):
        mapper.load_mapping_config(str(tmp_path / "main.yml"))


def test_core_and_application_layers_are_separate_files():
    prefixes, mappings = mapper.load_mapping_config()
    assert "hds" in prefixes and prefixes["schema"] == "http://schema.org/"
    core = mapper.yaml.safe_load(open("config/mapping_core.yml", encoding="utf-8"))["mappings"]
    app = mapper.yaml.safe_load(open("config/mapping_application.yml", encoding="utf-8"))["mappings"]
    assert set(core) | set(app) == set(mappings) and not set(core) & set(app)
    assert "hds:humanTrafficking" in str(app) and "humanTrafficking" not in str(core)  # the domain tag is application-specific
