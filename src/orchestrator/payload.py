"""Build the pipeline payload for one stored record (P3-3).

The payload has the shape described in config/field_crosswalk.csv:
  {"metadata": {...}, "data": {"record": {...}, "victim": {...}, "incident": {...},
                               "trafficker": {...}, "publication": {...}}}
All IDs are generated here from the record ID, never typed by a user (P1-1 decisions).
"""
import re
from datetime import date, datetime

import pandas as pd

# IDs and usernames that may appear in file names or IRIs (P2-3).
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_safe_id(value):
    return isinstance(value, str) and bool(SAFE_ID.fullmatch(value))


def _clean(value):
    """JSON-safe copy: dates as ISO strings, empty text as None."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, str) and not value.strip():
        return None
    return value


def build_payload(record):
    """`record` is a stored record dict (see ui/store.py). Returns the nested payload."""
    rid = record["id"]
    suffix = rid.split("-", 1)[-1]
    data = _clean(record["data"])
    incident = data.get("incident") or {}
    return {
        "metadata": {"submitted_by": record["owner"], "submitted_at": record["submitted"].isoformat()},
        "data": {
            "record": {
                "record_id": rid,
                "source_id": record["owner"],       # the logged-in user
                "topic_id": record["topic_id"],
                "title": record["title"],
                "narrative": record["narrative"],
                "date_recorded": record["submitted"].date().isoformat(),
                "corrects": record["corrects"],
                "correction_reason": record["reason"] or None,
            },
            "victim": {"victim_id": f"V-{suffix}", **(data.get("victim") or {})},
            "incident": {"incident_id": f"I-{suffix}", **incident},
            "trafficker": {"trafficker_id": f"TR-{suffix}", **(data.get("trafficker") or {})},
            "publication": data.get("publication") or {},
        },
    }


def payload_to_frame(payload):
    """Flatten to one row with columns like data_victim_age (same rule as the cleaner)."""
    return pd.json_normalize(payload, sep="_")
