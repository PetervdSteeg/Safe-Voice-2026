"""Navigation helpers.

The current screen is stored in the URL (st.query_params), e.g.
?topic=T-0001&record=R-0142. That keeps the structure simple:
Topics > topic > record.
"""

import streamlit as st


def current():
    """Return (view, topic_id, record_id) from the URL."""
    q = st.query_params
    return q.get("view"), q.get("topic"), q.get("record")


def go(view=None, topic=None, record=None):
    """Navigate to another screen and rerun the script."""
    st.query_params.clear()
    for key, value in (("view", view), ("topic", topic), ("record", record)):
        if value:
            st.query_params[key] = value
    st.rerun()


def breadcrumb(parts):
    """Render a breadcrumb. parts = [(label, target_dict_or_None), ...]; the last part is the current page."""
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        for i, (label, target) in enumerate(parts):
            if i:
                st.markdown(":gray[›]")
            if target is None:
                st.markdown(f":gray[{label}]")
            elif st.button(label, key=f"crumb_{i}", type="tertiary"):
                go(**target)


def flash(message):
    """Show a message on the next screen (after go())."""
    st.session_state["flash"] = message


def flash_error(message):
    """Like flash(), but shown as a warning."""
    st.session_state["flash_error"] = message


def show_flash():
    if msg := st.session_state.pop("flash", None):
        st.success(msg, icon=":material/check_circle:")
    if msg := st.session_state.pop("flash_error", None):
        st.warning(msg, icon=":material/sync_problem:")
