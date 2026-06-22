import html
import json
import math
import os
import threading
import time
from datetime import datetime

import pandas as pd
import streamlit as st


def _get_secret(key: str) -> str:
    val = os.getenv(key)
    if val:
        return val
    try:
        return st.secrets.get(key, "")
    except Exception:
        return ""


GOOGLE_PLACES_API_KEY = _get_secret("GOOGLE_PLACES_API_KEY")
ADZUNA_APP_ID         = _get_secret("ADZUNA_APP_ID")
ADZUNA_APP_KEY        = _get_secret("ADZUNA_APP_KEY")
OUTSCRAPER_API_KEY    = _get_secret("OUTSCRAPER_API_KEY")

from pipeline.places import geocode, search_clinics, get_clinic_details
from pipeline.jobs import fetch_adzuna_jobs, match_clinic_to_job
from pipeline.reviews import scan_reviews, SIGNAL_LABELS
from pipeline.outscraper_reviews import fetch_deep_reviews
from pipeline.classifier import classify_clinic
from pipeline.scorer import (
    detect_extended_hours,
    infer_specialty,
    calculate_pain_score,
    is_borderline,
    generate_outreach_angle,
)
from pipeline.website import check_website
from utils.helpers import extract_city, get_hours_summary
from utils.usage_tracker import (
    get_remaining_budget,
    record_usage,
    record_run,
    save_lead,
    OUTSCRAPER_MONTHLY_LIMIT,
    get_exact_run,
    get_known_place_ids,
    get_lead_run_info,
)

# ── Review drill-down helpers ───────────────────────────────────────────────────

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


# ── Color constants ─────────────────────────────────────────────────────────────
_TEXT2  = "#6b6f76"
_TEXT3  = "#8a8f98"
_BORDER = "#ededed"


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


def _priority_dot_color(score: float) -> str:
    if score >= 6:  return "#ef4444"
    if score >= 4:  return "#f97316"
    if score >= 2:  return "#eab308"
    return "#22c55e"


def _group_label(score: float) -> str:
    if score >= 6:  return "High Priority"
    if score >= 4:  return "Strong Signal"
    if score >= 2:  return "Moderate"
    return "Low Priority"


# ── Pipeline state ──────────────────────────────────────────────────────────────
if "_pipeline" not in st.session_state:
    st.session_state["_pipeline"] = {
        "running": False,
        "stop_requested": False,
        "progress": 0,
        "messages": [],
        "leads_df": None,
        "error": None,
        "search_location": None,
        "skipped_clinics": [],
    }

_p = st.session_state["_pipeline"]


