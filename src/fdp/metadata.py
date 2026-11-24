"""Draft FAIR Data Point metadata for the SafeVoice data (W2-04). Run from the repository root:

    python -m src.fdp.metadata                 writes data/fdp/safevoice-metadata.ttl

One catalogue for SafeVoice and one dcat:Dataset per user graph, each with a distribution that points at
the AllegroGraph repository. The graph is checked against the HDS shapes (catalogue, dataset, publisher,
licence). This only PREPARES the metadata: registering it needs the endpoint and profile of the FDP
that your professor's team points you to. Settings in .env (all optional):

    SAFEVOICE_PUBLISHER      name of the publishing organisation (default "SafeVoice field lab")
    SAFEVOICE_LICENSE        IRI of the licence or rights statement (default: none; a legal decision)
    SAFEVOICE_METADATA_LANG  language of titles and descriptions (default en)

It describes the datasets, never their content.
"""
import os
import sys
from datetime import datetime, timezone

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, FOAF, PROV, RDF, RDFS, XSD

from src.storage import ingest
from src.validation import shacl

DCAT = Namespace("http://www.w3.org/ns/dcat#")
EX = Namespace("https://w3id.org/dsip/eepa/")
CDM_IRI = URIRef("https://vodan-development.github.io/HDS-Centralized-Common-Data-Model/hds-cdm.ttl")
OUT = os.path.join("data", "fdp", "safevoice-metadata.ttl")


def build_metadata(users, publisher=None, license_iri=None, language=None, endpoint=None, now=None):
    """RDF graph with one catalogue and one dataset (plus distribution) per user."""
    publisher = publisher or os.getenv("SAFEVOICE_PUBLISHER", "SafeVoice field lab")
    license_iri = license_iri if license_iri is not None else os.getenv("SAFEVOICE_LICENSE", "")
    language = language or os.getenv("SAFEVOICE_METADATA_LANG", "en")
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if endpoint is None:
        s = ingest._settings()
        endpoint = f"https://{s['host']}/repositories/{s['repo']}" if s["host"] and s["repo"] else ""

    g = Graph()
    for prefix, ns in (("dcat", DCAT), ("dcterms", DCTERMS), ("prov", PROV), ("foaf", FOAF), ("ex", EX)):
        g.bind(prefix, ns)
    agent, catalog = EX.agent_publisher, EX.catalog_safevoice
    g.add((agent, RDF.type, PROV.Agent))
    g.add((agent, FOAF.name, Literal(publisher)))
    g.add((catalog, RDF.type, DCAT.Catalog))
    g.add((catalog, DCTERMS.title, Literal("SafeVoice catalogue", lang=language)))
    g.add((catalog, DCTERMS.description, Literal("Human-trafficking source reports collected with SafeVoice.", lang=language)))
    g.add((catalog, DCTERMS.publisher, agent))
    g.add((catalog, DCTERMS.conformsTo, CDM_IRI))
    g.add((catalog, PROV.generatedAtTime, Literal(now, datatype=XSD.dateTime)))
    if license_iri:
        g.add((URIRef(license_iri), RDF.type, DCTERMS.RightsStatement))
        g.add((catalog, DCTERMS.license, URIRef(license_iri)))
    for user in sorted(users):
        graph_iri = ingest.graph_for_source(user)
        dataset, dist = EX[f"dataset_{user}"], EX[f"distribution_{user}"]
        g.add((dataset, RDF.type, DCAT.Dataset))
        g.add((dataset, DCTERMS.identifier, Literal(f"safevoice-{user}")))
        g.add((dataset, DCTERMS.title, Literal(f"SafeVoice records of {user}", lang=language)))
        g.add((dataset, DCTERMS.description, Literal(
            f"Incidents reported by {user}, as RDF in the named graph {graph_iri}.", lang=language)))
        g.add((dataset, DCTERMS.isPartOf, catalog))
        g.add((dataset, DCTERMS.publisher, agent))
        g.add((dataset, DCTERMS.conformsTo, CDM_IRI))
        g.add((dataset, DCAT.version, Literal("1.0")))
        g.add((dataset, PROV.generatedAtTime, Literal(now, datatype=XSD.dateTime)))
        g.add((dataset, DCAT.distribution, dist))
        if license_iri:
            g.add((dataset, DCTERMS.license, URIRef(license_iri)))
        g.add((dist, RDF.type, DCAT.Distribution))
        g.add((dist, DCTERMS.title, Literal("SPARQL access to the AllegroGraph repository", lang=language)))
        g.add((dist, DCTERMS.description, Literal(f"Named graph {graph_iri}.", lang=language)))
        if endpoint:
            g.add((dist, DCAT.accessURL, URIRef(endpoint)))
    return g


def main(argv=None):
    from ui import auth
    users = list(auth._allowed_users())
    if not users:
        print("No users in SAFEVOICE_USERS: nothing to describe.")
        return 1
    g = build_metadata(users)
    conforms, problems = shacl.validate_graph(g)
    if not conforms:
        print("The metadata does not conform to the HDS shapes:", problems)
        return 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    g.serialize(OUT, format="turtle")
    print(f"Wrote {OUT}: 1 catalogue, {len(users)} dataset(s). It conforms to the HDS shapes.")
    if not os.getenv("SAFEVOICE_LICENSE"):
        print("Note: no SAFEVOICE_LICENSE set, so no licence is stated. Agree the licence or rights statement first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
