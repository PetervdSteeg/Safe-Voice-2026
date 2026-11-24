"""The mapping layers stay in their lanes: the core file uses only terms from the HDS CDM, every term of our
own extension is declared, and no mapping uses an hds: term that does not exist (typos)."""
import re

import yaml
from rdflib import Graph, URIRef
from rdflib.namespace import DCTERMS, FOAF, PROV, RDF, RDFS

from src.transform import mapper

HDS = "https://vodan-development.github.io/HDS-Centralized-Common-Data-Model/hds-cdm.ttl#"
CDM_EXT = "https://w3id.org/dsip/cdm/"
SCHEMA = "http://schema.org/"

# Non-hds terms that the CDM itself uses (see config/hds/hds-cdm-shapes.ttl and the HDS diagram).
CDM_EXTERNAL = {str(t) for t in (
    RDF.type, RDFS.label, DCTERMS.description, DCTERMS.isPartOf, DCTERMS.Location, FOAF.name, PROV.Agent,
    URIRef(SCHEMA + "location"), URIRef(SCHEMA + "startDate"), URIRef(SCHEMA + "endDate"))}


def _expand(term, prefixes):
    if term == "a":
        return str(RDF.type)
    prefix, _, local = str(term).partition(":")
    return prefixes[prefix] + local if prefix in prefixes else str(term)


def _terms(path, prefixes):
    """Every predicate and every class used in one mapping file, as full IRIs."""
    mappings = yaml.safe_load(open(path, encoding="utf-8"))["mappings"]
    used = set()
    for cfg in mappings.values():
        for po in cfg["po"]:
            pred, obj = (po["p"], po["o"]) if isinstance(po, dict) else (po[0], po[1])
            used.add(_expand(pred, prefixes))
            if pred == "a":
                used.add(_expand(obj, prefixes))
    return used


def _prefixes():
    return mapper.load_mapping_config()[0]


def _declared(path):
    return {str(s) for s in Graph().parse(path, format="turtle").subjects() if isinstance(s, URIRef)}


def test_core_mapping_uses_only_terms_from_the_hds_cdm():
    declared = _declared("config/hds/hds-cdm.ttl")
    outside = {t for t in _terms("config/mapping_core.yml", _prefixes())
               if t not in CDM_EXTERNAL and t not in declared}
    assert outside == set(), f"terms in mapping_core.yml that the HDS CDM does not define: {sorted(outside)}"


def test_core_purity_check_catches_an_extra_term():
    prefixes = _prefixes()
    declared = _declared("config/hds/hds-cdm.ttl")
    assert _expand("cdm:age", prefixes) not in declared | CDM_EXTERNAL
    assert _expand("schema:nationality", prefixes) not in declared | CDM_EXTERNAL


def test_every_extension_term_is_declared():
    prefixes = _prefixes()
    declared = _declared("config/safevoice-extension.ttl")
    used = set()
    for path in ("config/mapping_core.yml", "config/mapping_application.yml"):
        used |= {t for t in _terms(path, prefixes) if t.startswith(CDM_EXT)}
    for path in ("config/mapping_core.yml", "config/mapping_application.yml"):
        text = open(path, encoding="utf-8").read()
        used |= {_expand(m, prefixes) for m in re.findall(r"\bcdm:\w+", text)}
    assert used and used <= declared, f"cdm: terms used but not declared: {sorted(used - declared)}"


def test_every_hds_term_in_the_mappings_exists_in_the_cdm():
    declared = _declared("config/hds/hds-cdm.ttl")
    for path in ("config/mapping_core.yml", "config/mapping_application.yml"):
        names = set(re.findall(r"\bhds:(\w+)", open(path, encoding="utf-8").read()))
        missing = {n for n in names if HDS + n not in declared}
        assert missing == set(), f"{path} uses hds: terms the CDM does not define: {sorted(missing)}"


def test_the_domain_tag_is_a_concept_of_the_cdm_scheme():
    g = Graph().parse("config/hds/hds-cdm.ttl", format="turtle")
    tag = URIRef(HDS + "humanTrafficking")
    assert (tag, RDF.type, URIRef("http://www.w3.org/2004/02/skos/core#Concept")) in g
    assert (tag, URIRef("http://www.w3.org/2004/02/skos/core#inScheme"), URIRef(HDS + "incidentDomainScheme")) in g


def test_old_incident_domain_file_is_gone():
    import os
    assert not os.path.exists("config/hds/incident-domains.ttl")