def _run_pipeline(p: dict, location: str, radius_miles: int, max_results: int) -> None:
    p["running"]         = True
    p["stop_requested"]  = False
    p["progress"]        = 0
    p["messages"]        = []
    p["leads_df"]        = None
    p["error"]           = None
    p["search_location"] = location
    p["skipped_clinics"] = []

    _calls = {"geocode": 0, "search": 0, "detail": 0, "adzuna": 0, "outscraper_reviews": 0}
    leads  = []

    def log(msg: str) -> None:
        p["messages"].append(msg)

    try:
        log("Geocoding location...")
        try:
            lat, lng = geocode(location, GOOGLE_PLACES_API_KEY)
            _calls["geocode"] += 1
        except ValueError as e:
            p["error"] = str(e)
            return
        p["progress"] = 10

        if p["stop_requested"]:
            log("Stopped by user.")
            return

        log("Searching for dental clinics...")
        raw_clinics = search_clinics(lat, lng, radius_miles, max_results, GOOGLE_PLACES_API_KEY)
        _calls["search"] += math.ceil(max_results / 20)
        if not raw_clinics:
            p["error"] = "No dental clinics found in that area. Try expanding the search radius."
            return
        p["progress"] = 20

        if p["stop_requested"]:
            log("Stopped by user.")
            return

        log("Fetching job postings from Adzuna...")
        jobs = fetch_adzuna_jobs(location, ADZUNA_APP_ID, ADZUNA_APP_KEY)
        _calls["adzuna"] += 1
        p["progress"] = 30

        borderline_queue = []

        # B2 — partition clinics into new vs already-known
        known_place_ids = get_known_place_ids()
        new_clinics     = [c for c in raw_clinics if c["place_id"] not in known_place_ids]
        skipped_clinics_raw = [c for c in raw_clinics if c["place_id"] in known_place_ids]

        skipped_clinics: list[dict] = []
        for sc in skipped_clinics_raw:
            info = get_lead_run_info(sc["place_id"])
            skipped_clinics.append({
                "name":           sc.get("name", sc["place_id"]),
                "place_id":       sc["place_id"],
                "address":        sc.get("vicinity", ""),
                "prior_location": info["run_location"] if info else "",
                "prior_date":     info["scored_at"]    if info else "",
                "run_id":         info["run_id"]        if info else None,
            })

        if skipped_clinics:
            log(f"Skipping {len(skipped_clinics)} clinics already in database.")

        p["skipped_clinics"] = skipped_clinics

        total = len(new_clinics)

        for i, clinic in enumerate(new_clinics):
            if p["stop_requested"]:
                log(f"Stopped after {i} of {total} clinics.")
                break

            p["progress"] = 30 + int((i / total) * 40) if total else 70
            log(f"Fetching clinic details... ({i + 1}/{total})")

            details     = get_clinic_details(clinic["place_id"], GOOGLE_PLACES_API_KEY)
            _calls["detail"] += 1
            if not details:
                continue

            website_data  = check_website(details.get("website"))
            job_match     = match_clinic_to_job(details.get("name", ""), jobs)
            review_data   = scan_reviews(details.get("reviews", []))
            review_data["review_source"] = "places_sample"
            extended      = detect_extended_hours(details.get("opening_hours"))
            specialty     = infer_specialty(details.get("name", ""), details.get("types", []))

            clinic_data = {
                "has_hiring_signal":      job_match is not None,
                "hiring_job_url":         job_match["job_url"]   if job_match else None,
                "hiring_job_title":       job_match["job_title"] if job_match else None,
                "pain_review_count":      review_data["pain_review_count"],
                "pain_categories":        review_data["pain_categories"],
                "worst_review_snippet":   review_data["worst_review_snippet"],
                "review_source":          "places_sample",
                "num_locations":          1,
                "extended_hours":         extended,
                "uses_digital_tools":     website_data["uses_digital_tools"],
                "has_online_booking":     website_data["has_online_booking"],
                "has_hiring_banner":      website_data["has_hiring_banner"],
                "detected_tools":         website_data["detected_tools"],
                "rating":                 details.get("rating", 0),
                "user_ratings_total":     details.get("user_ratings_total", 0),
            }

            pain_score, signals = calculate_pain_score(clinic_data)
            classification      = classify_clinic(details.get("name", ""), num_locations=1)

            leads.append({
                "place_id":       clinic["place_id"],
                "details":        details,
                "clinic_data":    clinic_data,
                "specialty":      specialty,
                "pain_score":     pain_score,
                "signals":        signals,
                "job_match":      job_match,
                "review_data":    review_data,
                "classification": classification,
            })

            if is_borderline(pain_score):
                borderline_queue.append(len(leads) - 1)

        p["progress"] = 70

        if not p["stop_requested"]:
            log(f"Deep review scans on {len(borderline_queue)} borderline clinics...")
            OUTSCRAPER_REVIEWS_PER_CALL = 10
            calls_made = 0

            for idx in borderline_queue:
                if p["stop_requested"]:
                    log("Stopped during deep scans.")
                    break
                if calls_made >= 15:
                    leads[idx]["clinic_data"]["enrichment_note"] = "Per-run cap reached — Places sample only"
                    continue
                if not OUTSCRAPER_API_KEY:
                    leads[idx]["clinic_data"]["enrichment_note"] = "Outscraper not configured — Places sample only"
                    continue
                if get_remaining_budget() < OUTSCRAPER_REVIEWS_PER_CALL:
                    leads[idx]["clinic_data"]["enrichment_note"] = "Monthly budget reached — Places sample only"
                    continue

                deep_reviews = fetch_deep_reviews(leads[idx]["place_id"], OUTSCRAPER_API_KEY, OUTSCRAPER_REVIEWS_PER_CALL)
                calls_made += 1
                if not deep_reviews:
                    leads[idx]["clinic_data"]["enrichment_note"] = "Outscraper returned no data — Places sample only"
                    continue

                record_usage(len(deep_reviews))
                _calls["outscraper_reviews"] += len(deep_reviews)

                dr = scan_reviews(deep_reviews)
                dr["review_source"] = "outscraper_deep"
                leads[idx]["clinic_data"].update({
                    "pain_review_count":    dr["pain_review_count"],
                    "pain_categories":      dr["pain_categories"],
                    "worst_review_snippet": dr["worst_review_snippet"],
                    "review_source":        "outscraper_deep",
                    "enrichment_note":      f"Deep review scan via Outscraper (n={len(deep_reviews)})",
                })
                leads[idx]["review_data"] = dr
                new_score, new_signals     = calculate_pain_score(leads[idx]["clinic_data"])
                leads[idx]["pain_score"]  = new_score
                leads[idx]["signals"]     = new_signals

        p["progress"] = 90
        log("Building results table...")

        if not leads:
            p["error"] = "No leads could be processed. The run may have been stopped too early."
            return

        final_leads = []
        for lead in leads:
            details        = lead["details"]
            clinic_data    = lead["clinic_data"]
            signals        = lead["signals"]
            job_match      = lead["job_match"]
            review_data    = lead["review_data"]
            specialty      = lead["specialty"]
            pain_score     = lead["pain_score"]
            classification = lead["classification"]

            outreach_angle = generate_outreach_angle(signals, details.get("name", ""), specialty)

            evidence_parts = []
            if job_match:
                evidence_parts.append(f"Hiring: {job_match['job_title']} → {job_match['job_url']}")
            if review_data.get("worst_review_snippet"):
                src = "deep scan" if review_data.get("review_source") == "outscraper_deep" else "Places sample"
                evidence_parts.append(f'Review ({src}): "{review_data["worst_review_snippet"]}"')
            evidence = " | ".join(evidence_parts) or "No direct evidence found"

            notes_parts = [f"Rating: {details.get('rating','N/A')} ({details.get('user_ratings_total',0)} reviews)"]
            if clinic_data.get("enrichment_note"):
                notes_parts.append(clinic_data["enrichment_note"])
            if clinic_data.get("has_hiring_banner"):
                notes_parts.append("Website shows a hiring banner")

            review_depth_label = (
                "Deep scan" if review_data.get("review_source") == "outscraper_deep"
                else "Places sample (5 max)"
            )

            matched_reviews = review_data.get("matched_reviews", [])
            reviews_json = json.dumps(matched_reviews) if matched_reviews else None

            final_leads.append({
                "Clinic Name":         details.get("name", ""),
                "Classification":      classification,
                "Specialty":           specialty,
                "City":                extract_city(details.get("formatted_address", "")),
                "Address":             details.get("formatted_address", ""),
                "Website":             details.get("website", ""),
                "Phone Number":        details.get("formatted_phone_number", ""),
                "Best Contact Found":  "Office Manager",
                "Contact Role":        "Office Manager",
                "Contact Email":       "",
                "LinkedIn":            "",
                "Number of Locations": 1,
                "Pain Signal Type":    " | ".join(signals) if signals else "None detected",
                "Evidence / Source":   evidence,
                "Pain Score":          pain_score,
                "Outreach Angle":      outreach_angle,
                "Notes":               " | ".join(notes_parts),
                "Google Rating":       details.get("rating", ""),
                "Total Reviews":       details.get("user_ratings_total", 0),
                "Hours Summary":       get_hours_summary(details.get("opening_hours")),
                "Extended Hours":      "Yes" if clinic_data.get("extended_hours") else "No",
                "Online Booking":      "Yes" if clinic_data.get("has_online_booking") else "No",
                "Review Data Depth":   review_depth_label,
                "reviews_json":        reviews_json,
            })

            save_lead(
                place_id=lead["place_id"],
                run_location=location,
                name=details.get("name", ""),
                address=details.get("formatted_address", ""),
                phone=details.get("formatted_phone_number", ""),
                website=details.get("website", ""),
                specialty=specialty,
                classification=classification,
                pain_score=pain_score,
                signals=" | ".join(signals) if signals else "",
                outreach_angle=outreach_angle,
                rating=float(details.get("rating", 0) or 0),
                total_reviews=int(details.get("user_ratings_total", 0) or 0),
                extended_hours=bool(clinic_data.get("extended_hours")),
                online_booking=bool(clinic_data.get("has_online_booking")),
                review_depth=review_depth_label,
                reviews_json=reviews_json,
            )

        p["leads_df"] = pd.DataFrame(final_leads)
        p["progress"] = 100
        log(f"Done — {len(final_leads)} leads collected.")

    except Exception as e:
        p["error"] = f"An unexpected error occurred: {e}"
    finally:
        try:
            record_run(
                location=location,
                geocode_calls=_calls["geocode"],
                search_calls=_calls["search"],
                detail_calls=_calls["detail"],
                adzuna_calls=_calls["adzuna"],
                outscraper_reviews=_calls["outscraper_reviews"],
                clinics_found=len(leads),
                leads_found=len(p["leads_df"]) if p.get("leads_df") is not None else 0,
                stopped_early=p.get("stop_requested", False),
                radius_miles=radius_miles,
            )
        except Exception:
            pass
        p["running"] = False


