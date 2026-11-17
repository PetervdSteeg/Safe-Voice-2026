"""The screens of the SafeVoice UI prototype."""

from datetime import date

import pandas as pd
import streamlit as st

from ui import audit, auth, store
from ui.nav import breadcrumb, flash, flash_error, go, show_flash

DROP_DOWN_FILE_PATH = "config/UI_drop_downs.csv"
NOT_PROVIDED = ":gray[Not provided]"


@st.cache_data
def _vocab():
    try:
        df = pd.read_csv(DROP_DOWN_FILE_PATH)
    except Exception:
        return pd.DataFrame()
    df.columns = df.columns.str.strip()
    return df.map(lambda x: x.strip() if isinstance(x, str) else x)


def options(column):
    df = _vocab()
    return df[column].dropna().unique().tolist() if column in df.columns else []


# Day without a leading zero. strftime("%-d") only works with glibc and raises ValueError on Windows.
def fmt_dt(dt):
    return f"{dt.day} {dt:%b %Y, %H:%M}"


def fmt_d(dt):
    return f"{dt.day} {dt:%b}"


# ---------------------------------------------------------------- login

def login_page():
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown("## :material/shield_lock: SafeVoice")
        st.caption("Secure reporting for sources.")
        if notice := st.session_state.pop("notice", None):
            st.info(notice)
        with st.form("login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in", type="primary", width="stretch")
        if submitted:
            user, status, wait = auth.attempt_login(username, password)
            if status == "ok":
                st.session_state.user = user
                audit.log(user, "login")
                go()
            elif status == "locked":
                audit.log(username.strip().lower()[:32], "login_locked")
                st.error(f"Too many failed attempts. Try again in {-(-wait // 60)} minute(s).")
            else:
                audit.log(username.strip().lower()[:32], "login_failed")
                st.error("Invalid username or password.")
        st.caption("Demo login: users are defined in the .env file.")


# ---------------------------------------------------------------- sidebar

def sidebar(user, active_topic):
    with st.sidebar:
        st.markdown("### :material/shield_lock: SafeVoice")
        with st.expander("Topics", expanded=True, icon=":material/folder:"):
            if st.button("All topics", key="sb_all", type="tertiary", width="stretch"):
                go()
            for t in store.get_topics(user):
                kind = "primary" if t["id"] == active_topic else "tertiary"
                if st.button(t["title"], key=f"sb_{t['id']}", type=kind, width="stretch"):
                    go(topic=t["id"])
        st.space("large")
        st.caption(f":material/person: {user}")
        if st.button("Log out", icon=":material/logout:", type="tertiary"):
            audit.log(user, "logout")
            auth.end_session(st.session_state)
            go()


# ---------------------------------------------------------------- topics

def topic_overview(user):
    show_flash()
    breadcrumb([("Topics", None)])
    head, btn = st.columns([4, 1], vertical_alignment="center")
    head.markdown("## Your topics")
    if btn.button("New topic", icon=":material/add:", type="primary", width="stretch"):
        go(view="new_topic")

    query = st.text_input("Search topics", placeholder="Search topics", label_visibility="collapsed",
                          icon=":material/search:")
    topics = [t for t in store.get_topics(user) if query.lower() in t["title"].lower()]
    if not topics:
        st.info("No topics yet. Create a topic to start adding records." if not query
                else "No topics match your search.")
        return

    cols = st.columns(3)
    for i, t in enumerate(topics):
        n = len(store.get_records(user, t["id"]))
        with cols[i % 3].container(border=True):
            if st.button(t["title"], key=f"open_{t['id']}", icon=":material/folder:", type="tertiary"):
                go(topic=t["id"])
            st.caption(f"Created {fmt_d(t['created'])} {t['created']:%Y}  \n"
                       f"{n} record{'s' if n != 1 else ''} · Updated {fmt_d(store.last_activity(t))}")


