"""W1-06: an untouched form must not submit plausible but false values (0.0 coordinates, first drop-down option)."""
from streamlit.testing.v1 import AppTest


def _form():
    from ui import views
    views.record_form("alice", {"id": "T-1", "title": "Topic"})


def test_untouched_form_has_no_default_values():
    at = AppTest.from_function(_form, default_timeout=60).run()
    assert not at.exception
    assert len(at.number_input) >= 7 and len(at.selectbox) >= 6
    assert all(n.value is None for n in at.number_input), [n.label for n in at.number_input if n.value is not None]
    assert all(s.value is None for s in at.selectbox), [s.label for s in at.selectbox if s.value is not None]
    assert all(d.value is None for d in at.date_input)


def test_empty_form_cannot_be_submitted():
    at = AppTest.from_function(_form, default_timeout=60).run()
    next(b for b in at.button if b.label == "Review and submit").click().run()
    assert any("Enter a name for the record." in e.value for e in at.error)
    assert any("Write the narrative." in e.value for e in at.error)
