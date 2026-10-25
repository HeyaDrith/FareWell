"""Optional Streamlit draft panel; applying it never searches or moves money."""
from datetime import date, timedelta
from hashlib import sha256
import os
import re

from pydantic import ValidationError
import streamlit as st

import travel
import trip_draft

# When the chat gives no usable dates, suggest a week-long trip about a month out, so the
# draft can still be applied and searched (the user can change them before applying).
SUGGEST_LEAD_DAYS, SUGGEST_NIGHTS = 30, 7
PANEL_KEY = "chat_panel"  # the panel's open/closed state, set by the start choices and the homepage link


def open_panel():
    st.session_state[PANEL_KEY] = True


def close_panel():
    st.session_state[PANEL_KEY] = False


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


def _voice_input(version: int, demo: bool, has_key: bool):
    """🎤 Record, and Gemini writes what you said into the trip box (added to anything typed).

    Runs before the text box is drawn, because a widget's text can only be set before it exists
    in a run. Each recording is written down once; a new recording adds a new paragraph.
    """
    off = demo or not has_key
    why = ("Turn off Demo AI drafts in Data sources to use voice." if demo else
           "Voice needs Gemini: add `GEMINI_API_KEY` to `.env` (or Streamlit secrets) and restart the app."
           if off else "")
    recording = st.audio_input("🎤 Talk instead of typing", key=f"ai_voice_{version}", disabled=off,
                               help="Record your trip ideas; Gemini writes them into the box below, where you "
                                    "can edit them. " + why)
    if off:
        st.caption(f"🎤 Voice is off. {why}")  # said plainly, not only in the hover help
    if recording is None:
        return
    audio = recording.getvalue()
    heard = sha256(audio).hexdigest()
    if st.session_state.get("ai_voice_heard") == heard:
        return
    st.session_state.ai_voice_heard = heard
    try:
        with st.spinner("Writing down what you said..."):
            words = trip_draft.transcribe(audio, demo=demo)
    except trip_draft.DraftError as error:
        st.error(str(error))
        return
    box = f"ai_chat_{version}"
    before = (st.session_state.get(box) or "").rstrip()
    st.session_state[box] = (f"{before}\n\n{words}" if before else words)[:trip_draft.MAX_TEXT]
    st.success("Added what you said to the box below. Check it, then click Create trip draft.")


def render_draft_panel(demo: bool):
    with st.expander("Plan from your group chat", icon="💬", key=PANEL_KEY, on_change="rerun"):
        st.write("Paste the plans everyone has been discussing, say them out loud, or add a screenshot. "
                 "Review the draft before using it.")
        st.caption("When you click Create trip draft, the submitted text and screenshot pixels go to Google Gemini; "
                   "voice recordings go to Gemini to be written down. Remove names and private details first. "
                   "The app does not save uploads or recordings to disk.")
        example_col, clear_col = st.columns(2)
        example_col.button("Load example draft (no API)", on_click=_load_example)
        clear_col.button("Clear chat and draft", on_click=_clear_input)
        version = st.session_state.get("ai_input_version", 0)
        has_key = bool(os.getenv("GEMINI_API_KEY", "").strip())
        _voice_input(version, demo, has_key)
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
        if demo:
            st.caption("Demo mode makes no Gemini calls. Use the example, or turn off Demo mode for Gemini.")
        elif not has_key:
            st.caption("Gemini is not configured yet: add `GEMINI_API_KEY=<your key>` to the `.env` file "
                       "(or Streamlit secrets), then reload the page. Meanwhile, use the example or the manual form.")
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
            st.warning("The conversation contains disagreements. " + (
                "Pick one of the plans below to fill in the draft, or edit the fields yourself."
                if draft.plans else "Resolve these before applying the draft."))
            for conflict in draft.conflicts:
                st.text(conflict)
        questions = trip_draft.review_questions(draft)
        if questions:
            st.write("**Details to confirm**")
            for question in questions:
                st.text(question)
        _render_review(draft)


def _plain(text: str) -> str:
    """Model-written text shown in a widget label: drop markdown/HTML syntax, keep the words."""
    return re.sub(r"[\\`*_\[\]()#<>$|~]", "", str(text)).strip()


def _fill(source, today: date) -> tuple[dict, list[str]]:
    """Review-form values for the draft or a picked plan, with gaps filled so a search can run.

    Missing airports come from the trip form, a missing hotel city from the arrival airport,
    and missing or unusable dates become a suggested week about a month out. Returns the
    widget values and a note for each filled-in value.
    """
    ss = st.session_state
    latest = today + timedelta(days=3650)
    notes = []
    origin = source.origin or (ss.get("trip_origin") or "")
    if origin and not source.origin:
        notes.append(f"departure airport {origin} (from your trip form)")
    destination = source.destination or (ss.get("trip_destination") or "")
    if destination and not source.destination:
        notes.append(f"arrival airport {destination} (from your trip form)")
    city = source.city or travel.airport_city(destination) or ""
    if city and not source.city:
        notes.append(f"hotel city {_plain(city)} (from the arrival airport)")

    def usable(day):
        return day if day and today <= day <= latest else None
    depart, ret = usable(source.depart), usable(source.return_date)
    if depart and ret and ret <= depart:
        ret = None
    if not depart:
        depart = (ret - timedelta(days=SUGGEST_NIGHTS) if ret and ret - timedelta(days=SUGGEST_NIGHTS) >= today
                  else today + timedelta(days=SUGGEST_LEAD_DAYS))
    if not ret or ret <= depart:
        ret = depart + timedelta(days=SUGGEST_NIGHTS)
    if (depart, ret) != (source.depart, source.return_date):
        notes.append(f"dates {depart:%b %d} - {ret:%b %d, %Y} (the chat had no usable dates)"
                     if not (usable(source.depart) or usable(source.return_date))
                     else f"dates {depart:%b %d} - {ret:%b %d, %Y} (completed from the chat)")
    values = {"draft_review_origin": origin, "draft_review_destination": destination,
              "draft_review_city": city, "draft_review_depart": depart, "draft_review_return": ret}
    return values, notes


