# SafeVoice2026: implementation plan and roadmap

Migrated from the Claude Docs artifact "SafeVoice2026 — Implementation Plan & Roadmap" (created 2026-11-17), with the status of every task as of the last update. What was changed and how it was checked is in [../IMPROVEMENTS.md](../IMPROVEMENTS.md).

**Last updated:** 2026-11-17. **Phases 0, 1, 2 and 3 are done. Next: Phase 4.**

## How to use this plan

Work the phases top to bottom and tick a task when its "Done when" check passes.

- **Task IDs** (P0-1, P1-3, ...) are for commits and stand-ups. Codes in brackets (W1-01, W3-04, ...) point to findings in *Technical Plan v2.0*; "FE" items come from *First Plan Frontend SafeVoice*.
- **Priority** follows both documents (Must / Should / Could). Do all Musts before any Should.
- **Files** are paths in this repository. `app.py` + `ui/` is the front end; `src/` + `config/` is the pipeline.

Legend: `[x]` done, `[ ]` open.

## Where things stand

| Area | State today | Biggest gap |
|---|---|---|
| Front-end flow (login, topics, records, corrections) | Built; login checks users from `.env` | Demo login only: no lockout, no HTTPS (W3-01) |
| Form quality (empty defaults, validation, confirmation) | Done | Help text only on the narrative field (P6-1); restored fields not yet on the form (see below) |
| Storage | SQLite (`data/app/safevoice.db`), survives reload and logout | No backup or retention rule yet (P5-3) |
| Pipeline `src/` + `config/` | Aligned with CDM, crosswalk and YAML; fed by `submit_record` | Not yet run against a live AllegroGraph in this project (see P3-3) |
| RDF model | Record fields mapped | No topic, correction or provenance model yet (P4-1, P4-3) |
| Access control | Ownership enforced on every read and write; audit log | AllegroGraph itself not isolated per user (P4-4) |
| Privacy | Coordinates rounded to 3 decimals in the RDF only | Stored and shown precision not unified (P5-1) |

## Roadmap

Four waves: quick fixes; data contract and login; integration; then RDF, privacy and the remaining front-end work, ending with testing and the expert review.

```
P0 quick fixes -> P1 data contract -> P3 persistence + pipeline -> P4 RDF model --\
                  P2 authentication --^                            P5 privacy ----> P7 testing, review, demo
                                                                   P6 front-end polish (optional) --/
```

Phase 3 was the critical step: records could not be stored safely or mapped without loss until the data contract (P1) and real login (P2) existed. Phase 6 is optional polish and can move later if time runs short.

---

## Phase 0: quick fixes (done)

- [x] **P0-1 Fix the Windows date crash** (Must). `%-d` raises `ValueError` on Windows; replaced by `f"{dt.day} ..."` in `ui/views.py`.
- [x] **P0-2 Show creation date on topic cards** (Must).
- [x] **P0-3 Pin dependencies** (Must). `requirements.txt`, verified in a fresh venv.
- [x] **P0-4 Decide the entry point** (Should). `app.py` is the only entry point; the 2025 `app.py` was deleted.

## Phase 1: data contract (done)

- [x] **P1-1 Write the field crosswalk** (Must, W1-03, W1-05). `config/field_crosswalk.csv`.
- [x] **P1-2 Update the CDM CSV to match** (Must, W1-03). 33 -> 56 fields.
- [x] **P1-3 Fix datatype lookup** (Must, W1-01). Lower-case lookup, float/boolean/url added.
- [x] **P1-4 Generate required fields from the CDM** (Must, W1-02).
- [x] **P1-5 Fix the YAML placeholder mismatch** (Must, W1-03).
- [x] **P1-6 Add contract tests** (Must). `tests/test_contract.py`.

## Phase 2: authentication and access control (done)