def new_topic_page(user):
    breadcrumb([("Topics", {}), ("New topic", None)])
    st.markdown("## New topic")
    with st.form("new_topic"):
        title = st.text_input("Title *", placeholder="Border crossing 2026")
        description = st.text_area("Short description", placeholder="What this topic is about")
        c1, c2 = st.columns(2)
        create = c1.form_submit_button("Create topic", type="primary", width="stretch")
        cancel = c2.form_submit_button("Cancel", width="stretch")
    if cancel:
        go()
    if create:
        if not title.strip():
            st.error("Enter a title for the topic.")
        else:
            t = store.create_topic(user, title.strip(), description.strip())
            flash(f"Topic “{t['title']}” created.")
            go(topic=t["id"])


def topic_page(user, topic):
    show_flash()
    breadcrumb([("Topics", {}), (topic["title"], None)])
    head, btn = st.columns([4, 1], vertical_alignment="center")
    head.markdown(f"## {topic['title']}")
    if btn.button("New record", icon=":material/add:", type="primary", width="stretch"):
        go(view="new_record", topic=topic["id"])

    records = store.get_records(user, topic["id"])
    st.caption(f"Created {fmt_dt(topic['created'])} · {len(records)} record{'s' if len(records) != 1 else ''}"
               + (f"  \n{topic['description']}" if topic["description"] else ""))

    originals = [r for r in records if not r["corrects"]]
    if not originals:
        st.info("No records in this topic yet. Add the first record.")
        return

    widths = [3, 1.2, 1.4, 1.2]
    with st.container(border=True):
        for col, label in zip(st.columns(widths), ("Record", "ID", "Submitted", "Status")):
            col.caption(label)
        for r in sorted(originals, key=lambda r: r["submitted"], reverse=True):
            _record_row(user, r, widths, indent=False)
            for c in store.get_chain(user, r)[1:]:
                _record_row(user, c, widths, indent=True)


def _record_row(user, r, widths, indent):
    c1, c2, c3, c4 = st.columns(widths, vertical_alignment="center")
    label = f"↳ Correction: {r['reason'] or r['title']}" if indent else r["title"]
    if c1.button(label, key=f"row_{r['id']}", type="tertiary"):
        go(topic=r["topic_id"], record=r["id"])
    c2.write(r["id"])
    c3.write(fmt_d(r["submitted"]))
    if not indent and store.get_corrections(user, r["id"]):
        c4.markdown(":orange-badge[Corrected]")


# ---------------------------------------------------------------- record detail

def _value(v, digits=None):
    if v is None or v == "":
        return NOT_PROVIDED
    if digits is not None and isinstance(v, (int, float)):
        return f"{v:.{digits}f}"
    if isinstance(v, date):
        return f"{v.day} {v:%b %Y}"
    return str(v)


def _card(title, rows):
    with st.container(border=True, height="stretch"):
        st.markdown(f"**:primary[{title}]**")
        st.markdown("  \n".join(f":gray[{k}:] {v}" for k, v in rows))


def _loc(d):
    d = d or {}
    place = ", ".join(x for x in (d.get("town"), d.get("country")) if x)
    return place or None


