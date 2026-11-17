# SafeVoice2026: improvements made to the code base

This file records what has been changed compared with the original SafeVoice (2025), why, and how each change was checked. Task IDs (P0-1, P1-3, ...) refer to the *SafeVoice2026 Implementation Plan & Roadmap*; codes in brackets (W1-01, ...) are the findings in *Technical Plan v2.0*.

**Status:** Phases 0 to 3 complete (data contract, authentication, persistence, pipeline hookup). Next: Phase 4 (RDF model). Full plan: [plan/IMPLEMENTATION_PLAN.md](plan/IMPLEMENTATION_PLAN.md). and Phase 3 (persistence and pipeline integration).

---

## Background: how a report becomes a fact in the database

```
form -> JSON -> flatten to a table row -> clean (uses the CDM) -> RDF triples (uses the YAML mapping) -> AllegroGraph
```

- **CDM** (`config/CDM - Human Trafficking Sources EEPA.csv`): the list of allowed fields, with type and "required".
- **Flattening**: nested JSON becomes one row; `data.victim.age` becomes the column `data_victim_age`.
- **YAML mapping** (`config/yml_mapping.yml`): a recipe that turns a row into triples. It reads columns by name, e.g. `$(data_victim_age)`.
- **Triple**: one fact written as subject - predicate - object, e.g. `victim_77  age  17`.

The same field name has to be right in the form, the CDM and the YAML. When it isn't, nothing crashes; the data silently disappears. Phase 1 removes that risk.

---

## Phase 0: quick fixes

| Task | Change | Files |
|---|---|---|
| P0-1 | Dates no longer crash on Windows. `strftime("%-d")` works only on Linux/macOS; replaced by `f"{dt.day} {dt:%b}"`. | `ui/views.py` |
| P0-2 | Topic cards show "Created <date>", record count and last update. | `ui/views.py` |
| P0-3 | Dependencies pinned to the tested versions (Streamlit 1.67.0, pandas 3.0.6, numpy 2.4.6, PyYAML 6.0.3, python-dotenv 1.2.4, agraph-python 105.4.0). Verified in a fresh virtual environment. | `requirements.txt` |
| P0-4 | One entry point: `streamlit run app.py`. The deprecated 2025 `app.py` was deleted and `app_new.py` renamed to `app.py`. README rewritten (venv step, Python 3.11+, run command, new usage guide); flowchart updated. | `app.py`, `README.md`, `docs/flowcharts/` |

Also fixed: `pd.to_datetime(..., infer_datetime_format=True)` raised `TypeError` on pandas 3 and would have stopped the cleaner at its first date column. The argument was removed (format inference is the default since pandas 2). `src/cleaning/cleaner.py`.

---

## P1-1: field crosswalk (new)

`config/field_crosswalk.csv` lists every field once: group, field, flattened column, origin, whether the old/new form has it, decision, matching CDM field, type, required, current RDF predicate, status, notes.

Decisions recorded in it:

| Field | Decision |
|---|---|
| `record_id`, `victim_id`, `incident_id` | Generated server-side, never typed |
| `source_id` | Taken from the logged-in user |
| `date_recorded` | Set automatically at submission time |
| `trafficker_id` | Generated, one per record (no cross-record linking) |
| Victim current location, state, village, descriptions, date received | Restored in the form for all topics |

Findings that drove the next tasks (before the fixes below): only 9 of 53 fields were consistent across form, CDM and YAML; 12 had names the cleaner could not match; 25 were missing from the CDM; 17 had no YAML mapping.

Open `DECIDE` rows (need the experts): what `source_id` means (username or organisation); whether to add a report-language dropdown; whether several traffickers may share one description; whether trafficker IDs should ever link across records; whether the CDM's unused `Updates` block is replaced by the new corrects/reason model.

---

## P1-2: CDM updated to match the crosswalk

`config/CDM - Human Trafficking Sources EEPA.csv`: 33 fields -> 56.

- **Names now equal the form's JSON keys.** `victim_age` -> `age`, `victim_nationality` -> `nationality`, `trafficker_nat` -> `nationality`, `pub_name` -> `name`, `current_lat` -> `current_location_latitude`, and so on.
- **Added:** `topic_id`, `title`, `narrative`, `corrects`, `correction_reason`, `date_received`, `date_recorded`, `report_language`, victim current location (country/state/town/village/lat/lon), victim description, state/village/name/description for both departure and destination, `departure_date` / `destination_date`, `destination_type`, `number_of_traffickers`, trafficker description.
- **Required = Yes:** record ID, source ID, topic ID, title, narrative, incident ID, victim ID. Trafficker ID is optional.
- **Removed:** `incident_description` (no form field or YAML line ever used it; the narrative covers it).
- **Kept unchanged:** the `Updates` block, pending a decision.

