"""Check a generated N-Triples file against the shared HDS shapes before it is uploaded (W2-02).

The shapes come from the HDS Common Data Model (config/hds/hds-cdm-shapes.ttl), plus our own
extension shapes (config/safevoice-extension-shapes.ttl). As the HDS README describes, the data graph
also gets hds-cdm.ttl, so class hierarchy, concept type and scheme membership checks can work.

SAFEVOICE_VALIDATE_RDF=off skips the check (development only).
"""
import functools
import os

HDS_DIR = os.path.join("config", "hds")
# hds-cdm.ttl now holds the incident-domain concepts too (there is no separate incident-domains.ttl).
ONTOLOGY_FILES = ("hds-cdm.ttl",)
SHAPES_FILE = "hds-cdm-shapes.ttl"
# SafeVoice's own extension terms (declared in config/safevoice-extension.ttl) have their own shapes.
EXTENSION_SHAPES = os.path.join("config", "safevoice-extension-shapes.ttl")

# Summary of the last failed check: which properties and constraints, never the values (which can
# be report content). For the audit log; the app does not show it to users.
last_report = ""


def enabled():
    return os.getenv("SAFEVOICE_VALIDATE_RDF", "on").strip().lower() not in ("off", "0", "false", "no")


@functools.lru_cache(maxsize=1)
def _static_graphs():
    from rdflib import Graph
    ontology = Graph()
    for name in ONTOLOGY_FILES:
        ontology.parse(os.path.join(HDS_DIR, name), format="turtle")
    shapes = Graph().parse(os.path.join(HDS_DIR, SHAPES_FILE), format="turtle")
    if os.path.exists(EXTENSION_SHAPES):
        shapes.parse(EXTENSION_SHAPES, format="turtle")
    return ontology, shapes


def _short(term):
    text = str(term)
    return text.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _summary(report_graph):
    from rdflib.namespace import RDF, SH
    found = set()
    for result in report_graph.subjects(RDF.type, SH.ValidationResult):
        path = report_graph.value(result, SH.resultPath)
        component = report_graph.value(result, SH.sourceConstraintComponent)
        found.add(f"{_short(path) if path else '?'} ({_short(component) if component else '?'})")
    return (f"{len(found)} problem(s): " + "; ".join(sorted(found)))[:300]


def validate_graph(data):
    """Validate an rdflib Graph. Returns (conforms, summary)."""
    global last_report
    last_report = ""
    try:
        from pyshacl import validate
    except ImportError:
        last_report = "pyshacl is not installed (pip install pyshacl)"
        return False, last_report
    ontology, shapes = _static_graphs()
    checked = data + ontology
    conforms, report_graph, _ = validate(checked, shacl_graph=shapes, inference="none")
    if not conforms:
        last_report = _summary(report_graph)
    return bool(conforms), last_report


def validate_nt_file(path):
    """Validate an .nt file. Returns (conforms, summary). Always (True, "") when switched off."""
    if not enabled():
        return True, ""
    from rdflib import Graph
    return validate_graph(Graph().parse(path, format="nt"))
