from __future__ import annotations

import re
import json
import html
from datetime import datetime, timezone

import streamlit as st
from pipeline.reviews import SIGNAL_LABELS

def safe_parse_datetime(ts_str: str) -> datetime:
    """Safely parse ISO datetime string, handling varying microsecond lengths for Python 3.9 compatibility."""
    cleaned = ts_str.strip().replace("Z", "+00:00")
    if "+" in cleaned:
        dt_part, tz_part = cleaned.split("+", 1)
        tz_part = "+" + tz_part
    elif "-" in cleaned and cleaned.count("-") >= 3:
        idx = cleaned.rfind("-")
        dt_part = cleaned[:idx]
        tz_part = cleaned[idx:]
    else:
        dt_part = cleaned
        tz_part = ""
        
    if "." in dt_part:
        base, micro = dt_part.split(".", 1)
        micro_digits = re.findall(r'\d+', micro)
        if micro_digits:
            micro_str = micro_digits[0][:6].ljust(6, '0')
            dt_part = f"{base}.{micro_str}"
        else:
            dt_part = base
            
    try:
        return datetime.fromisoformat(dt_part + tz_part)
    except ValueError:
        try:
            if "." in dt_part:
                dt_part = dt_part.split(".", 1)[0]
            return datetime.fromisoformat(dt_part + tz_part)
        except Exception:
            return datetime.now(timezone.utc)


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


# ── Review highlighting & summary helpers ──────────────────────────────────────

def apply_highlights(text: str, highlights: list, category: str) -> str:
    """Wrap keyword spans for the given category in <mark> tags.

    Other-category highlights are ignored so each expander only marks its own
    signals. Overlapping spans are skipped (first match wins).
    """
    spans = sorted(
        [h for h in highlights if h["category"] == category],
        key=lambda h: h["start"],
    )
    out_parts = []
    cursor = 0
    for span in spans:
        s, e = span["start"], span["end"]
        if s < cursor:
            continue  # skip overlapping
        out_parts.append(html.escape(text[cursor:s]))
        out_parts.append(
            f'<mark style="background:#fef08a;padding:1px 3px;border-radius:3px">'
            f'{html.escape(text[s:e])}</mark>'
        )
        cursor = e
    out_parts.append(html.escape(text[cursor:]))
    return "".join(out_parts)


def generate_category_summary(category: str, reviews: list[dict]) -> str:
    """Compile a detailed summary of complaining keywords and actual quotes."""
    from pipeline.reviews import PAIN_KEYWORDS
    keywords = PAIN_KEYWORDS.get(category, [])
    label = SIGNAL_LABELS.get(category, category.replace("_", " ").title())

    # Find which keywords actually matched
    matched_kws = set()
    sentences = []

    for r in reviews:
        text = r.get("text", "")
        text_lower = text.lower()
        # Find keywords matched in this review
        for kw in keywords:
            if kw in text_lower:
                matched_kws.add(kw)

        # Split into sentences to find the most relevant one
        for sentence in re.split(r'[.!?\n]+', text):
            sentence_clean = sentence.strip()
            if not sentence_clean:
                continue
            sentence_lower = sentence_clean.lower()
            if any(kw in sentence_lower for kw in keywords):
                # Avoid duplicates and check length
                if sentence_clean not in sentences and len(sentence_clean) > 5 and len(sentence_clean) < 250:
                    sentences.append(sentence_clean)

    kw_str = ", ".join(f"'{k}'" for k in sorted(matched_kws))
    summary = f"**{label.title()} Summary:** Found {len(reviews)} review(s) mentioning {label.lower()} indicators ({kw_str}).\n\n"
    if sentences:
        summary += "Key patient feedback:\n"
        for s in sentences[:3]:  # Top 3 quotes
            s_clean = s.replace('"', '').replace("'", "").strip()
            summary += f"- *\"{s_clean}\"*\n"
    else:
        summary += "*No specific quotes extracted, please see the reviews below.*"
    return summary


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

        review_method = _get("Review Method", "review_method", "")
        if review_method == "pattern_fallback":
            st.caption("Review analysis: pattern matching (Gemini unavailable)")
        elif review_method == "ai":
            st.caption("Review analysis: AI")

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

        # ── Review Drill-Down ─────────────────────────────────────────────
        raw_rj = _get("reviews_json", "reviews_json", None)
        all_matched = []
        if raw_rj:
            if isinstance(raw_rj, str):
                try:
                    all_matched = json.loads(raw_rj)
                except (ValueError, TypeError):
                    all_matched = []
            elif isinstance(raw_rj, list):
                all_matched = raw_rj

        # Group reviews by category
        cat_reviews: dict[str, list] = {}
        for rev in all_matched:
            for cat in rev.get("matched_categories", []):
                cat_reviews.setdefault(cat, []).append(rev)

        if cat_reviews:
            st.markdown("")
            st.markdown("**Review Drill-Down**")
            for cat, cat_revs in cat_reviews.items():
                label = SIGNAL_LABELS.get(cat, cat.replace("_", " ").title())
                cat_summary = generate_category_summary(cat, cat_revs)
                with st.expander(f":material/search: {label.title()}  ({len(cat_revs)} reviews)", expanded=False):
                    st.markdown(cat_summary)
                    st.divider()
                    for rev in cat_revs:
                        rating_val = rev.get("rating", 0)
                        stars = "★" * rating_val + "☆" * (5 - rating_val)
                        author_name = rev.get("author") or "Anonymous Patient"
                        st.markdown(f"**{stars}** · *{author_name}*")
                        highlighted = apply_highlights(
                            rev.get("text", ""),
                            rev.get("highlights", []),
                            cat,
                        )
                        st.markdown(highlighted, unsafe_allow_html=True)
                        st.divider()
        else:
            st.markdown("")
            st.info(":material/info: Review drill-down not available for this legacy lead.")