Related code changes:

- `src/cleaning/cleaner.py`: the `data_` prefix is now applied to every level except `Updates`. Before, only record/victim/incident got it, so trafficker and publication columns never matched the data.
- `ui/views.py`, `ui/store.py`: the trafficker count key was renamed `number` -> `number_of_traffickers`, to match the victim equivalent and the CDM.

---

## P1-3: datatype lookup fixed (W1-01)

**Problem.** The cleaner translated CDM types through a table with title-case keys (`'Integer'`), but the CDM says `integer`. Every lookup returned `None`, so no column was ever converted to its real type.

**Change** (`src/cleaning/cleaner.py`):

- `TYPE_TRANSLATION` keys are lower-case and the lookup lower-cases and trims the CDM value.
- Added `float`, `boolean` and `url`.
- Unknown types print a warning instead of silently becoming `None`.
- Boolean columns are converted (`"true"` / `"false"` -> real booleans).

**Checked:** all 56 CDM fields resolve to a type (0 `None`). Test values convert correctly: age -> integer, latitude -> float (and still rounded to 3 decimals), date string -> date, `"TRUE"` -> `True`.

---

## P1-4: required fields come from the CDM (W1-02)

**Problem.** The cleaner dropped records unless three ID columns were present (`record_id`, `victim_id`, `trafficker_id`), a list written by hand in the code and unrelated to the CDM's "Required" column.

**Change** (`src/cleaning/cleaner.py`):

- New `create_required_columns()` reads the CDM "Required" column; `run_clean_pipeline` passes the result to `clean_and_preprocess`.
- A record missing a required value is dropped, and the number dropped is logged.
- If a required column is absent from the input altogether, every row is rejected and the missing columns are named. (Before, an absent column was skipped silently.)
- The CDM parsing is shared by the type map and the required list (`_read_cdm`), so they cannot disagree.

**Checked:**

- A record with title, narrative, topic and the generated IDs passes cleaning (1 row), with no trafficker needed.
- The same record with an empty narrative is rejected (0 rows).

---

## P1-5: YAML mapping aligned with the crosswalk (W1-03)

`config/yml_mapping.yml`:

- **Fixed** `data_victim_count` (a column that never existed, so the victim count was never written) -> `data_victim_number_of_victims`.
- **Added** triples for fields that were collected but never mapped: incident ID, record title, narrative, date received, date recorded, language; village for departure and destination; destination name; departure and arrival dates; number of traffickers.
- **Changed** `departure/destination type` from `schema:description` to `cdm:locationType`. It used to share a predicate with the free-text description, so the two were mixed together. The victim's current village moved from `schema:description` to `cdm:village` for the same reason.
- Dates are written as `xsd:date`.
- **Deferred to Phase 4** (RDF model for topics, corrections and provenance): topic ID, `corrects`, correction reason, source ID. They are marked `deferred (P4)` in the crosswalk and noted in the YAML.

Related fix in `src/transform/mapper.py` (`safe_str`): with real column types (P1-3), a missing integer became `pd.NA` and a missing date `NaT`, and both would have been written to the graph as the text `"<NA>"` / `"NaT"`. They are now treated as empty and skipped. Dates no longer carry a `00:00:00` time.

`config/field_crosswalk.csv` was simplified to the columns that do not go stale (group, field, column, origin, old/new form, decision, `rdf_scope`, current predicates, notes). It is now maintained by hand and guarded by the tests below.

---

## P1-6: contract tests (new)

`tests/test_contract.py` (run `pytest`; needs `requirements-dev.txt`). The crosswalk is the single field list; the tests check it against the CDM, the YAML and the real cleaner/mapper:

| Test | Fails when |
|---|---|
| crosswalk matches CDM | a field exists in one but not the other, or a CDM type is unknown |
| crosswalk matches YAML | a mapped field is not read by the YAML, or the YAML reads a column that does not exist |
| required fields in crosswalk | the CDM requires something no form field provides |
| every CDM type converts | a value fails type conversion (becomes missing) |
| every mapped field reaches the triples | a value goes in the cleaner but never appears in the RDF (runs a full sample record through cleaner and mapper) |
| missing values are not written as text | an empty field becomes `<NA>` / `NaT` in the graph |
| checks catch a one-sided rename | the guard itself stops working |

