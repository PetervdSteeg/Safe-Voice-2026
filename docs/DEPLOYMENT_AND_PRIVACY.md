# Deployment checklist and privacy notes

Written for the HDS deployment step (where AllegroGraph runs, local provider, local FDP). It lists what the
application does itself and what the host has to provide. Fill in the "Decision" column with the team.

## 1. Decisions for the deployment session

| Question | Why it matters | Decision |
|---|---|---|
| Where does AllegroGraph run (Kenya, Uganda, Ethiopia or Belgium)? | Decides which data-protection law applies and who can be compelled to hand over data | |
| Which local provider hosts it? | Needs the controls in section 2 | |
| Where does the SafeVoice app and its SQLite file run? | The SQLite file holds the full records (section 3) | |
| Which local FDP do we register with? | Needs its endpoint and metadata profile; `python -m src.fdp.metadata` prepares the metadata | |
| Which licence or rights statement describes the data? | A legal decision; `SAFEVOICE_LICENSE` stays empty until agreed | |
| Who is the publisher / data owner in the metadata? | `SAFEVOICE_PUBLISHER` | |

## 2. What the host has to provide (W4-04: not done by the application)

- **Encryption at rest** of the disks that hold the SQLite file, the audit log and the AllegroGraph repository.
- **Encrypted backups**, with the encryption keys kept apart from the backups, and a tested restore.
- **Transport encryption**: AllegroGraph is already reached over HTTPS (port 443). The Streamlit app must be put
  behind HTTPS too (reverse proxy); the demo login is not production authentication.
- **Access**: only named administrators can log in to the server; least-privilege file permissions on `data/` and `.env`.
- **AllegroGraph accounts**: the application uses one account. Give it write access to its repository only, no
  repository creation (`AG_CREATE_REPO=false`), and keep other accounts read-only.
- **Retention and deletion**: agree how long records are kept and who may delete them (`python -m src.storage.admin
  drop-user NAME` removes a user's graph; the SQLite rows and audit log are separate).
- **Monitoring**: who reads `data/audit/audit.log` and checks `python -m ui.audit verify`.

## 3. What the application does itself

| Control | How | Switch |
|---|---|---|
| Login and ownership | Hashed passwords from `.env`, every query filtered by the logged-in user | `SAFEVOICE_USERS` |
| Brute-force lockout | 5 failures lock a user name for 15 minutes (in memory) | `SAFEVOICE_MAX_ATTEMPTS`, `SAFEVOICE_LOCKOUT_MINUTES` |
| One graph per user in AllegroGraph | `<graph base>/<user>` | `SAFEVOICE_GRAPH_BASE` |
| Encrypted database columns | Fernet: titles, narratives, reasons, data, topic titles | `SAFEVOICE_DB_KEY`, `python -m ui.secure migrate` |
| Tamper-evident records | Keyed hash per record | `SAFEVOICE_INTEGRITY_KEY`, `python -m ui.secure sealhash`, `SAFEVOICE_INTEGRITY_STRICT=true` |
| Tamper-evident audit log | Every line holds the hash of the line before | `python -m ui.audit verify` |
| Shape validation before upload | HDS shapes plus our extension shapes | `SAFEVOICE_VALIDATE_RDF` |
| Coordinates generalised | Rounded to 3 decimals (about 110 m) when saved | fixed |

Keys: keep `SAFEVOICE_DB_KEY` and `SAFEVOICE_INTEGRITY_KEY` outside the database folder and back them up. Without
the database key encrypted rows cannot be read.

## 4. Privacy risks that remain (documented limitations)

- **Free text is not de-identified.** The narrative, victim and trafficker descriptions, place names, a trafficker's
  name or alias and the publication details can identify people, places or sources. The form says "non-identifying
  details only", but nothing checks it. A human review step or guidance for reporters is needed.
- **Coordinates to about 110 m, plus dates and a small group size, can still single out a person or a camp.**
  Rounding is generalisation, not anonymisation. Re-identification risk has not been assessed.
- **Older records** keep the precision they were saved with: changing them would break their integrity hash.
- **The reporter's user name** is written to the shared graph (`dcterms:identifier` on the reporting agent) so the
  source of a record is traceable. If user names are real names, use pseudonyms or an organisation ID.
- **The demo login** has no password reset, no second factor and no session expiry beyond idle logout.
- **Keys in `.env`** are readable by anyone who can read the file. Use the host's secret store in production.
- **The audit log** is tamper-evident, not tamper-proof: removing lines from the end is not detectable from the log alone.
