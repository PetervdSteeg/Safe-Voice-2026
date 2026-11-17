# src/cleaning/cleaner.py

import pandas as pd
import numpy as np

# --- CONFIGURATION ---
# CDM file path
CDM_FILE_PATH = 'config/CDM - Human Trafficking Sources EEPA.csv'
# CDM data type -> internal conversion type.
# Keys are LOWER-CASE: the lookup lower-cases whatever the CDM says, so
# "Integer", "integer" and " INTEGER " all work. The old title-case keys never
# matched the lower-case CDM, so every column type came out as None (W1-01).
TYPE_TRANSLATION = {
    'integer': 'INT',
    'string': 'STRING',
    'string (predefined)': 'STRING',
    'date': 'DATE',
    'float': 'FLOAT',
    'decimal': 'FLOAT',        # old schema layout
    'boolean': 'BOOL',
    'url': 'STRING',
}
# ---------------------


def translate_type(raw_type):
    """Look up a CDM data type (case/whitespace-insensitive). Unknown types are reported, not silently dropped."""
    key = str(raw_type).strip().lower()
    result = TYPE_TRANSLATION.get(key)
    if result is None:
        print(f"[CLEANER] Warning: unknown CDM data type '{raw_type}'. Add it to TYPE_TRANSLATION.")
    return result

def normalize_name(s):
    """Converts CDM string (e.g., 'Record ID') to flat snake_case (e.g., 'record_id')."""
    if pd.isna(s) or s.lower() in ['nan', '']:
        return None
    return str(s).strip().lower().replace(' ', '_')

def create_cdm_column_map(cdm_file_path):
    """Return {flat column name: internal type} for every field in the CDM."""
    return {col: fmt for col, fmt, _ in _read_cdm(cdm_file_path)}


def create_required_columns(cdm_file_path):
    """Return the flat column names the CDM marks Required = Yes (W1-02)."""
    return [col for col, _, required in _read_cdm(cdm_file_path) if required]


def _read_cdm(cdm_file_path):
    """
    Reads the CDM csv file and returns a list of (flat column name, internal type, is_required).
    Flat names follow the JSON flattening in the UI: data_<level>_<field>.
    """
    try:
        # Using engine='python' and sep=None handles potential encoding/delimiter shifts smoothly
        cdm_raw = pd.read_csv(cdm_file_path, dtype=str, encoding='utf-8-sig', sep=None, engine='python')
        print("[CLEANER] CDM Schema loaded successfully.")
    except Exception as e:
        print(f"[CLEANER] Could not load CDM schema. {e}")
        return []

    fields = []
    cdm = cdm_raw.copy()
    cdm.columns = cdm.columns.str.strip()
    
    # Check if the CSV is using the new flat layout or the old multi-level layout
    if 'Level' in cdm.columns and 'Field Name' in cdm.columns:
        # --- NEW SCHEMA LAYOUT LOGIC ---
        cdm['Level'] = cdm['Level'].ffill()
        
        for index, row in cdm.iterrows():
            level = str(row.get('Level', '')).strip()
            field_name = str(row.get('Field Name', '')).strip()
            data_type = str(row.get('Data Type', '')).strip()
            
            normalized_level = normalize_name(level)
            normalized_field = normalize_name(field_name)
            
            if not normalized_field:
                continue
            
            # Combine level and field name to build the flat column structure
            if normalized_level and normalized_level != normalized_field:
                flat_col_name = f"{normalized_level}_{normalized_field}"
            else:
                flat_col_name = normalized_field
            
            # Add 'data_' prefix to separate core data columns from metadata
            if normalized_level != 'updates':  # every data level lives under the JSON "data" key
                flat_col_name = "data_" + flat_col_name
            
            is_required = str(row.get('Required', '')).strip().lower() in ('yes', 'true', 'y')
            fields.append((flat_col_name, translate_type(data_type), is_required))

    else:
        # --- OLD SCHEMA LAYOUT LOGIC (Fallback) ---
        if 'Level 1' not in cdm.columns:
            print(f"[CLEANER] CRITICAL ERROR: Neither 'Level' nor 'Level 1' columns found!")
            return []
            
        cdm['Level 1'] = cdm['Level 1'].ffill()
        cdm['Level 2'] = cdm['Level 2'].ffill()
        cdm['Level 3'] = cdm['Level 3'].fillna(np.nan)
        
        for index, row in cdm.iterrows():
            l1 = str(row.get('Level 1', '')).strip()
            l2 = str(row.get('Level 2', '')).strip()
            l3 = str(row.get('Level 3', '')).strip()
            required_format = str(row.get('Format', '')).strip()
            
            normalized_l1 = normalize_name(l1)
            normalized_l2 = normalize_name(l2)
            normalized_l3 = normalize_name(l3)

            flat_parts = [p for p in [normalized_l1, normalized_l2, normalized_l3] if p]
            if not flat_parts:
                continue
            
            flat_col_name = "_".join(flat_parts)
            if normalized_l1 != 'updates':
                flat_col_name = "data_" + flat_col_name
            
            # The old layout has no Required column, so nothing is required there.
            fields.append((flat_col_name, translate_type(required_format), False))

    return fields

