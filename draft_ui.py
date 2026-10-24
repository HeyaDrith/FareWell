"""Optional Streamlit draft panel; applying it never searches or moves money."""
from datetime import date, timedelta
from hashlib import sha256
import os

from pydantic import ValidationError
import streamlit as st

import trip_draft


def _fingerprint(text: str, image: bytes | None) -> str:
    return sha256(text.encode("utf-8") + b"\0" + (image or b"")).hexdigest()


def _clear_review():
    for key in list(st.session_state):
        if key.startswith("draft_review_"):
            del st.session_state[key]


def _remember(draft: trip_draft.TripDraft, text: str, image: bytes | None, *, example=False):
    _clear_review()
    st.session_state.ai_draft = draft.model_dump(mode="json")
    st.session_state.ai_source = _fingerprint(text, image)
    st.session_state.ai_example = example


def _clear_input():
    # New widget IDs discard the previous text/upload on the next render.
    st.session_state.ai_input_version = st.session_state.get("ai_input_version", 0) + 1
    for key in ("ai_draft", "ai_source", "ai_example"):
        st.session_state.pop(key, None)
    _clear_review()


def _load_example():
    _clear_input()
    text, draft = trip_draft.example_draft()
    st.session_state[f"ai_chat_{st.session_state.ai_input_version}"] = text
    _remember(draft, text, None, example=True)


def render_draft_panel(demo: bool):
    with st.expander("Turn our group chat into a trip", expanded=False):
        st.write("Paste the plans everyone has been discussing, or add a screenshot. Review the draft before using it.")
        st.caption("When you click Create trip draft, the submitted text and screenshot pixels go to Google Gemini. "
                   "Remove names and private details first. The app does not save uploads to disk.")
        example_col, clear_col = st.columns(2)
        example_col.button("Load example draft (no API)", on_click=_load_example)
        clear_col.button("Clear chat and draft", on_click=_clear_input)
        version = st.session_state.get("ai_input_version", 0)
        text = st.text_area("Group chat or trip ideas", key=f"ai_chat_{version}",
                            max_chars=trip_draft.MAX_TEXT, height=150,
                            placeholder="Where from, where to, dates, budget, and what everyone wants to do...")
        upload = st.file_uploader("Screenshot (optional, PNG/JPEG, up to 4 MB)", type=["png", "jpg", "jpeg"],
                                  key=f"ai_upload_{version}", max_upload_size=4)
        image = None
        if upload is not None:
            if upload.size > trip_draft.MAX_IMAGE_BYTES:
                st.warning("Choose a screenshot up to 4 MB.")
                return
            image = upload.getvalue()
        has_key = bool(os.getenv("GEMINI_API_KEY", "").strip())
        if demo:
            st.caption("Demo mode makes no Gemini calls. Use the example, or turn off Demo mode for Gemini.")
        elif not has_key:
            st.caption("Gemini is not configured yet. Use the example or the manual trip form.")
        if st.button("Create trip draft", disabled=demo or not has_key or not (text.strip() or image)):
            # A failed new attempt must not leave an old draft looking current.
            st.session_state.pop("ai_draft", None)
            _clear_review()
            try:
                with st.spinner("Turning the conversation into a draft..."):
                    draft = trip_draft.extract_trip(text, image, demo=demo)
            except trip_draft.DraftError as error:
                st.error(str(error))
            else:
                _remember(draft, text, image)

        if "ai_draft" not in st.session_state:
            return
        if st.session_state.ai_source != _fingerprint(text, image):
            st.info("The chat or screenshot changed. Create a new draft before applying it.")
            return
        draft = trip_draft.TripDraft.model_validate(st.session_state.ai_draft)
        if st.session_state.ai_example:
            st.info("Offline example draft. This is not a Gemini analysis of your chat.")
        st.write("**Review the draft**")
        # Render model-supplied text as plain text, never as HTML/Markdown links.
        if draft.summary:
            st.text(draft.summary)
        if draft.conflicts:
            st.warning("The conversation contains disagreements. Resolve these before applying the draft.")
            for conflict in draft.conflicts:
                st.text(conflict)
        questions = trip_draft.review_questions(draft)
        if questions:
            st.write("**Details to confirm**")
            for question in questions:
                st.text(question)
        _render_review(draft)