# ── Sidebar controls ────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("Location")
    location = st.text_input(
        "Location",
        placeholder="City, State or ZIP",
        label_visibility="collapsed",
        disabled=_p["running"],
    )

    st.markdown("Search Radius")
    radius_miles = st.select_slider(
        "Radius",
        options=[10, 25, 50],
        value=25,
        label_visibility="collapsed",
        disabled=_p["running"],
        format_func=lambda x: f"{x} mi",
    )

    st.markdown("Max Results")
    max_results = st.select_slider(
        "Max Results",
        options=[20, 35, 50],
        value=50,
        label_visibility="collapsed",
    )

    st.markdown("Specialty")
    all_specialties  = ["General", "Orthodontic", "Pediatric", "Endodontic", "Oral Surgery", "Periodontic"]
    specialty_filter = st.pills(
        "Specialties",
        options=all_specialties,
        default=all_specialties,
        selection_mode="multi",
        label_visibility="collapsed",
    )
    if not specialty_filter:
        specialty_filter = all_specialties

    st.markdown("Practice Type")
    all_classifications  = ["Independent", "DSO", "Chain", "Unknown"]
    classification_filter = st.pills(
        "Practice Type",
        options=all_classifications,
        default=all_classifications,
        selection_mode="multi",
        label_visibility="collapsed",
    )
    if not classification_filter:
        classification_filter = all_classifications

    st.markdown("Min Pain Score")
    min_pain_score = st.slider(
        "Min Score",
        min_value=0,
        max_value=8,
        value=0,
        label_visibility="collapsed",
    )

    st.markdown("")
    find_leads = st.button(
        "Find Leads",
        use_container_width=True,
        type="primary",
        disabled=_p["running"],
    )

    if _p["running"]:
        if st.button("Stop Run", use_container_width=True, type="secondary"):
            _p["stop_requested"] = True

    st.markdown("---")

    # Pain score guide
    st.markdown(
        f"""
        <div class='pain-guide'>
            <div class='pain-guide-title'>Pain Score Guide</div>
            <div><span class='pain-pill' style='background:#fef2f2;color:#b91c1c'>6+</span> High Priority</div>
            <div><span class='pain-pill' style='background:#fff7ed;color:#c2410c'>4–5</span> Strong Signal</div>
            <div><span class='pain-pill' style='background:#fefce8;color:#854d0e'>2–3</span> Moderate</div>
            <div><span class='pain-pill' style='background:#f0fdf4;color:#166534'>0–1</span> Low Priority</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")

    remaining_budget = get_remaining_budget()
    pct_used = 1.0 - remaining_budget / OUTSCRAPER_MONTHLY_LIMIT
    if remaining_budget == 0:
        st.error("Outscraper monthly limit reached — deep scans disabled.")
    elif pct_used >= 0.8:
        st.warning(f"Outscraper: {remaining_budget} reviews left ({int(pct_used*100)}% used)")
    else:
        st.caption(f"Outscraper: {remaining_budget}/{OUTSCRAPER_MONTHLY_LIMIT} reviews remaining")


# ── Page header ─────────────────────────────────────────────────────────────────
st.markdown(
    "<div class='page-header-linear'>"
    "<span class='bc-parent'>Kairos</span>"
    "<span class='bc-sep'>›</span>"
    "<span class='bc-current'>Find Leads</span>"
    "</div>",
    unsafe_allow_html=True,
)

# ── API warnings ────────────────────────────────────────────────────────────────
if not GOOGLE_PLACES_API_KEY:
    st.error("Google Places API key not configured. Add `GOOGLE_PLACES_API_KEY` to your `.env` file.")
if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
    st.warning("Adzuna API not configured — hiring signals will be skipped.")
if not OUTSCRAPER_API_KEY:
    st.info("Outscraper not configured — deep review scans will be skipped.")

# ── Pipeline trigger ─────────────────────────────────────────────────────────────
if find_leads:
    if not location.strip():
        st.error("Enter a location before searching.")
        st.stop()
    if not GOOGLE_PLACES_API_KEY:
        st.error("Google Places API key not configured.")
        st.stop()

    # B1 — exact query deduplication check
    prior_run = get_exact_run(location.strip(), radius_miles)
    if prior_run and not st.session_state.get("_overlap_run_anyway"):
        from datetime import datetime as _dt
        try:
            prior_ts = _dt.fromisoformat(prior_run["timestamp"].replace("Z", "+00:00"))
            prior_date_str = prior_ts.strftime("%b %d, %Y")
        except Exception:
            prior_date_str = prior_run.get("timestamp", "")
        st.warning(
            f"You already searched **{location.strip()}** at a **{radius_miles}mi radius** "
            f"on {prior_date_str}. Viewing the same results again?"
        )
        col_hist, col_run = st.columns(2)
        with col_hist:
            if st.button("Go to History", use_container_width=True):
                st.switch_page("pages/history.py")
        with col_run:
            if st.button("Run Anyway", use_container_width=True, type="primary"):
                st.session_state["_overlap_run_anyway"] = True
                st.rerun()
        st.stop()

    # Clear the "run anyway" flag so it doesn't persist to future searches
    st.session_state.pop("_overlap_run_anyway", None)

    threading.Thread(
        target=_run_pipeline,
        args=(_p, location, radius_miles, max_results),
        daemon=True,
    ).start()
    st.rerun()

# ── Running state ────────────────────────────────────────────────────────────────
if _p["running"]:
    st.markdown("<div style='padding:24px 0 8px'>", unsafe_allow_html=True)
    st.progress(_p["progress"] / 100, text=f"Scanning dental clinics… {_p['progress']}%")

    recent = _p["messages"][-6:]
    if recent:
        lines = "".join(
            f"<div style='padding:2px 0;border-bottom:1px solid {_BORDER};font-size:11.5px;color:{_TEXT2}'>{m}</div>"
            for m in recent
        )
        log_bg = "#f7f7f8"
        st.markdown(
            f"<div style='font-family:ui-monospace,monospace;padding:10px 12px;"
            f"background:{log_bg};border-radius:7px;"
            f"border:1px solid {_BORDER};margin-top:8px'>{lines}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)
    time.sleep(0.6)
    st.rerun()

if _p["error"] and not _p["running"]:
    st.error(_p["error"])

# ── Results ──────────────────────────────────────────────────────────────────────
leads_df = _p.get("leads_df")

if leads_df is not None and not _p["running"]:
    df = leads_df.copy()
    if specialty_filter and len(specialty_filter) < len(all_specialties):
        df = df[df["Specialty"].isin(specialty_filter)]
    if len(classification_filter) < len(all_classifications):
        df = df[df["Classification"].str.lower().isin([c.lower() for c in classification_filter])]
    df = df[df["Pain Score"] >= min_pain_score]
    df = df.sort_values("Pain Score", ascending=False).reset_index(drop=True)

    if df.empty:
        st.warning("No leads matched the current filters.")
    else:
        # ── B2 Overlap summary ───────────────────────
        skipped = _p.get("skipped_clinics", [])
        if skipped:
            from datetime import datetime as _dt
            with st.container():
                st.info(
                    f"↩ {len(skipped)} clinic{'s' if len(skipped) != 1 else ''} "
                    f"{'were' if len(skipped) != 1 else 'was'} already in your database "
                    f"and skipped (saved ~{len(skipped)} API call{'s' if len(skipped) != 1 else ''})"
                )
                for sc in skipped:
                    prior_loc  = sc.get("prior_location", "")
                    prior_date = sc.get("prior_date", "")
                    run_id     = sc.get("run_id")
                    try:
                        prior_date_str = _dt.fromisoformat(
                            prior_date.replace("Z", "+00:00")
                        ).strftime("%b %d") if prior_date else ""
                    except Exception:
                        prior_date_str = prior_date

                    meta = " · ".join(filter(None, [prior_loc, prior_date_str]))
                    sc_col1, sc_col2 = st.columns([3, 1])
                    with sc_col1:
                        st.caption(f"**{sc['name']}**" + (f"  ·  {meta}" if meta else ""))
                    with sc_col2:
                        if run_id is not None:
                            if st.button("View in History", key=f"skip_{sc['place_id']}", use_container_width=True):
                                st.session_state["history_target_run"] = run_id
                                st.switch_page("pages/history.py")

        # ── Stat blocks ─────────────────────────────
        high_ct   = len(df[df["Pain Score"] >= 6])
        strong_ct = len(df[(df["Pain Score"] >= 4) & (df["Pain Score"] < 6)])
        avg_score = round(df["Pain Score"].mean(), 1)
        deep_ct   = len(df[df["Review Data Depth"] == "Deep scan"])
        hiring_ct = len(df[df["Pain Signal Type"].str.contains("iring", na=False)])

        st.markdown(
            f"""
            <div class='stat-blocks' style='margin:20px 0 18px'>
              <div class='stat-block'>
                <div class='sl'>Total Leads</div>
                <div class='sv'>{len(df)}</div>
              </div>
              <div class='stat-block'>
                <div class='sl'>High Priority</div>
                <div class='sv' style='color:#ef4444'>{high_ct}</div>
                <div class='ss'>Score ≥ 6</div>
              </div>
              <div class='stat-block'>
                <div class='sl'>Strong Signal</div>
                <div class='sv' style='color:#f97316'>{strong_ct}</div>
                <div class='ss'>Score 4–5</div>
              </div>
              <div class='stat-block'>
                <div class='sl'>Avg Score</div>
                <div class='sv'>{avg_score}</div>
              </div>
              <div class='stat-block'>
                <div class='sl'>Deep Scans</div>
                <div class='sv'>{deep_ct}</div>
                <div class='ss'>Outscraper enriched</div>
              </div>
              <div class='stat-block'>
                <div class='sl'>Hiring Signals</div>
                <div class='sv'>{hiring_ct}</div>
                <div class='ss'>Hiring detected</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── Tab filter ──────────────────────────────
        filter_tab = st.segmented_control(
            "Filter",
            options=["All Leads", "High Priority", "Strong Signal", "Low Priority"],
            default="All Leads",
            label_visibility="collapsed",
            key="leads_filter",
        )
        if filter_tab is None:
            filter_tab = "All Leads"

        if filter_tab == "High Priority":
            view_df = df[df["Pain Score"] >= 6].copy()
        elif filter_tab == "Strong Signal":
            view_df = df[(df["Pain Score"] >= 4) & (df["Pain Score"] < 6)].copy()
        elif filter_tab == "Low Priority":
            view_df = df[df["Pain Score"] < 4].copy()
        else:
            view_df = df.copy()

        # ── Practice Type filter ────────────────────
        all_classifications = ["Independent", "DSO", "Chain", "Unknown"]
        classification_filter = st.pills(
            "Practice Type",
            options=all_classifications,
            default=all_classifications,
            selection_mode="multi",
            key="results_classification_filter",
        )
        if not classification_filter:
            classification_filter = all_classifications
        if len(classification_filter) < len(all_classifications):
            view_df = view_df[
                view_df["Classification"].str.lower().isin([c.lower() for c in classification_filter])
            ]

        view_df = view_df.reset_index(drop=True)

        # ── Toolbar ─────────────────────────────────
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        tool_c1, tool_c2, tool_c3 = st.columns([4, 1.4, 1.2])
        with tool_c1:
            loc_label = _p.get("search_location", "")
            st.caption(
                f"{len(view_df)} lead{'s' if len(view_df) != 1 else ''}"
                + (f" · {loc_label}" if loc_label else "")
            )
        with tool_c2:
            sort_by = st.selectbox(
                "Sort",
                options=["Pain Score ↓", "Rating ↓", "Rating ↑", "Name ↑"],
                label_visibility="collapsed",
                key="leads_sort",
            )
        with tool_c3:
            loc = _p.get("search_location", "unknown")
            st.download_button(
                "Export CSV",
                data=view_df.to_csv(index=False),
                file_name=f"kairos_{loc.replace(' ','_').replace(',','')}_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

        sort_map = {
            "Pain Score ↓": ("Pain Score", False),
            "Rating ↓":     ("Google Rating", False),
            "Rating ↑":     ("Google Rating", True),
            "Name ↑":       ("Clinic Name", True),
        }
        scol, sasc = sort_map[sort_by]
        view_df = view_df.sort_values(scol, ascending=sasc).reset_index(drop=True)

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

        # ── Grouped lead rows ────────────────────────
        GROUPS = [
            ("High Priority", view_df[view_df["Pain Score"] >= 6],                                  "#ef4444"),
            ("Strong Signal", view_df[(view_df["Pain Score"] >= 4) & (view_df["Pain Score"] < 6)],  "#f97316"),
            ("Moderate",      view_df[(view_df["Pain Score"] >= 2) & (view_df["Pain Score"] < 4)],  "#eab308"),
            ("Low Priority",  view_df[view_df["Pain Score"] < 2],                                   "#22c55e"),
        ]

        for group_name, group_df, dot_color in GROUPS:
            if group_df.empty:
                continue

            st.markdown(
                f"<div class='lead-group-header'>"
                f"<span class='lgd' style='background:{dot_color}'></span>"
                f"<span class='lgn'>{group_name}</span>"
                f"<span class='lgc'>{len(group_df)}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

            for _, row in group_df.iterrows():
                score  = row["Pain Score"]
                name   = row["Clinic Name"]
                city   = row["City"]
                rating = row.get("Google Rating", "")
                rating_str = f"  ·  {rating} stars" if rating else ""

                label = f"{name}  ·  {city}  ·  Score {score}{rating_str}"

                with st.expander(label, expanded=False):
                    col_a, col_b = st.columns([1, 1])

                    with col_a:
                        phone   = row.get("Phone Number", "")
                        website = row.get("Website", "")
                        if phone:
                            st.markdown(f"**Phone** &nbsp; {phone}")
                        if website:
                            disp = (website[:52] + "…") if len(website) > 52 else website
                            st.markdown(f"**Website** &nbsp; [{disp}]({website})")

                        st.markdown(f"**Address** &nbsp; {row['Address']}")
                        st.markdown(f"**Specialty** &nbsp; {row['Specialty']}  ·  {row['Classification']}")

                        rating_full = row.get("Google Rating", "")
                        total_rev   = int(row.get("Total Reviews", 0) or 0)
                        if rating_full:
                            st.markdown(f"**Rating** &nbsp; {rating_full} / 5 ({total_rev:,} reviews)")

                        hours = row.get("Hours Summary", "")
                        if hours:
                            st.markdown(f"**Hours** &nbsp; {hours}")

                        flags = []
                        if row.get("Extended Hours") == "Yes":  flags.append("Extended hours")
                        if row.get("Online Booking") == "Yes":  flags.append("Online booking")
                        if flags:
                            st.markdown(f"**Features** &nbsp; {' · '.join(flags)}")

                        depth = row.get("Review Data Depth", "")
                        if depth:
                            st.caption(f"Review depth: {depth}")

                    with col_b:
                        st.markdown(_pain_badge(score), unsafe_allow_html=True)
                        st.markdown("")

                        signals = [
                            s for s in row.get("Pain Signal Type", "").split(" | ")
                            if s and s != "None detected"
                        ]
                        if signals:
                            st.markdown("**Pain Signals**")
                            for sig in signals:
                                st.markdown(f"— {sig}")
                        else:
                            st.caption("No pain signals detected")

                        outreach = row.get("Outreach Angle", "")
                        if outreach:
                            st.markdown("")
                            st.markdown("**Outreach Angle**")
                            st.markdown(f"_{outreach}_")

                        evidence = row.get("Evidence / Source", "")
                        if evidence and evidence != "No direct evidence found":
                            st.markdown("")
                            st.markdown("**Evidence**")
                            for part in evidence.split(" | ")[:2]:
                                if part.strip():
                                    st.caption(part.strip())

                        # ── Review drill-down ────────────────────────────
                        raw_rj = row.get("reviews_json")
                        if raw_rj:
                            try:
                                all_matched = json.loads(raw_rj)
                            except (ValueError, TypeError):
                                all_matched = []

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
                                    with st.expander(f"🔍 {label}  ({len(cat_revs)} reviews)", expanded=False):
                                        st.markdown(
                                            f"**Summary:** Found {len(cat_revs)} review(s) "
                                            f"mentioning {label} issues."
                                        )
                                        st.divider()
                                        for rev in cat_revs:
                                            rating_val = rev.get("rating", 0)
                                            stars = "★" * rating_val + "☆" * (5 - rating_val)
                                            st.markdown(f"**{stars}**")
                                            highlighted = apply_highlights(
                                                rev.get("text", ""),
                                                rev.get("highlights", []),
                                                cat,
                                            )
                                            st.markdown(highlighted, unsafe_allow_html=True)
                                            st.divider()

# ── Empty state ──────────────────────────────────────────────────────────────────
elif leads_df is None and not _p["running"] and not _p["error"]:
    st.markdown(
        f"""
        <div class='empty-state'>
          <div class='empty-state-title'>Ready to find leads</div>
          <div class='empty-state-body'>
            Enter a city, state, or ZIP in the sidebar and click <strong>Find Leads</strong>
            to scan dental clinics for front-desk automation opportunities.
          </div>
          <div class='how-it-works'>
            <div class='hw-title'>How it works</div>
            <div class='hw-step'>
              <div class='hw-num'>1</div>
              <div>Scans Google Places for dental clinics near the target location</div>
            </div>
            <div class='hw-step'>
              <div class='hw-num'>2</div>
              <div>Cross-references active hiring signals on Adzuna job board</div>
            </div>
            <div class='hw-step'>
              <div class='hw-num'>3</div>
              <div>Scans patient reviews for admin and front-desk complaints</div>
            </div>
            <div class='hw-step'>
              <div class='hw-num'>4</div>
              <div>Scores and ranks each clinic by pain signal strength</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