def clean_and_preprocess(df, flat_to_format_map, required_columns=None):
    """
    Performs the data cleaning and pre-processing steps, including dropping records
    that lack a field the CDM marks as required,
    converting the data to correct data type based on format map,
    and rounding the latitude and lontitude columns.
    """
    if required_columns is None:
        required_columns = create_required_columns(CDM_FILE_PATH)
    
    # --- Remove this part since data input is not csv anymore ---
    # 1. Handling Missing Values
    ## Replace common excel error such as '#REF!' with NaN
    #values_to_replace = ['#N/A', '#VALUE!', '#DIV/0!', '#NUM!', '#NAME?', '#NULL!', '#REF!']
    #df = df.replace(values_to_replace, np.nan)
    # ------
    
    # 2. Drop rows where the critical ID columns are missing
    # NOTE: The column names here must be accurate to the column names in config/field_crosswalk.csv.
    
    # Convert empty strings and whitespace to NaN
    df.replace(r'^\s*$', np.nan, regex=True, inplace=True)
    # Drop rows that lack a required field. The list comes from the CDM "Required"
    # column, so it can no longer drift from the data model (W1-02).
    absent = [col for col in required_columns if col not in df.columns]
    if absent:
        # The sender forgot a required field entirely: reject every row, loudly.
        print(f"[CLEANER] Rejected: required columns missing from input: {absent}")
        return df.iloc[0:0]
    before = len(df)
    df.dropna(subset=required_columns, inplace=True)
    if len(df) < before:
        print(f"[CLEANER] Dropped {before - len(df)} row(s) missing a required field.")

    STRING_COLUMNS = []
    INT_COLUMNS = []
    FLOAT_COLUMNS = []
    DATE_COLUMNS = []
    BOOL_COLUMNS = []

    # 3. Convert the data to correct data type defined by the format map for further data processing steps
    for flat_col_name in df.columns:
        
        # Use .get() to look up the required format directly from the map
        required_format = flat_to_format_map.get(flat_col_name)
        
        if required_format == 'STRING':
            STRING_COLUMNS.append(flat_col_name)
        elif required_format == 'INT':
            INT_COLUMNS.append(flat_col_name)
        elif required_format == 'FLOAT':
            FLOAT_COLUMNS.append(flat_col_name)
        elif required_format == 'DATE':
            DATE_COLUMNS.append(flat_col_name)
        elif required_format == 'BOOL':
            BOOL_COLUMNS.append(flat_col_name)

    # Applying data type conversions
    
    # a. INTEGER Conversion
    for col in INT_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
    
    # b. FLOAT Conversion
    for col in FLOAT_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')
    
    # c. DATE Conversion
    for col in DATE_COLUMNS:
        # Format inference has been the default since pandas 2.0; the old
        # infer_datetime_format keyword was removed in pandas 3 (TypeError).
        df[col] = pd.to_datetime(df[col], errors='coerce')

    # d. BOOLEAN Conversion ("true"/"false" strings or real booleans; anything else becomes missing)
    for col in BOOL_COLUMNS:
        df[col] = (df[col].astype('string').str.strip().str.lower()
                   .map({'true': True, 'false': False}).astype('boolean'))

    # 4. Anonymize the location information by rounding the latitude and longitude
    # NOTE: The column names here must be accurate to the column names in config/field_crosswalk.csv.
    location_cols = [
        'data_victim_current_location_latitude',
        'data_victim_current_location_longitude',
        'data_incident_departure_latitude',
        'data_incident_departure_longitude',
        'data_incident_destination_latitude',
        'data_incident_destination_longitude'
    ]

    for col in location_cols:
        # Check if column exists to avoid KeyErrors if the schema changes
        if col in df.columns:
            # Round to 3 decimal places
            df[col] = df[col].round(3)
    
    print("[PIPELINE] Data cleaning complete.")
    return df


def run_clean_pipeline(raw_df):
    
    # --- Execute Cleaning Steps ---
    
    cdm_column_map = create_cdm_column_map(CDM_FILE_PATH)
    required_columns = create_required_columns(CDM_FILE_PATH)
    cleaned_df = clean_and_preprocess(raw_df, cdm_column_map, required_columns)
    
    # Return the cleaned data and row count
    return cleaned_df