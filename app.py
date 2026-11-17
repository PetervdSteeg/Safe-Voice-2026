"""SafeVoice UI prototype (dummy data).

Run with:  streamlit run app.py

Structure: Login > Topics > topic (its records) > record (details and history).
Topics and records are stored in SQLite (ui/store.py) and sent through the pipeline on submit.
"""

import time

import streamlit as st

from ui import audit, auth, views
from ui import store
from ui.nav import current, go

st.set_page_config(page_title="SafeVoice", page_icon=":material/shield_lock:", layout="wide")

# Small cosmetic tweaks: left-align the topic buttons in the sidebar, cut off long
# topic names with "…", and reduce the empty space at the top of the page.
# This CSS depends on Streamlit internals and may need updating after a Streamlit upgrade.
st.markdown(
    """<style>
    section[data-testid="stSidebar"] button[data-testid^="stBaseButton"],
    section[data-testid="stSidebar"] button[data-testid^="stBaseButton"] > div { justify-content: flex-start; text-align: left; }
    section[data-testid="stSidebar"] button[data-testid^="stBaseButton"] { padding-left: 0.75rem; }
    section[data-testid="stSidebar"] button p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    [data-testid="stMainBlockContainer"] { padding-top: 2.5rem; }
    </style>""",
    unsafe_allow_html=True,
)

user = st.session_state.get("user")
if user and auth.idle_expired(st.session_state.get("last_seen"), time.time()):
    # Checked on every interaction: an idle session is closed before anything is shown (P2-4).
    audit.log(user, "idle_logout")
    auth.end_session(st.session_state, "You were logged out after a period of inactivity.")
    user = None
if not user:
    views.login_page()
    st.stop()
st.session_state["last_seen"] = time.time()

view, topic_id, record_id = current()
topic = store.get_topic(user, topic_id) if topic_id else None
record = store.get_record(user, record_id) if record_id else None

views.sidebar(user, topic["id"] if topic else None)

# Unknown or not-owned IDs fall back to the topic overview (ownership check).
if (topic_id and not topic) or (record_id and (not record or record["topic_id"] != topic_id)):
    audit.log(user, "access_denied", detail=f"topic={topic_id} record={record_id}")
    st.warning("This topic or record doesn't exist, or you don't have access to it.")
    if st.button("Back to topics"):
        go()
    st.stop()

if view == "new_topic":
    views.new_topic_page(user)
elif topic and view == "new_record":
    views.record_form(user, topic)
elif record and view == "correct":
    views.record_form(user, topic, original=record)
elif record:
    views.record_page(user, topic, record)
elif topic:
    views.topic_page(user, topic)
else:
    views.topic_overview(user)