- [x] **P2-1 Real local login** (Must, W3-01, FE login). Users and PBKDF2 password hashes are in `SAFEVOICE_USERS` in `.env`; `python -m ui.auth` makes a hash. One generic error for a wrong username or password. *Plan said "streamlit-authenticator or bcrypt + user file"; the minimal standard-library version was chosen on request, for demo use only.*
- [x] **P2-2 Server-side ownership on every read and write** (Must, W3-02). Every query in `ui/store.py` filters by owner; `submit_record` and `retry_sync` raise `PermissionError` if the topic, record or corrected record is not the user's. Tested with two users.
- [x] **P2-3 No typed text in file paths** (Must, W3-04). The `.nt` file is named after the server-generated record ID; IDs and usernames must match `[A-Za-z0-9_-]`; the mapper refuses names like `../../x.nt` and checks the resolved path stays inside `data/intermediate`.
- [x] **P2-4 Automatic logout after inactivity** (Should, FE login). 30 minutes by default (`SAFEVOICE_IDLE_MINUTES`). Checked on every interaction, so a tab left open is logged out when it is next used.
- [x] **P2-5 Audit log and integrity hash** (Should, W3-05). `data/audit/audit.log` (append-only JSON lines: time, user, action, record ID; never report content). Each record stores a SHA-256 of its content; the record page shows an error if it no longer matches. *The hash sits in the same database as the record, so it detects accidental or casual edits, not an attacker with full database access.*

## Phase 3: persistence and pipeline integration (done, one check outstanding)

- [x] **P3-1 Choose the app store** (Must). SQLite in `data/app/safevoice.db` (git-ignored). Two tables: `topics`, `records`. AllegroGraph stays the RDF store.
- [x] **P3-2 Re-implement `ui/store.py` on that store** (Must). Same functions, so `ui/views.py` needed only small additions. Demo seed data removed. Data survives reload and logout.
- [ ] **P3-3 Call the pipeline from `submit_record`** (Must). Built: `src/orchestrator/payload.py` builds the nested payload in crosswalk shape (IDs generated from the record ID, dates as ISO text, `source_id` = logged-in user), flattens it and calls `run_full_pipeline`. Tested end to end with the real cleaner and mapper and a faked AllegroGraph upload. **Outstanding:** confirm with the real server that one submitted record produces triples (needs valid `AG_*` values in `.env`).
- [x] **P3-4 Clear success and error feedback** (Must). No fake progress bar, no stack traces. Decision taken: the record is **saved first**; if the database or mapping fails it is marked "Not yet in the database" with a **Retry** button on the record page.
- [x] **P3-5 Clean up files on failure** (Should, W4-01). No raw JSON is written; the single `.nt` file is deleted when ingestion fails and archived when it succeeds.
- [x] **P3-6 Unique IDs and filenames** (Should, W1-04). IDs are 10 hex characters with a database primary key (collision retried); filenames come from record IDs.

## Phase 4: RDF model, provenance and graph isolation (open)

Extend the mapping so the graph holds topics, records, corrections and who submitted them, and check the graph before it is uploaded.

- [ ] **P4-1 Model topic, record and correction in RDF** (Must, W2-05). `ex:topic_<id>`, `ex:record_<id>` linked to its topic, title and narrative; `prov:wasRevisionOf` from a correction to its original, plus the reason. Server-generated IDs only. The crosswalk marks topic ID, `corrects`, correction reason and source ID as `deferred (P4)`.
- [ ] **P4-2 Complete the mapping and test it** (Must, W2-01). `tests/test_mapping.py` with expected triples for 2-3 sample records. Fix the mapper so an empty ID inside an IRI is never written as a truncated IRI such as `ex:victim_` (the trafficker link currently relies on always generating a trafficker ID).
- [ ] **P4-3 Record the submitting user and the transformation** (Should, W2-03). Replace the constant `prov:wasAssociatedWith ex:EEPA`; add a provenance activity (time, code and CDM/mapping versions).
- [ ] **P4-4 Isolate data in AllegroGraph** (Should, W3-03). Named graph per user/source in `src/storage/ingest.py`; drop `create=True`; least-privilege account; fix the README claim about per-source repositories.
- [ ] **P4-5 SHACL validation before upload** (Should, W2-02). `pyshacl` in the orchestrator; stop on failure.

