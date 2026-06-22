from __future__ import annotations

import re

import streamlit as st

_STRIP_WORDS = {
    "dental", "dentistry", "smile", "smiles", "family", "associates",
    "llc", "inc", "pllc", "dds", "dmd", "dr", "doctor", "office", "care",
    "center", "group", "practice", "clinic",
}


def normalize_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^\w\s]", " ", name)
    tokens = [t for t in name.split() if t not in _STRIP_WORDS]
    return " ".join(tokens).strip()


def miles_to_meters(miles: int) -> int:
    return int(miles * 1609.34)


def truncate(text: str, max_len: int = 200) -> str:
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def extract_city(formatted_address: str) -> str:
    if not formatted_address:
        return ""
    parts = [p.strip() for p in formatted_address.split(",")]
    if len(parts) >= 3:
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else ""


def get_hours_summary(opening_hours: dict | None) -> str:
    if not opening_hours:
        return "Hours not available"
    weekday_text = opening_hours.get("weekday_text")
    if weekday_text:
        return "; ".join(weekday_text)
    return "Hours not available"


# ── Pain score badge HTML ─────────────────────────────────────────────────────

def _pain_badge(val: float) -> str:
    if val >= 6:
        bg, color = "#fef2f2", "#b91c1c"
    elif val >= 4:
        bg, color = "#fff7ed", "#c2410c"
    elif val >= 2:
        bg, color = "#fefce8", "#854d0e"
    else:
        bg, color = "#f0fdf4", "#166534"
    return (
        f"<span class='ps-badge' style='background:{bg};color:{color}'>"
        f"Pain Score {val}"
        f"</span>"
    )


# ── Shared lead card renderer ─────────────────────────────────────────────────

def render_lead_card(row: dict) -> None:
    """Render a mini-summary lead card inside an expander.

    ``row`` may be a dict (from Supabase) or a pandas Series from leads_df.
    All keys match the column names used in pages/leads.py final_leads dicts,
    with lowercase Supabase column names also accepted (e.g. ``pain_score``
    instead of ``Pain Score``).
    """

    def _get(primary: str, fallback: str = "", default=""):
        v = row.get(primary)
        if v is None or (isinstance(v, float) and v != v):  # None or NaN
            v = row.get(fallback, default)
        return v if v is not None else default

    # Resolve column names (DataFrame uses title case, Supabase uses snake_case)
    score    = _get("Pain Score",       "pain_score",      0)
    phone    = _get("Phone Number",     "phone",           "")
    website  = _get("Website",          "website",         "")
    address  = _get("Address",          "address",         "")
    specialty   = _get("Specialty",     "specialty",       "")
    classif     = _get("Classification","classification",  "")
    rating      = _get("Google Rating", "rating",          "")
    total_rev   = int(_get("Total Reviews", "total_reviews", 0) or 0)
    hours       = _get("Hours Summary", "",                "")
    ext_hours   = _get("Extended Hours","extended_hours",  "")
    online_bkg  = _get("Online Booking","online_booking",  "")
    depth       = _get("Review Data Depth", "review_depth", "")
    signals_raw = _get("Pain Signal Type",  "signals",     "")
    outreach    = _get("Outreach Angle",    "outreach_angle", "")
    evidence    = _get("Evidence / Source", "",            "")

    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.0

    # Normalise boolean-like values that may come from Supabase as True/False
    def _yes(val) -> bool:
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("yes", "true", "1")

    col_a, col_b = st.columns([1, 1])

    with col_a:
        if phone:
            st.markdown(f"**Phone** &nbsp; {phone}")
        if website:
            disp = (website[:52] + "…") if len(website) > 52 else website
            st.markdown(f"**Website** &nbsp; [{disp}]({website})")
        st.markdown(f"**Address** &nbsp; {address}")
        st.markdown(f"**Specialty** &nbsp; {specialty}  ·  {classif}")

        if rating:
            st.markdown(f"**Rating** &nbsp; {rating} / 5 ({total_rev:,} reviews)")

        if hours and hours != "Hours not available":
            st.markdown(f"**Hours** &nbsp; {hours}")

        flags = []
        if _yes(ext_hours):
            flags.append("Extended hours")
        if _yes(online_bkg):
            flags.append("Online booking")
        if flags:
            st.markdown(f"**Features** &nbsp; {' · '.join(flags)}")

        if depth:
            st.caption(f"Review depth: {depth}")

    with col_b:
        st.markdown(_pain_badge(score), unsafe_allow_html=True)
        st.markdown("")

        signals = [
            s for s in str(signals_raw).split(" | ")
            if s and s != "None detected"
        ]
        if signals:
            st.markdown("**Pain Signals**")
            for sig in signals:
                st.markdown(f"— {sig}")
        else:
            st.caption("No pain signals detected")

        if outreach:
            st.markdown("")
            st.markdown("**Outreach Angle**")
            st.markdown(f"_{outreach}_")

        if evidence and evidence != "No direct evidence found":
            st.markdown("")
            st.markdown("**Evidence**")
            for part in str(evidence).split(" | ")[:2]:
                if part.strip():
                    st.caption(part.strip())
