"""Create synthetic records for demos, tests and the HDS portal. Nothing here is real data.

    python -m ui.mockdata --user alice --records 20            create and upload
    python -m ui.mockdata --user alice --records 20 --no-upload   create only (upload later with Retry)

The records go through the normal path (SQLite, cleaning, RDF, shape check, AllegroGraph), so they also
prove that the mapping produces valid HDS data. Every title starts with "[MOCK]" and every narrative says
it is synthetic. `--user` must be a user from SAFEVOICE_USERS to see the data in the app.
"""
import os
import random
import sys
from datetime import date, timedelta

import pandas as pd

from ui import store

DROPDOWNS = os.path.join("config", "UI_drop_downs.csv")
_FALLBACK = {"Country": ["Sudan", "Uganda", "Kenya", "Ethiopia"], "Gender": ["Female", "Male", "Other"],
             "Situation": ["In captivity", "En route", "Other"], "Nationality": ["Ethiopia", "Eritrea", "Sudan"],
             "Type of location": ["Refugee/IDP Camp", "Human Trafficking/Smuggling Camp"]}
_TOWNS = ["Mock Town A", "Mock Town B", "Mock Village C", "Mock City D"]


def _options():
    try:
        frame = pd.read_csv(DROPDOWNS, dtype=str, encoding="utf-8-sig")
        return {c: frame[c].dropna().tolist() for c in _FALLBACK if c in frame.columns} | {
            c: v for c, v in _FALLBACK.items() if c not in frame.columns}
    except (OSError, ValueError):
        return dict(_FALLBACK)


def _place(rng, opts, start):
    return {"country": rng.choice(opts["Country"]), "town": rng.choice(_TOWNS), "date": start,
            "latitude": round(rng.uniform(-5, 20), 3), "longitude": round(rng.uniform(25, 45), 3),
            "type": rng.choice(opts["Type of location"])}


def make_data(rng, opts, full):
    """Structured data for one record; with full=False most optional fields stay empty."""
    if not full:
        return {"victim": {"number_of_victims": rng.randint(1, 4)}, "incident": {}}
    start = date(2026, 1, 1) + timedelta(days=rng.randint(0, 200))
    return {
        "victim": {"number_of_victims": rng.randint(1, 6), "nationality": rng.choice(opts["Nationality"]),
                   "gender": rng.choice(opts["Gender"]), "age": rng.randint(8, 60),
                   "situation": rng.choice(opts["Situation"])},
        "incident": {"departure": _place(rng, opts, start),
                     "destination": _place(rng, opts, start + timedelta(days=rng.randint(1, 30)))},
        "trafficker": {"number_of_traffickers": rng.randint(1, 3), "name": "", "nationality": rng.choice(opts["Nationality"]),
                       "description": "Synthetic description."},
        "publication": {"name": "Mock Gazette", "link": "https://example.org/mock", "date": start},
    }


def generate(user, records=20, seed=7, upload=True):
    """Create 2 topics and `records` synthetic records for `user`. Returns the list of stored records."""
    rng, opts = random.Random(seed), _options()
    if not upload:
        original, store.run_pipeline = store.run_pipeline, lambda df: (df, "Failed: Ingestion Error")
    try:
        topics = [store.create_topic(user, f"[MOCK] Topic {n}", "Synthetic topic for demos.") for n in "AB"]
        stored = []
        for i in range(1, records + 1):
            topic = topics[i % 2]
            corrects = None
            if i % 5 == 0 and stored:  # every fifth record corrects an earlier one in the same topic
                earlier = [r for r in stored if r["topic_id"] == topic["id"]]
                corrects = earlier[-1]["id"] if earlier else None
            stored.append(store.submit_record(
                user, topic["id"], f"[MOCK] Record {i}",
                f"Synthetic example record {i}. It is not based on a real case.",
                make_data(rng, opts, full=i % 4 != 0), corrects=corrects,
                reason="Synthetic correction." if corrects else ""))
        return stored
    finally:
        if not upload:
            store.run_pipeline = original


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--user" not in argv:
        print(__doc__)
        return 2
    user = argv[argv.index("--user") + 1]
    count = int(argv[argv.index("--records") + 1]) if "--records" in argv else 20
    stored = generate(user, count, upload="--no-upload" not in argv)
    synced = sum(r["sync_status"] == store.SYNCED for r in stored)
    print(f"Created {len(stored)} synthetic records for {user}: {synced} in the database.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