## Phase 5: privacy and data protection (open)

- [ ] **P5-1 One coordinate rule for stored and shown data** (Must, W4-02). Today the RDF rounds to 3 decimals, the screen to 2, and the database keeps full precision. Agree a precision (Q7), apply it before anything is stored, show destination coordinates too.
- [ ] **P5-2 Review free-text and place-name fields** (Must, W4-02). Guidance text on the form; agree with the experts whether any field must be generalised.
- [ ] **P5-3 Protect local files** (Must, W4-01). Synthetic data only in development; `data/` stays git-ignored (now includes `data/app/` and `data/audit/`); document permissions and a retention rule; delete leftover test files from the original repo.
- [ ] **P5-4 Document attachments with dummy files** (Should FE / Could W4-03). `st.file_uploader`, files stored outside AllegroGraph under a server-generated name, metadata only in the graph.

## Phase 6: remaining front-end items (open)

- [ ] **P6-1 Help text on every field** (Should).
- [ ] **P6-2 Filter topics** (Should).
- [ ] **P6-3 Filter records on field values** (Should). Only the user's own records, only display-safe fields.
- [ ] **P6-4 Save as draft** (Could).
- [ ] **P6-5 Check on a phone** (Could).
- [ ] **P6-6 Add the restored fields to the form** (new, Must for data completeness). Decided in P1-1 but not yet on the form: victim current location, state/village for each place, victim and place descriptions, date received, destination name. The CDM, YAML and tests already support them; the form (`record_form` in `ui/views.py`) and the record page need the inputs.

## Phase 7: testing, expert review and delivery (open)

- [ ] **P7-1 End-to-end test** (Must). Log in -> topic -> record -> correction -> check triples in AllegroGraph -> second user has no access. The store, pipeline and ownership parts are covered by `tests/test_store.py`; the live AllegroGraph step and the submit dialog (not drivable with Streamlit `AppTest`) remain.
- [ ] **P7-2 Re-run the Technical Plan reproductions** (Must). W1-01, W1-03, W1-05, W1-06 and W3-04 should no longer reproduce.
- [ ] **P7-3 Expert review with Mirjam and Daniel** (Must). Walk through the flow and bring the open questions below.
- [ ] **P7-4 Update the documentation** (Must). README, flowcharts in `docs/flowcharts/` (basic `SafeVoice2026_flowchart.drawio` updated after Phase 3), changelog against the original SafeVoice.
- [ ] **P7-5 Final fixes and demo** (Must).

---

## Out of scope and open questions

**Out of scope (Won't):** FDP registration (W2-04), encryption at rest and backups (W4-04), IPA single sign-on, production document storage, forgot-password, legal disclaimer, BERT extraction from the narrative.

**Decisions needed from Mirjam and Daniel**, ideally before Phase 4:

- [ ] **Q1** Is a topic or record owned by one user, or can it be shared?
- [ ] **Q2** Are there other roles (e.g. an aid organisation that sees all topics)? Changes P2-2 and P4-4.
- [ ] **Q3** Which fields does a topic need besides title and description?
- [ ] **Q4** What is the minimum to submit a record? (Implemented: title + narrative + topic.)
- [ ] **Q5** What may be corrected, and should the original stay visible to the user? (Implemented: original stays visible.)
- [ ] **Q6** Which fields dropped from the old form must come back? (Decided to restore all; see P6-6.)
- [ ] **Q7** What coordinate precision is acceptable to store and show? Drives P5-1.
- [ ] **Q8** Will users work on a phone? Which document types must be uploaded?

**Open data-model decisions** (crosswalk `DECIDE` rows, see [../IMPROVEMENTS.md](../IMPROVEMENTS.md)): what `source_id` means (username or organisation); a report-language dropdown; several traffickers sharing one description; trafficker IDs linking across records; fate of the CDM `Updates` block.