def record_page(user, topic, record):
    show_flash()
    breadcrumb([("Topics", {}), (topic["title"], {"topic": topic["id"]}), (record["title"], None)])
    head, btn = st.columns([4, 1.3], vertical_alignment="center")
    head.markdown(f"## {record['title']}")
    if btn.button("Submit correction", icon=":material/edit:", width="stretch"):
        go(view="correct", topic=topic["id"], record=record["id"])

    chain = store.get_chain(user, record)
    newer = [r for r in chain if r["submitted"] > record["submitted"]]
    meta = f":gray[{record['id']} · Submitted {fmt_dt(record['submitted'])}]"
    if record["corrects"]:
        meta += f" :blue-badge[Correction of {record['corrects']}]"
    if newer:
        meta += f" :orange-badge[Corrected by {newer[-1]['id']}]"
    if record["sync_status"] != store.SYNCED:
        meta += " :red-badge[Not yet in the database]"
    st.markdown(meta)
    if record["sync_status"] != store.SYNCED:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.caption(f"{record['sync_message'] or 'Waiting to be sent.'} Your record is saved and nothing is lost.")
            if st.button("Retry", icon=":material/sync:", type="tertiary", key="retry"):
                done = store.retry_sync(user, record["id"])
                if done["sync_status"] == store.SYNCED:
                    flash("Record saved to the database.")
                else:
                    flash_error(f"Still not in the database. {done['sync_message']}")
                go(topic=topic["id"], record=record["id"])
    if not store.verify_record(record):
        st.error("Integrity check failed: this record's content no longer matches what was submitted.")
    if newer:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.caption("You are viewing an older version of this record.")
            if st.button("Open latest version", type="tertiary", key="latest"):
                go(topic=topic["id"], record=newer[-1]["id"])

    with st.container(border=True):
        st.markdown(":gray[:material/notes: Narrative]")
        st.write(record["narrative"])
        if record["reason"]:
            st.caption(f"Reason for correction: {record['reason']}")

    d = record["data"]
    v, inc, tr, pub = d.get("victim", {}), d.get("incident", {}), d.get("trafficker", {}), d.get("publication", {})
    dep, dest = inc.get("departure", {}) or {}, inc.get("destination", {}) or {}
    row1 = st.columns(2)
    with row1[0]:
        _card("Incident", [
            ("Departure", _value(_loc(dep))), ("Departure date", _value(dep.get("date"))),
            ("Destination", _value(_loc(dest))), ("Destination date", _value(dest.get("date"))),
            ("Departure coordinates", _value(", ".join(_value(dep.get(k), 2) for k in ("latitude", "longitude"))
                                             if dep.get("latitude") is not None else None)),
        ])
    with row1[1]:
        _card("Victim", [
            ("Number", _value(v.get("number_of_victims"))), ("Nationality", _value(v.get("nationality"))),
            ("Gender", _value(v.get("gender"))), ("Age", _value(v.get("age"))),
            ("Situation", _value(v.get("situation"))),
        ])
    row2 = st.columns(2)
    with row2[0]:
        _card("Trafficker", [
            ("Number", _value(tr.get("number_of_traffickers"))), ("Name or alias", _value(tr.get("name"))),
            ("Nationality", _value(tr.get("nationality"))), ("Description", _value(tr.get("description"))),
        ])
    with row2[1]:
        _card("Publication", [
            ("Name", _value(pub.get("name"))), ("Link", _value(pub.get("link"))), ("Date", _value(pub.get("date"))),
        ])

    with st.container(border=True):
        st.markdown(":gray[:material/attach_file: Documents]")
        st.caption("Document upload is not part of this prototype yet.")

    with st.container(border=True):
        st.markdown(":gray[:material/history: History]")
        for r in reversed(chain):
            kind = "Correction" if r["corrects"] else "Original record"
            here = " · viewing" if r["id"] == record["id"] else ""
            c1, c2 = st.columns([3, 2], vertical_alignment="center")
            if c1.button(f"{r['id']} {kind}", key=f"hist_{r['id']}", type="tertiary",
                         disabled=r["id"] == record["id"]):
                go(topic=topic["id"], record=r["id"])
            c2.caption(f"{fmt_dt(r['submitted'])}{here}" + (f"  \n{r['reason']}" if r["reason"] else ""))


# ---------------------------------------------------------------- record form

REQUIRED = {"title": "Record name", "narrative": "Narrative"}


def _select(label, column, key, current):
    opts = options(column)
    if current and current not in opts:
        opts = [current] + opts
    return st.selectbox(label, opts, index=opts.index(current) if current in opts else None,
                        placeholder="Select…", key=key)


