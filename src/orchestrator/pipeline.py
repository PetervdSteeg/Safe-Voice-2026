# src/orchestrator/pipeline.py

import os
import shutil
from src.cleaning import run_clean_pipeline
from src.transform import save_triples_to_file
from src.storage import ingest_rdf_file
from src.orchestrator.payload import is_safe_id
from src.validation import shacl

# --- File Path Configuration ---
BASE_DATA_DIR = "data"
PROCESSED_NT_DIR = os.path.join(BASE_DATA_DIR, "processed/processed_nt_file")
os.makedirs(PROCESSED_NT_DIR, exist_ok=True)


def run_full_pipeline(raw_df):
    """
    Executes the data processing workflow for a single report record:
    clean -> RDF -> shape validation -> AllegroGraph. Returns (cleaned_df, status), where status is "Success"
    or "Failed: <reason>". Nothing is written to disk before the record is valid, and the
    only file is the .nt named after the server-generated record ID (P2-3, P3-5).
    """
    # 1. Cleaning
    print("[PIPELINE] Starting Data Cleaning...")
    cleaned_df = run_clean_pipeline(raw_df)

    if cleaned_df.empty:
        print("[PIPELINE] Warning: Empty DataFrame after cleaning.")
        return cleaned_df, "Failed: Empty DataFrame or IDs"

    try:
        source_id = str(cleaned_df['data_record_source_id'].iloc[0]).strip()
        record_id = str(cleaned_df['data_record_record_id'].iloc[0]).strip()
    except KeyError:
        print("[PIPELINE] ERROR: 'source_id' or 'record_id' column not found.")
        return cleaned_df, "Failed: Missing source_id"

    # Both end up in a file name and a graph IRI: accept only a strict pattern.
    if not (is_safe_id(source_id) and is_safe_id(record_id)):
        print("[PIPELINE] ERROR: source_id or record_id has unsafe characters.")
        return cleaned_df, "Failed: Invalid ID"

    # 2. RDF Transformation
    print("[PIPELINE] Starting RDF Transformation...")
    output_filename = f"{record_id}.nt"
    nt_file_path = save_triples_to_file(cleaned_df, filename=output_filename)

    if not nt_file_path:
        print("[PIPELINE] Error: No RDF file produced.")
        return cleaned_df, "Failed: RDF Generation Error"

    # 2b. Check the graph against the shared HDS shapes (W2-02) before anything is uploaded
    conforms, problems = shacl.validate_nt_file(nt_file_path)
    if not conforms:
        print(f"[PIPELINE] ERROR: RDF does not conform to the HDS shapes: {problems}")
        try:
            os.remove(nt_file_path)
        except OSError:
            pass
        return cleaned_df, "Failed: Validation Error"

    # 3. Ingestion to triplestore
    print(f"[PIPELINE] Ingesting {output_filename}...")
    ingest_success = ingest_rdf_file(nt_file_path, source_id=source_id)

    # 4. Archive
    if ingest_success:
        try:
            shutil.move(nt_file_path, os.path.join(PROCESSED_NT_DIR, output_filename))
        except Exception as e:
            print(f"[WARN] Failed to move NT file: {e}")
        return cleaned_df, "Success"

    # Failed: remove the staging file; the record stays in the app store and can be retried.
    try:
        os.remove(nt_file_path)
    except OSError:
        pass
    print("[PIPELINE] ERROR: Ingestion failed.")
    return cleaned_df, "Failed: Ingestion Error"