def _pick_plan():
    """Picking a plan from the chat autofills the review form (runs before the widgets)."""
    ss = st.session_state
    choice = ss.get("draft_review_plan")
    draft = trip_draft.TripDraft.model_validate(ss.ai_draft)
    if choice is None or not 0 <= choice < len(draft.plans):
        return
    values, notes = _fill(draft.plans[choice], date.today())
    ss.update(values)
    ss.draft_review_notes = notes


def _plan_label(plan: trip_draft.PlanOption) -> str:
    route = " → ".join(code for code in (plan.origin, plan.destination) if code)
    dates = (f"{plan.depart:%b %d} - {plan.return_date:%b %d}" if plan.depart and plan.return_date
             else f"from {plan.depart:%b %d}" if plan.depart else "no dates given")
    return " · ".join(part for part in (_plain(plan.label), route, dates) if part)


def _render_review(draft: trip_draft.TripDraft):
    ss = st.session_state
    today = date.today()
    latest = today + timedelta(days=3650)
    if "draft_review_origin" not in ss:  # a new draft: start from it, gaps filled
        values, notes = _fill(draft, today)
        ss.update(values)
        ss.draft_review_notes = notes
        ss.update({"draft_review_travelers": draft.travelers,
                   "draft_review_budget": "" if draft.budget is None else str(draft.budget),
                   "draft_review_scope": draft.budget_scope, "draft_review_currency": draft.currency,
                   "draft_review_interests": "\n".join(draft.interests)})

    if draft.plans:
        st.write("**Pick a plan to fill in the draft**")
        st.radio("Plans from the chat", range(len(draft.plans)), index=None, key="draft_review_plan",
                 format_func=lambda i: _plan_label(draft.plans[i]), on_change=_pick_plan,
                 label_visibility="collapsed")
    if ss.get("draft_review_notes"):
        # Notes are built by _fill from airport codes, dates and the airport table (city text
        # cleaned there); "$" is escaped so markdown can't turn it into math.
        st.info("Filled in so you can search right away (change anything below): "
                + "; ".join(ss.draft_review_notes).replace("$", "\\$") + ".")

    with st.form("draft_review_form"):
        left, right = st.columns(2)
        origin = left.text_input("Draft departure airport", key="draft_review_origin", max_chars=3)
        destination = right.text_input("Draft arrival airport", key="draft_review_destination", max_chars=3)
        city = st.text_input("Draft hotel city (optional)", key="draft_review_city", max_chars=100,
                             help="Hotels are searched where the flight lands. A different city here "
                                  "(e.g. Tulum when flying into Cancún) narrows that search.")
        depart = left.date_input("Draft departure date", min_value=today, max_value=latest, key="draft_review_depart")
        return_date = right.date_input("Draft return date", min_value=today, max_value=latest, key="draft_review_return")
        travelers = left.number_input("Travelers (optional)", min_value=1, max_value=20, key="draft_review_travelers")
        budget = right.text_input("Budget limit (optional)", key="draft_review_budget", max_chars=20)
        scopes = ["unknown", "per_person", "group"]
        scope = left.selectbox("Budget applies to", scopes,
                                format_func=lambda value: {"unknown": "Not sure yet", "per_person": "Each person", "group": "Whole group"}[value],
                                key="draft_review_scope")
        currencies = ["unknown", "USD", "other"]
        currency = right.selectbox("Budget currency", currencies, key="draft_review_currency")
        interests = st.text_area("Preferences (one per line, up to 8)", max_chars=1920, key="draft_review_interests")
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
    # The trip form only takes airports from its list, so a draft can't bring in any other.
    unknown = [code for code in (reviewed.origin, reviewed.destination) if not travel.airport_location(code)]
    if unknown:
        st.warning(f"{', '.join(unknown)} isn't in the airport list. Use an airport from the From/To lists.")
        return
    # Only this explicit submission writes into the manual form; no search/funding side effects.
    st.session_state.update(fields)
    st.session_state.confirmed_trip_notes = reviewed.model_dump(mode="json")
    # A per-person USD budget becomes the trip budget (the app plans for one traveler);
    # a group budget stays a planning note.
    if reviewed.budget is not None and reviewed.budget_scope == "per_person":
        st.session_state["trip_budget"] = int(min(50000, max(50, round(reviewed.budget))))
    st.success("Draft applied. Check the trip fields below, then select Start planning.")


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