def _location_fields(prefix, title, cur):
    cur = cur or {}
    st.markdown(f"**{title}**")
    c1, c2, c3 = st.columns(3)
    with c1:
        country = _select("Country", "Country", f"{prefix}_country", cur.get("country"))
    with c2:
        town = st.text_input("Town or village", value=cur.get("town") or "", key=f"{prefix}_town")
    with c3:
        when = st.date_input("Date", value=cur.get("date"), key=f"{prefix}_date", format="DD/MM/YYYY")
    c4, c5, c6 = st.columns(3)
    with c4:
        lat = st.number_input("Latitude", value=cur.get("latitude"), format="%.4f", key=f"{prefix}_lat",
                              placeholder="Not provided")
    with c5:
        lon = st.number_input("Longitude", value=cur.get("longitude"), format="%.4f", key=f"{prefix}_lon",
                              placeholder="Not provided")
    with c6:
        loc_type = _select("Location type", "Type of location", f"{prefix}_type", cur.get("type"))
    return {"country": country, "town": town.strip(), "date": when, "latitude": lat, "longitude": lon,
            "type": loc_type}


def _validate(title, narrative, data):
    errors = []
    if not title.strip():
        errors.append("Enter a name for the record.")
    if not narrative.strip():
        errors.append("Write the narrative.")
    today = date.today()
    inc = data["incident"]
    for name, loc in (("Departure", inc["departure"]), ("Destination", inc["destination"])):
        if loc["date"] and loc["date"] > today:
            errors.append(f"{name} date can't be in the future.")
        lat, lon = loc["latitude"], loc["longitude"]
        if lat is not None and not -90 <= lat <= 90:
            errors.append(f"{name} latitude must be between -90 and 90.")
        if lon is not None and not -180 <= lon <= 180:
            errors.append(f"{name} longitude must be between -180 and 180.")
        if (lat is None) != (lon is None):
            errors.append(f"{name}: enter both latitude and longitude, or neither.")
    d1, d2 = inc["departure"]["date"], inc["destination"]["date"]
    if d1 and d2 and d1 > d2:
        errors.append("Departure date must be before the destination date.")
    age = data["victim"]["age"]
    if age is not None and not 0 <= age <= 120:
        errors.append("Age must be between 0 and 120.")
    pub = data["publication"]
    if pub["link"] and not pub["link"].startswith(("http://", "https://")):
        errors.append("Publication link must start with http:// or https://.")
    if pub["date"] and pub["date"] > today:
        errors.append("Publication date can't be in the future.")
    return errors


@st.dialog("Submit this record?")
def _confirm(user, topic, payload):
    st.write("Submitted records can't be changed afterwards. To fix a mistake later, "
             "you can submit a correction.")
    st.markdown(f"**{payload['title']}**  \n:gray[Topic: {topic['title']}]")
    c1, c2 = st.columns(2)
    if c1.button("Submit", type="primary", width="stretch"):
        rec = store.submit_record(user, topic["id"], **payload)
        if rec["sync_status"] == store.SYNCED:
            flash(f"Record {rec['id']} submitted and saved to the database.")
        else:
            flash_error(f"Record {rec['id']} is saved, but not yet in the database. {rec['sync_message']} "
                        "You can retry from the record page.")
        go(topic=topic["id"], record=rec["id"])
    if c2.button("Go back", width="stretch"):
        st.rerun()


