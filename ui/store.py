"""Dummy data store for the UI prototype.

Everything is kept in st.session_state, so data resets when the browser tab is
reloaded. The functions below are the interface the UI uses; later they can be
replaced by the real topic/record model without changing the screens.
"""

import uuid
from datetime import datetime

import streamlit as st


def _new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


def _seed(user):
    """Create example topics and records owned by the logged-in user.

    One topic belongs to "other_user", to show that you can't open other people's topics.
    """
    topics = [
        {"id": "T-0001", "owner": user, "title": "Border crossing 2026",
         "description": "Reports about movements across the Sudan-Libya route.",
         "created": datetime(2026, 10, 3, 10, 12)},
        {"id": "T-0002", "owner": user, "title": "Labour exploitation",
         "description": "Forced labour on farms and construction sites.",
         "created": datetime(2026, 10, 15, 16, 40)},
        {"id": "T-0003", "owner": user, "title": "Online recruitment",
         "description": "Fake job offers shared through social media.",
         "created": datetime(2026, 10, 21, 9, 5)},
        {"id": "T-0004", "owner": "other_user", "title": "Camp transfers",
         "description": "Transfers between refugee camps.",
         "created": datetime(2026, 11, 1, 11, 0)},
    ]
    base = {
        "victim": {"number_of_victims": 8, "nationality": "Eritrea", "gender": None, "age": None,
                   "situation": "En route"},
        "incident": {
            "departure": {"country": "Sudan", "town": "Kassala", "date": None,
                          "latitude": 15.45, "longitude": 36.4},
            "destination": {"country": None, "town": "Tripoli", "date": None,
                            "latitude": None, "longitude": None},
        },
        "trafficker": {"number": 2, "nationality": None, "description": ""},
        "publication": {"name": "", "link": "", "date": None},
    }
    records = [
        {"id": "R-0137", "topic_id": "T-0001", "owner": user, "title": "Witness statement",
         "narrative": "A witness described a truck leaving the camp at night with about twenty people.",
         "submitted": datetime(2026, 11, 4, 13, 20), "corrects": None, "reason": "",
         "data": base},
        {"id": "R-0142", "topic_id": "T-0001", "owner": user, "title": "Group transfer near border",
         "narrative": "A group of around eight people was moved across the border at night by two men. "
                      "They were held in a house for several days before being transported further north.",
         "submitted": datetime(2026, 11, 9, 14, 32), "corrects": None, "reason": "",
         "data": base},
        {"id": "R-0151", "topic_id": "T-0001", "owner": user, "title": "Group transfer near border",
         "narrative": "A group of around eight people was moved across the border at night by two men. "
                      "They were held in a house for several days before being transported further north.",
         "submitted": datetime(2026, 11, 10, 9, 15), "corrects": "R-0142",
         "reason": "Departure town was wrong.",
         "data": {**base, "incident": {**base["incident"],
                                       "departure": {**base["incident"]["departure"], "town": "Wad Sharifey"}}}},
        {"id": "R-0120", "topic_id": "T-0002", "owner": user, "title": "Farm workers without pay",
         "narrative": "Several workers reported that their documents were taken and wages withheld.",
         "submitted": datetime(2026, 11, 2, 8, 45), "corrects": None, "reason": "",
         "data": {"victim": {"number_of_victims": 5}}},
    ]
    return {"topics": topics, "records": records}


def _db():
    if "db" not in st.session_state:
        st.session_state.db = _seed(st.session_state.get("user", "demo"))
    return st.session_state.db


# ---- Topics ----

def get_topics(user):
    """Topics owned by this user, most recently active first."""
    topics = [t for t in _db()["topics"] if t["owner"] == user]
    return sorted(topics, key=last_activity, reverse=True)


def get_topic(user, topic_id):
    """Return the topic only if this user owns it (ownership check, W3-02)."""
    return next((t for t in _db()["topics"] if t["id"] == topic_id and t["owner"] == user), None)


def create_topic(user, title, description):
    topic = {"id": _new_id("T"), "owner": user, "title": title, "description": description,
             "created": datetime.now()}
    _db()["topics"].append(topic)
    return topic


def last_activity(topic):
    times = [r["submitted"] for r in _db()["records"] if r["topic_id"] == topic["id"]]
    return max(times + [topic["created"]])


# ---- Records ----

def get_records(user, topic_id):
    """All records in a topic for this user, oldest first."""
    recs = [r for r in _db()["records"] if r["topic_id"] == topic_id and r["owner"] == user]
    return sorted(recs, key=lambda r: r["submitted"])


def get_record(user, record_id):
    return next((r for r in _db()["records"] if r["id"] == record_id and r["owner"] == user), None)


def get_corrections(user, record_id):
    """Corrections that directly correct this record, oldest first."""
    recs = [r for r in _db()["records"] if r["corrects"] == record_id and r["owner"] == user]
    return sorted(recs, key=lambda r: r["submitted"])


def get_root(user, record):
    """Follow 'corrects' links back to the original record."""
    while record and record["corrects"]:
        record = get_record(user, record["corrects"])
    return record


def get_chain(user, record):
    """Original record followed by all its corrections, in time order."""
    root = get_root(user, record)
    chain, todo = [], [root]
    while todo:
        r = todo.pop(0)
        chain.append(r)
        todo.extend(get_corrections(user, r["id"]))
    return sorted(chain, key=lambda r: r["submitted"])


def submit_record(user, topic_id, title, narrative, data, corrects=None, reason=""):
    """Store a new immutable record. ID and timestamp are generated here (W1-04).

    TODO: call the real pipeline (cleaning, RDF mapping, AllegroGraph ingestion) here.
    """
    record = {"id": _new_id("R"), "topic_id": topic_id, "owner": user, "title": title,
              "narrative": narrative, "submitted": datetime.now(), "corrects": corrects,
              "reason": reason, "data": data}
    _db()["records"].append(record)
    return record