**Verified:** 7 tests pass. Renaming a field in only the YAML, or only the CDM, makes 2 and 4 tests fail respectively.

---

## P2-1: demo login (new)

`ui/auth.py`, `ui/views.py` (login page), `.env.example`, `tests/test_auth.py`.

- Allowed users are in `SAFEVOICE_USERS` in `.env`: comma-separated `username:hash`. Passwords are never stored, only salted PBKDF2-SHA256 hashes (standard library, no new dependency).
- `python -m ui.auth` prompts for a username and password and prints the line to add.
- Wrong username or password gives one generic error. Usernames are case-insensitive.
- **Demo only:** no lockout, no sessions timeout, no HTTPS. Real authentication (W3-01) is still needed before real use.
- Tested: 3 unit tests, plus a headless run of the login screen (wrong password rejected, correct one logs in).

---

## P2-2 to P2-5: access control, safe paths, idle logout, audit

- **P2-2 ownership.** Every query in `ui/store.py` filters by owner. `submit_record` and `retry_sync` raise `PermissionError` when the topic, record or corrected record is not the user's. Tested with two users (`tests/test_store.py`).
- **P2-3 safe paths.** The `.nt` file is named after the server-generated record ID. IDs and usernames must match `[A-Za-z0-9_-]` (usernames in `SAFEVOICE_USERS` that don't are ignored). `mapper.save_triples_to_file` refuses names like `../../x.nt` and checks the resolved path stays inside `data/intermediate`.
- **P2-4 idle logout.** 30 minutes by default (`SAFEVOICE_IDLE_MINUTES`). Checked on each interaction in `app.py`; the login page then explains why.
- **P2-5 audit and integrity.** `ui/audit.py`: append-only `data/audit/audit.log` (login, failed login, logout, topic created, record submitted, synced / not synced; no report content). Each record stores a SHA-256 of its content and the record page flags a mismatch. The hash lives in the same database, so it detects accidental edits, not a determined attacker.

---

## P3: persistence and pipeline integration

- **P3-1/P3-2 store.** `ui/store.py` now uses SQLite (`data/app/safevoice.db`, git-ignored; path via `SAFEVOICE_DB`). Same function names, so the screens are almost unchanged. Records are immutable; corrections are new rows. The demo seed data is gone: a fresh install starts empty.
- **P3-3 pipeline.** `submit_record` saves the record, then `src/orchestrator/payload.py` builds the payload in crosswalk shape (record, victim, incident and trafficker IDs generated from the record ID; `source_id` = logged-in user; `date_recorded` = submission time; dates as ISO text), flattens it and calls `run_full_pipeline`. Verified with the real cleaner and mapper and a faked AllegroGraph upload. **Not yet verified against a live AllegroGraph.**
- **P3-4 feedback.** A record is saved before the pipeline runs. If the database or mapping fails, the record shows a "Not yet in the database" badge and a **Retry** button; the user sees a plain message and never a stack trace.
- **P3-5/P3-6 files and IDs.** No raw JSON is written any more; the `.nt` staging file is removed on failure and archived on success. `pipeline.run_full_pipeline(raw_df)` lost its unused `raw_json_path` argument. IDs are 10 hex characters with a database primary key (collisions retried).

Tests: `tests/test_store.py` (15) covers ownership, round trip, corrections, pipeline success/failure/retry, unsafe paths, idle logout, audit log content and hash tampering. 29 tests pass in total.

**Not covered by automated tests:** the confirm dialog (Streamlit `AppTest` cannot click inside dialogs; checked via the store instead) and the live AllegroGraph upload.

---

## Behaviour changes to be aware of

1. **The 2025 interface and its pipeline hookup are gone.** The new UI feeds the pipeline through `submit_record` (Phase 3).
2. **Trafficker and publication fields are now type-converted by the cleaner.** Before, their CDM entries used different column names, so the cleaner never saw them.
3. **Records now persist** in SQLite instead of the browser session. Demo seed data was removed.
4. **The form still lacks the restored fields** (victim current location, state/village, descriptions, date received, destination name); the pipeline already supports them (plan task P6-6).

## Open expert decisions (from the crosswalk)

What `source_id` means (username or organisation); whether to add a report-language dropdown; whether several traffickers may share one description; whether trafficker IDs should ever link across records; whether the CDM's unused `Updates` block is replaced by the new corrects/reason model.