def record_form(user, topic, original=None):
    """New record form. With `original`, it becomes a pre-filled correction form."""
    fid = f"corr_{original['id']}" if original else f"new_{topic['id']}"
    if original:
        breadcrumb([("Topics", {}), (topic["title"], {"topic": topic["id"]}),
                    (original["title"], {"topic": topic["id"], "record": original["id"]}), ("Correction", None)])
        st.markdown("## Submit a correction")
        st.caption(f"Correcting {original['id']}. The original record stays unchanged; "
                   "your correction is saved as a new record linked to it.")
    else:
        breadcrumb([("Topics", {}), (topic["title"], {"topic": topic["id"]}), ("New record", None)])
        st.markdown("## New record")
        st.caption(f"Topic: {topic['title']} · Fields marked * are required. Leave anything you don't know empty.")

    cur = (original or {}).get("data", {})
    cv, ci, ct, cp = (cur.get(k, {}) or {} for k in ("victim", "incident", "trafficker", "publication"))

    title = st.text_input("Record name *", value=(original or {}).get("title", ""), key=f"{fid}_title",
                          placeholder="Short name, e.g. Group transfer near border")
    narrative = st.text_area("Narrative *", value=(original or {}).get("narrative", ""), key=f"{fid}_narr",
                             height=180, placeholder="Describe what happened in your own words.",
                             help="Write what you know. Structured details below are optional.")
    reason = ""
    if original:
        reason = st.text_input("Reason for correction", key=f"{fid}_reason",
                               placeholder="What was wrong in the original record?")

    st.markdown("#### Details (optional)")
    with st.expander("Incident: departure and destination", icon=":material/route:"):
        dep = _location_fields(f"{fid}_dep", "Departure", ci.get("departure"))
        st.divider()
        dest = _location_fields(f"{fid}_dest", "Destination", ci.get("destination"))
    with st.expander("Victim", icon=":material/person:"):
        c1, c2, c3 = st.columns(3)
        n_vic = c1.number_input("Number of victims", min_value=1, step=1, value=cv.get("number_of_victims"),
                                key=f"{fid}_nvic", placeholder="Not provided")
        with c2:
            nat = _select("Nationality", "Nationality", f"{fid}_vnat", cv.get("nationality"))
        with c3:
            gender = _select("Gender", "Gender", f"{fid}_gender", cv.get("gender"))
        c4, c5 = st.columns(2)
        age = c4.number_input("Age", min_value=0, max_value=120, step=1, value=cv.get("age"),
                              key=f"{fid}_age", placeholder="Not provided")
        with c5:
            situation = _select("Situation", "Situation", f"{fid}_sit", cv.get("situation"))
    with st.expander("Trafficker", icon=":material/person_alert:"):
        c1, c2, c3 = st.columns(3)
        n_tr = c1.number_input("Number of traffickers", min_value=1, step=1, value=ct.get("number_of_traffickers"),
                               key=f"{fid}_ntr", placeholder="Not provided")
        tr_name = c2.text_input("Name or alias", value=ct.get("name") or "", key=f"{fid}_trname")
        with c3:
            tr_nat = _select("Nationality", "Nationality", f"{fid}_trnat", ct.get("nationality"))
        tr_desc = st.text_area("Description", value=ct.get("description") or "", key=f"{fid}_trdesc",
                               placeholder="Non-identifying details only.")
    with st.expander("Publication", icon=":material/article:"):
        c1, c2, c3 = st.columns(3)
        pub_name = c1.text_input("Publication name", value=cp.get("name") or "", key=f"{fid}_pubname")
        pub_link = c2.text_input("Link", value=cp.get("link") or "", key=f"{fid}_publink",
                                 placeholder="https://")
        pub_date = c3.date_input("Date", value=cp.get("date"), key=f"{fid}_pubdate", format="DD/MM/YYYY")

    data = {
        "victim": {"number_of_victims": n_vic, "nationality": nat, "gender": gender, "age": age,
                   "situation": situation},
        "incident": {"departure": dep, "destination": dest},
        "trafficker": {"number_of_traffickers": n_tr, "name": tr_name.strip(), "nationality": tr_nat,
                       "description": tr_desc.strip()},
        "publication": {"name": pub_name.strip(), "link": pub_link.strip(), "date": pub_date},
    }

    st.write("")
    c1, c2, _ = st.columns([1.3, 1, 3])
    submit = c1.button("Review and submit", type="primary", width="stretch")
    if c2.button("Cancel", width="stretch"):
        if original:
            go(topic=topic["id"], record=original["id"])
        go(topic=topic["id"])
    if submit:
        errors = _validate(title, narrative, data)
        if errors:
            st.error("Some fields need attention:\n\n" + "\n".join(f"- {e}" for e in errors))
        else:
            _confirm(user, topic, {"title": title.strip(), "narrative": narrative.strip(), "data": data,
                                   "corrects": original["id"] if original else None,
                                   "reason": reason.strip()})
