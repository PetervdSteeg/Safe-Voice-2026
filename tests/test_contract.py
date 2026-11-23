"""Data-contract tests (P1-6).

The same field is named in four places: the form, the CDM, the YAML mapping and the cleaner.
`config/field_crosswalk.csv` is the single list of fields. These tests fail when any one place is
renamed, added or removed without the others, which used to make data disappear silently.
"""
import re
from datetime import date, timedelta

import pandas as pd
import yaml

from src.cleaning import cleaner
from src.transform import mapper

CROSSWALK = "config/field_crosswalk.csv"
YAML_PATH = "config/yml_mapping.yml"
NO_COLUMN = "(none)"            # crosswalk rows that stand for a decision, not a column
UNUSED_LEVEL = "updates_"       # CDM 'Updates' block: undecided, see crosswalk


# --------------------------------------------------------------------------- loaders

def load_crosswalk():
    df = pd.read_csv(CROSSWALK, encoding="utf-8-sig", keep_default_na=False, dtype=str)
    return df[df["flat_column"] != NO_COLUMN]


def yaml_placeholders(path=YAML_PATH):
    _, mappings = mapper.load_mapping_config(path)  # core + application files, merged
    found = set()
    for mapping in mappings.values():
        found.update(re.findall(r"\$\((\w+)\)", mapping["s"]))
        for po in mapping["po"]:
            obj = po["o"] if isinstance(po, dict) else po[1]
            found.update(re.findall(r"\$\((\w+)\)", str(obj)))
    return found


# --------------------------------------------------------------------------- the checks
# Each returns a list of problems, so the same logic can be shown to catch a deliberate break.

def check_crosswalk_vs_cdm(crosswalk_cols, cdm_types):
    problems = [f"crosswalk column not in CDM: {c}" for c in crosswalk_cols if c not in cdm_types]
    problems += [f"CDM field not in crosswalk: {c}" for c in cdm_types
                 if c not in crosswalk_cols and not c.startswith(UNUSED_LEVEL)]
    problems += [f"CDM type unknown for {c}" for c, t in cdm_types.items() if t is None]
    return problems


def check_crosswalk_vs_yaml(mapped_cols, placeholders):
    problems = [f"mapped field not read by the YAML: {c}" for c in mapped_cols if c not in placeholders]
    problems += [f"YAML reads a column that does not exist: {p}" for p in placeholders
                 if p not in mapped_cols and p not in UNMAPPED_BUT_ALLOWED]
    return problems


# Columns the YAML may read even though the crosswalk marks them deferred (none today).
# Added by the mapper itself (provenance), not form fields.
UNMAPPED_BUT_ALLOWED = {"meta_generated_at", "meta_mapping_version"}


# --------------------------------------------------------------------------- tests

def test_crosswalk_matches_cdm():
    cdm_types = cleaner.create_cdm_column_map(cleaner.CDM_FILE_PATH)
    cols = set(load_crosswalk()["flat_column"])
    assert check_crosswalk_vs_cdm(cols, cdm_types) == []


def test_crosswalk_matches_yaml():
    cw = load_crosswalk()
    mapped = set(cw.loc[cw["rdf_scope"] == "mapped", "flat_column"])
    assert check_crosswalk_vs_yaml(mapped, yaml_placeholders()) == []


def test_required_fields_exist_in_crosswalk():
    required = set(cleaner.create_required_columns(cleaner.CDM_FILE_PATH))
    assert required <= set(load_crosswalk()["flat_column"])


def _sample_row():
    """One value per crosswalk column, shaped by its CDM type, each unique so it can be traced."""
    types = cleaner.create_cdm_column_map(cleaner.CDM_FILE_PATH)
    row, marker = {}, {}
    for i, col in enumerate(load_crosswalk()["flat_column"]):
        t = types[col]
        if t == "INT":
            value = str(1000 + i); marker[col] = value
        elif t == "FLOAT":
            value = f"{10 + i / 1000:.3f}"; marker[col] = value
        elif t == "DATE":
            d = date(2026, 1, 1) + timedelta(days=i); value = d.isoformat(); marker[col] = value
        elif t == "BOOL":
            value = "true"; marker[col] = None
        else:
            value = f"zz{i:03d}zz"; marker[col] = value
        row[col] = value
    return pd.DataFrame([row]), marker


def test_every_cdm_type_converts():
    df, _ = _sample_row()
    types = cleaner.create_cdm_column_map(cleaner.CDM_FILE_PATH)
    out = cleaner.run_clean_pipeline(df)
    assert len(out) == 1, "sample record was rejected by the cleaner"
    for col, t in types.items():
        if col not in out.columns:
            continue
        assert out[col].notna().all(), f"{col} ({t}) failed to convert and became missing"
        if t == "INT":
            assert str(out[col].dtype) == "Int64", col
        elif t == "FLOAT":
            assert out[col].dtype == "float64", col
        elif t == "DATE":
            assert pd.api.types.is_datetime64_any_dtype(out[col]), col


def test_every_mapped_field_reaches_the_triples():
    """Full path: flattened record -> cleaner -> RDF. Each mapped value must appear in the output."""
    df, marker = _sample_row()
    out = cleaner.run_clean_pipeline(df)
    triples = mapper.generate_triples(out)
    cw = load_crosswalk()
    missing = [c for c in cw.loc[cw["rdf_scope"] == "mapped", "flat_column"]
               if marker[c] is not None and marker[c] not in triples]
    assert missing == [], f"these fields never reach the RDF: {missing}"


def test_missing_values_are_not_written_as_text():
    """An empty optional field must not become the literal text '<NA>' or 'NaT' in the graph."""
    df, _ = _sample_row()
    df["data_victim_age"] = None
    df["data_record_date_received"] = None
    triples = mapper.generate_triples(cleaner.run_clean_pipeline(df))
    assert "<NA>" not in triples and "NaT" not in triples


# --------------------------------------------------------------------------- the guard itself

def test_checks_catch_a_one_sided_rename():
    """Rename a field in only one place and the checks must complain."""
    cdm_types = cleaner.create_cdm_column_map(cleaner.CDM_FILE_PATH)
    cols = set(load_crosswalk()["flat_column"])

    renamed_in_cdm = {("data_victim_years" if k == "data_victim_age" else k): v for k, v in cdm_types.items()}
    assert check_crosswalk_vs_cdm(cols, renamed_in_cdm), "CDM-only rename went unnoticed"

    placeholders = yaml_placeholders() - {"data_victim_age"} | {"data_victim_years"}
    cw = load_crosswalk()
    mapped = set(cw.loc[cw["rdf_scope"] == "mapped", "flat_column"])
    assert check_crosswalk_vs_yaml(mapped, placeholders), "YAML-only rename went unnoticed"