def _render_review(draft: trip_draft.TripDraft):
    today = date.today()
    latest = today + timedelta(days=3650)

    def editable_date(value):
        return value if value and today <= value <= latest else None

    with st.form("draft_review_form"):
        left, right = st.columns(2)
        origin = left.text_input("Draft departure airport", draft.origin or "", key="draft_review_origin", max_chars=3)
        destination = right.text_input("Draft arrival airport", draft.destination or "", key="draft_review_destination", max_chars=3)
        city = st.text_input("Draft hotel city", draft.city or "", key="draft_review_city", max_chars=100)
        depart = left.date_input("Draft departure date", editable_date(draft.depart), min_value=today,
                                 max_value=latest, key="draft_review_depart")
        return_date = right.date_input("Draft return date", editable_date(draft.return_date), min_value=today,
                                       max_value=latest, key="draft_review_return")
        travelers = left.number_input("Travelers (optional)", min_value=1, max_value=20,
                                      value=draft.travelers, key="draft_review_travelers")
        budget = right.text_input("Budget limit (optional)", "" if draft.budget is None else str(draft.budget),
                                   key="draft_review_budget", max_chars=20)
        scopes = ["unknown", "per_person", "group"]
        scope = left.selectbox("Budget applies to", scopes, index=scopes.index(draft.budget_scope),
                                format_func=lambda value: {"unknown": "Not sure yet", "per_person": "Each person", "group": "Whole group"}[value],
                                key="draft_review_scope")
        currencies = ["unknown", "USD", "other"]
        currency = right.selectbox("Budget currency", currencies, index=currencies.index(draft.currency),
                                    key="draft_review_currency")
        interests = st.text_area("Preferences (one per line, up to 8)", "\n".join(draft.interests),
                                 max_chars=1920, key="draft_review_interests")
        st.caption("Group size, preferences, and group budgets are planning notes. Search currently quotes "
                   "one traveler and one room; it does not price the whole group or book activities.")
        acknowledged = st.checkbox("I reviewed the airports and dates and resolved any disagreements.",
                                    key="draft_review_acknowledged")
        submitted = st.form_submit_button("Apply reviewed draft")
    if not submitted:
        return
    if not acknowledged:
        st.warning("Review the draft and check the confirmation box before applying it.")
        return
    try:
        reviewed = trip_draft.TripDraft(
            origin=origin.strip().upper() or None, destination=destination.strip().upper() or None,
            city=city.strip() or None, depart=depart, return_date=return_date,
            travelers=travelers, budget=float(budget) if budget.strip() else None,
            budget_scope=scope, currency=currency,
            interests=[line.strip() for line in interests.splitlines() if line.strip()],
        )
        fields = trip_draft.confirmed_search_fields(reviewed)
    except trip_draft.DraftError as error:
        st.warning(str(error))
        return
    except (ValidationError, ValueError):
        st.warning("Use three-letter airport codes, a positive budget up to 1,000,000, and up to eight short preferences.")
        return
    # Only this explicit submission writes into the manual form; no search/funding side effects.
    st.session_state.update(fields)
    st.session_state.confirmed_trip_notes = reviewed.model_dump(mode="json")
    # Preserve the user's savings schedule unless the newly reviewed trip invalidates it.
    deadline = st.session_state.get("deadline")
    if not isinstance(deadline, date) or not today <= deadline <= reviewed.depart:
        st.session_state["deadline"] = min(today + timedelta(days=60), reviewed.depart)
    st.success("Draft applied. Check the trip fields below, then select Search prices.")


def render_planning_notes(search_fields: dict, budget: float | None = None):
    """Show notes only while the manual form still matches the confirmed draft."""
    raw = st.session_state.get("confirmed_trip_notes")
    if not raw:
        return
    reviewed = trip_draft.TripDraft.model_validate(raw)
    try:
        confirmed_fields = trip_draft.confirmed_search_fields(reviewed)
    except trip_draft.DraftError:
        return  # An old draft must not block a freshly edited manual trip.
    if confirmed_fields != search_fields:
        return
    if budget is None:
        if reviewed.travelers:
            st.caption(f"Planning for {reviewed.travelers} traveler(s). Prices below cover one traveler and one room.")
        if reviewed.interests:
            st.text("Preferences: " + "; ".join(reviewed.interests))
        if reviewed.budget is not None and reviewed.budget_scope == "group":
            st.caption(f"Group budget note: USD {reviewed.budget:,.2f}. A full group quote is still needed.")
    elif reviewed.budget is not None and reviewed.budget_scope == "per_person":
        remaining = round(reviewed.budget - budget, 2)
        message = (f"This one-traveler estimate is USD {abs(remaining):,.2f} "
                   f"{'under' if remaining >= 0 else 'over'} your USD {reviewed.budget:,.2f} per-person limit.")
        (st.info if remaining >= 0 else st.warning)(message)
