# SafeVoice: Human Trafficking Source Information
## Description
**SafeVoice** is a data pipeline application designed to transform raw human trafficking incident reports into semantic RDF triples. Built as part of the 2025 Data Science in Practice (DSIP) course, this application manages the below data lifecycle:

* **Data Entry UI**: A user interface for submitting reports.

* **Data Cleaning**: Automated data cleaning and anonymization of raw inputs.

* **RDF Mapping**: Transformation of data into RDF N-Triples.

* **Ingestion**: Direct upload of RDF N-Triples to an AllegroGraph server.

## Project Structure

This project follows a modular architecture to separate the user interface, data processing, and storage logic.

```
SAFEVOICE project/
├── app.py                      # Main entry point: SafeVoice2026 Streamlit UI (topics, records, corrections)
├── ui/
│   ├── views.py                # Screens: login, topics, topic, record, record form
│   ├── store.py                # Topics and records in SQLite; sends each submitted record through the pipeline
│   ├── auth.py                 # Demo login (users and password hashes from .env), idle timeout
│   ├── audit.py                # Append-only audit log and record integrity hash
│   └── nav.py                  # URL-based navigation, breadcrumbs, flash messages
├── requirements.txt            # Pinned Python dependencies
├── requirements-dev.txt        # Adds pytest for the tests
├── tests/                      # Contract, login, store and pipeline tests (run: pytest)
├── docs/
│   ├── IMPROVEMENTS.md         # Changelog against the original SafeVoice
│   └── plan/IMPLEMENTATION_PLAN.md  # Plan and roadmap with task status
├── config/
│   ├── UI_drop_downs.csv       # Defines UI dropdown options
│   ├── yml_mapping.yml         # YARRRML configuration mapping dataframe to RDF
│   ├── field_crosswalk.csv     # One row per field: form <-> CDM <-> RDF (single source of truth)
│   └── Data schemas CDM...csv  # Common Data Model schema
├── data/
│   ├── app/                    # SQLite database with topics and records (git-ignored, created on first use)
│   ├── audit/                  # audit.log: who did what, never report content (git-ignored)
│   ├── intermediate/           # Staging area for generated .nt RDF files
│   └── processed/              # Archive of .nt files that were ingested successfully
└── src/
    ├── orchestrator/
    │   ├── pipeline.py         # The central controller script that manages the flow of data from cleaning to mapping to ingestion
    │   └── payload.py          # Builds the pipeline payload (generated IDs, ISO dates) from a stored record
    ├── cleaning/
    │   └── cleaner.py          # Handles data cleaning, type casting, and location anonymization
    ├── transform/
    │   └── mapper.py           # Converts clean DataFrames into RDF triples using the YAML config
    └── storage/
        └── ingest.py           # Handles connection and upload RDF triples to the AllegroGraph server
```

- **`app.py`** + **`ui/`**: The SafeVoice2026 user interface and entry point. Users log in, organise reports into topics, submit records and corrections. Records are stored in SQLite (`ui/store.py`, `data/app/`) and sent through the pipeline (`src/orchestrator/`) to AllegroGraph on submit; if the database is unreachable they are kept and can be retried.
- **`src/orchestrator/pipeline.py`**: Acts as the central orchestrator, managing the full data flow from cleaning and transformation to ingestion.
- **`src/cleaning/cleaner.py`**: Converts raw input data into the correct data types based on the CDM schema (located under `/config` and configurable), and performs preprocessing steps such as geodata anonymization.
- **`src/transform/mapper.py`**: Converts the cleaned data into RDF N-Triples using the provided YARRRML mapping configuration (located under `/config` and configurable).
- **`src/storage/ingest.py`**: Manages the connection to the AllegroGraph server and uploads the generated RDF files to the source-specific repository (e.g., `001_repo`).
- **`config/`**: Contains the UI dropdown CSV file, the CDM schema CSV file, and the YARRRML mapping configuration file.

## Getting Started

### Prerequisites

* **Python 3.11 or newer** (tested on 3.11, Windows)
* **AllegroGraph Server** (Cloud or Local)
* Python packages, pinned in `requirements.txt` (Streamlit 1.50 or newer is required by the new UI)


### Installing

1. Clone the repo
   ```sh
   git clone https://github.com/VODAN-Development/SafeVoice.git
   cd SafeVoice
   ```
2. Create a virtual environment and install the dependencies
   ```sh
   python -m venv .venv
   .venv\Scripts\activate          # Windows (macOS/Linux: source .venv/bin/activate)
   pip install -r requirements.txt
   ```
3. Create your AllegroGraph server to store the triples
4. Replace your AllegroGraph server credentails in `.env` (Rename existing .env.example file to .env)
   ```
    # --- Server Configuration Constants ---
    # NOTE : Please replace your server credentials here
    AG_BASE_URL=allegrograph_base_url
    AG_REPO=your_repository_name
    AG_USER=your_allegrograph_username
    AG_PASSWORD=your_allegrograph_password
   ```
5. Replace your CDM file name and path in `cleaner.py`
   ```
   # --- CONFIGURATION ---
   # CDM file path
   CDM_FILE_PATH = 'config/CDM - Human Trafficking Sources EEPA.csv'
   ```

6. Replace your YAML mapping file name and path in `mapper.py`
   ```
   # --- Configuration ---
   # Define the expected location of the YML mapping file
   YML_MAPPING_PATH = os.path.join("config", "yml_mapping.yml")
    
   # Define the intermediate data path for .nt files
   # This is where the RDF files will be stored before ingestion
   INTERMEDIATE_DIR = os.path.join("data", "intermediate")
   ```
   
### Executing program
```sh
streamlit run app.py
```
Log in with a user defined in `.env` (demo only). Generate a password hash with `python -m ui.auth` and add `username:hash` to `SAFEVOICE_USERS` (comma-separated for several users); see `.env.example`.

### Running the tests
```sh
pip install -r requirements-dev.txt
pytest
```
The contract tests fail if a field is renamed in the form, CDM or YAML mapping without the others.
## Application Usage Guide

1. **Log in** with a demo user from `.env`.
2. **Choose or create a topic.** Topics group related records. Use the search box to find one, or **New topic** to create one.
3. **Add a record.** Open a topic and select **New record**. A record name and a narrative are required; everything under *Details* is optional, so leave out what you do not know. Select **Review and submit**, check the summary and confirm.
4. **Open a record** to see its details, its history and any corrections.
5. **Correct a record.** Records are never edited. Select **Submit correction**, change what was wrong and give a reason; a new record is created and the original stays unchanged and visible.

> Records are currently kept in the browser session only and are not yet sent to the pipeline or AllegroGraph (planned, see `docs/IMPROVEMENTS.md`).

## Authors
| Name | Github Username | 
| :---- | :------------------- |
|DA    |duyanhtrinh| 
|Mihir |mihirramani|
|Nurifeiya |nurifeiya|
|Stephanie |yocabano|
|Xiong |arashikuma|

## License
[MIT License](https://gh.io/mit)


