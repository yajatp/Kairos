import os
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

st.set_page_config(
    page_title="Kairos Lead Engine",
    page_icon="⏳",
    layout="wide",
    initial_sidebar_state="expanded",
)

load_dotenv()

def _get_secret(key: str) -> str:
    val = os.getenv(key)
    if val:
        return val
    try:
        return st.secrets.get(key, "")
    except Exception:
        return ""

GOOGLE_PLACES_API_KEY = _get_secret("GOOGLE_PLACES_API_KEY")
ADZUNA_APP_ID = _get_secret("ADZUNA_APP_ID")
ADZUNA_APP_KEY = _get_secret("ADZUNA_APP_KEY")
OUTSCRAPER_API_KEY = _get_secret("OUTSCRAPER_API_KEY")

from pipeline.places import geocode, search_clinics, get_clinic_details
from pipeline.jobs import fetch_adzuna_jobs, match_clinic_to_job
from pipeline.reviews import scan_reviews
from pipeline.outscraper_reviews import fetch_deep_reviews
from pipeline.scorer import (
    detect_extended_hours,
    infer_specialty,
    calculate_pain_score,
    is_borderline,
    generate_outreach_angle,
)
from pipeline.website import check_website
from utils.helpers import extract_city, get_hours_summary
from utils.usage_tracker import get_remaining_budget, record_usage

# ── Custom CSS ──────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    [data-testid="stSidebar"] { background-color: #1e3a10; }
    [data-testid="stSidebar"] * { color: #f0f0f0 !important; }
    .main-header {
        background-color: #2d5016;
        padding: 1rem 1.5rem;
        border-radius: 8px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .main-header h1 { color: white; margin: 0; }
    .main-header p { color: #c8e6a0; margin: 0.25rem 0 0; }
    </style>
    """,
    unsafe_allow_html=True,
)


def highlight_pain_score(val):
    if val >= 6:
        return "background-color: #ff4b4b; color: white; font-weight: bold"
    elif val >= 4:
        return "background-color: #ff8c00; color: white; font-weight: bold"
    elif val >= 2:
        return "background-color: #ffc300; color: black"
    else:
        return "background-color: #d4edda; color: black"


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⏳ Kairos Lead Engine")
    st.markdown("---")

    st.markdown("### 📍 Location")
    location = st.text_input("City, State or ZIP code", placeholder="e.g. Dallas, TX", label_visibility="collapsed")

    st.markdown("### 🔍 Search Radius")
    radius_miles = st.select_slider("Radius", options=[10, 25, 50], value=25, label_visibility="collapsed")

    st.markdown("### 🎯 Max Results")
    max_results = st.select_slider("Max Results", options=[20, 35, 50], value=50, label_visibility="collapsed")

    st.markdown("### 🏥 Specialty Filter")
    all_specialties = ["General", "Orthodontic", "Pediatric", "Endodontic", "Oral Surgery", "Periodontic"]
    specialty_filter = st.multiselect(
        "Specialties",
        options=all_specialties,
        default=all_specialties,
        label_visibility="collapsed",
    )

    st.markdown("### ⚡ Min Pain Score")
    min_pain_score = st.slider("Min Score", min_value=0, max_value=8, value=0, label_visibility="collapsed")

    find_leads = st.button("🔍 Find Leads", use_container_width=True, type="primary")

    st.markdown("---")
    st.markdown(
        """
**ℹ️ Pain Score Guide**
- 6+ 🔴 High Priority
- 4-5 🟠 Strong Signal
- 2-3 🟡 Moderate
- 0-1 🟢 Low Priority
"""
    )

    st.markdown("---")
    remaining_budget = get_remaining_budget()
    st.markdown(
        f"""
**⚠️ Data Source Notes**

Hiring data is sourced via Adzuna under their evaluation-use terms — confirm commercial licensing with Adzuna before scaling this beyond initial testing. See README.

Deep review scans (Outscraper) are used selectively on moderate-scoring clinics to stay within free usage. Remaining monthly budget: **{remaining_budget}/450 reviews**.
"""
    )

# ── Main Panel ───────────────────────────────────────────────────────────────
st.markdown(
    """
    <div class="main-header">
        <h1>⏳ Kairos Health Lead Engine</h1>
        <p>AI-powered dental clinic prospecting for front-desk automation</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# API key warnings (shown regardless of search state)
if not GOOGLE_PLACES_API_KEY:
    st.error("Google Places API key not configured. Add GOOGLE_PLACES_API_KEY to your .env file.")
if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
    st.warning("Adzuna API not configured — hiring signals will not be available. Job signals disabled.")
if not OUTSCRAPER_API_KEY:
    st.info("Outscraper API not configured — deep review scans skipped. All clinics will use the Google Places 5-review sample.")

if "leads_df" not in st.session_state:
    st.session_state["leads_df"] = None

if not find_leads and st.session_state["leads_df"] is None:
    st.markdown(
        """
**How it works:**
1. Enter a location in the sidebar
2. Click **Find Leads**
3. The tool scans Google Places for dental clinics, cross-references hiring activity, and scans reviews for admin complaints
4. Moderate-scoring clinics get a deeper review scan automatically (budget-permitting) to refine their priority
5. Download your lead list as CSV
"""
    )

# ── Search Pipeline ──────────────────────────────────────────────────────────
if find_leads:
    if not location.strip():
        st.error("Please enter a location before searching.")
        st.stop()
    if not GOOGLE_PLACES_API_KEY:
        st.error("Google Places API key not configured. Add GOOGLE_PLACES_API_KEY to your .env file.")
        st.stop()

    progress_bar = st.progress(0)
    status = st.status("Starting search...", expanded=True)

    try:
        # Step 1: Geocode
        status.write("📍 Geocoding location...")
        try:
            lat, lng = geocode(location, GOOGLE_PLACES_API_KEY)
        except ValueError as e:
            st.error(str(e))
            st.stop()
        progress_bar.progress(10)

        # Step 2: Find clinics
        status.write("🗺️ Searching for dental clinics...")
        raw_clinics = search_clinics(lat, lng, radius_miles, max_results, GOOGLE_PLACES_API_KEY)
        if not raw_clinics:
            st.error("No dental clinics found in that area. Try expanding the search radius.")
            st.stop()
        progress_bar.progress(20)

        # Step 3: Fetch Adzuna jobs once
        status.write("💼 Fetching job postings from Adzuna...")
        jobs = fetch_adzuna_jobs(location, ADZUNA_APP_ID, ADZUNA_APP_KEY)
        progress_bar.progress(30)

        # Step 4: Per-clinic details
        leads = []
        borderline_queue = []
        total = len(raw_clinics)

        for i, clinic in enumerate(raw_clinics):
            pct = 30 + int((i / total) * 40)
            progress_bar.progress(pct)
            status.write(f"📋 Fetching clinic details from Google... ({i + 1}/{total} clinics processed)")

            details = get_clinic_details(clinic["place_id"], GOOGLE_PLACES_API_KEY)
            if not details:
                continue

            website_data = check_website(details.get("website"))
            job_match = match_clinic_to_job(details.get("name", ""), jobs)
            review_data = scan_reviews(details.get("reviews", []))
            review_data["review_source"] = "places_sample"
            extended = detect_extended_hours(details.get("opening_hours"))
            specialty = infer_specialty(details.get("name", ""), details.get("types", []))

            clinic_data = {
                "has_hiring_signal": job_match is not None,
                "hiring_job_url": job_match["job_url"] if job_match else None,
                "hiring_job_title": job_match["job_title"] if job_match else None,
                "pain_review_count": review_data["pain_review_count"],
                "pain_categories": review_data["pain_categories"],
                "worst_review_snippet": review_data["worst_review_snippet"],
                "review_source": "places_sample",
                "num_locations": 1,
                "extended_hours": extended,
                "uses_digital_tools": website_data["uses_digital_tools"],
                "has_online_booking": website_data["has_online_booking"],
                "has_hiring_banner": website_data["has_hiring_banner"],
                "detected_tools": website_data["detected_tools"],
                "rating": details.get("rating", 0),
                "user_ratings_total": details.get("user_ratings_total", 0),
            }

            pain_score, signals = calculate_pain_score(clinic_data)

            lead_record = {
                "place_id": clinic["place_id"],
                "details": details,
                "clinic_data": clinic_data,
                "specialty": specialty,
                "pain_score": pain_score,
                "signals": signals,
                "job_match": job_match,
                "review_data": review_data,
            }
            leads.append(lead_record)

            if is_borderline(pain_score):
                borderline_queue.append(len(leads) - 1)

        progress_bar.progress(70)

        # Step 5: Website check already done above; move to pass 2
        status.write(f"🔬 Running deep review scans on borderline clinics ({len(borderline_queue)} clinics, budget-permitting)...")

        OUTSCRAPER_REVIEWS_PER_CALL = 10
        MAX_OUTSCRAPER_CALLS_PER_RUN = 35
        calls_made_this_run = 0

        for idx in borderline_queue:
            if calls_made_this_run >= MAX_OUTSCRAPER_CALLS_PER_RUN:
                leads[idx]["clinic_data"]["enrichment_note"] = "Per-run Outscraper cap reached — Places sample only"
                continue

            if not OUTSCRAPER_API_KEY:
                leads[idx]["clinic_data"]["enrichment_note"] = "Outscraper not configured — Places sample only"
                continue

            remaining_budget = get_remaining_budget()
            if remaining_budget < OUTSCRAPER_REVIEWS_PER_CALL:
                leads[idx]["clinic_data"]["enrichment_note"] = "Outscraper monthly budget reached — Places sample only"
                continue

            deep_reviews = fetch_deep_reviews(leads[idx]["place_id"], OUTSCRAPER_API_KEY, OUTSCRAPER_REVIEWS_PER_CALL)
            calls_made_this_run += 1

            if not deep_reviews:
                leads[idx]["clinic_data"]["enrichment_note"] = "Outscraper returned no data — Places sample only"
                continue

            record_usage(len(deep_reviews))

            deep_review_data = scan_reviews(deep_reviews)
            deep_review_data["review_source"] = "outscraper_deep"

            leads[idx]["clinic_data"]["pain_review_count"] = deep_review_data["pain_review_count"]
            leads[idx]["clinic_data"]["pain_categories"] = deep_review_data["pain_categories"]
            leads[idx]["clinic_data"]["worst_review_snippet"] = deep_review_data["worst_review_snippet"]
            leads[idx]["clinic_data"]["review_source"] = "outscraper_deep"
            leads[idx]["review_data"] = deep_review_data

            new_score, new_signals = calculate_pain_score(leads[idx]["clinic_data"])
            leads[idx]["pain_score"] = new_score
            leads[idx]["signals"] = new_signals
            leads[idx]["clinic_data"]["enrichment_note"] = f"Deep review scan via Outscraper (n={len(deep_reviews)})"

        progress_bar.progress(90)

        # Final assembly
        status.write("⚡ Building results table...")
        final_leads = []
        for lead in leads:
            details = lead["details"]
            clinic_data = lead["clinic_data"]
            pain_score = lead["pain_score"]
            signals = lead["signals"]
            job_match = lead["job_match"]
            review_data = lead["review_data"]
            specialty = lead["specialty"]

            outreach_angle = generate_outreach_angle(signals, details.get("name", ""), specialty)

            evidence_parts = []
            if job_match:
                evidence_parts.append(f"Hiring: {job_match['job_title']} → {job_match['job_url']}")
            if review_data.get("worst_review_snippet"):
                source_label = "deep scan" if review_data.get("review_source") == "outscraper_deep" else "Places sample"
                snippet = review_data["worst_review_snippet"]
                evidence_parts.append(f'Review ({source_label}): "{snippet}"')
            evidence = " | ".join(evidence_parts) if evidence_parts else "No direct evidence found"

            notes_parts = [f"Rating: {details.get('rating', 'N/A')}★ ({details.get('user_ratings_total', 0)} reviews)"]
            if clinic_data.get("enrichment_note"):
                notes_parts.append(clinic_data["enrichment_note"])
            if clinic_data.get("has_hiring_banner"):
                notes_parts.append("Website shows a hiring banner (corroborating signal)")

            final_leads.append({
                "Clinic Name": details.get("name", ""),
                "Specialty": specialty,
                "City": extract_city(details.get("formatted_address", "")),
                "Address": details.get("formatted_address", ""),
                "Website": details.get("website", ""),
                "Phone Number": details.get("formatted_phone_number", ""),
                "Best Contact Found": "Office Manager",
                "Contact Role": "Office Manager",
                "Contact Email": "",
                "LinkedIn": "",
                "Number of Locations": 1,
                "Pain Signal Type": " | ".join(signals) if signals else "None detected",
                "Evidence / Source": evidence,
                "Pain Score": pain_score,
                "Outreach Angle": outreach_angle,
                "Notes": " | ".join(notes_parts),
                "Google Rating": details.get("rating", ""),
                "Total Reviews": details.get("user_ratings_total", 0),
                "Hours Summary": get_hours_summary(details.get("opening_hours")),
                "Extended Hours": "Yes" if clinic_data.get("extended_hours") else "No",
                "Online Booking": "Yes" if clinic_data.get("has_online_booking") else "No",
                "Review Data Depth": "Deep scan" if review_data.get("review_source") == "outscraper_deep" else "Places sample (5 max)",
            })

        df = pd.DataFrame(final_leads)
        if specialty_filter and len(specialty_filter) < len(all_specialties):
            df = df[df["Specialty"].isin(specialty_filter)]
        df = df[df["Pain Score"] >= min_pain_score]
        df = df.sort_values("Pain Score", ascending=False).reset_index(drop=True)

        st.session_state["leads_df"] = df
        st.session_state["search_location"] = location

        progress_bar.progress(100)
        status.update(label=f"✅ Done — {len(df)} leads found", state="complete", expanded=False)

    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        st.stop()

# ── Results Display ───────────────────────────────────────────────────────────
df = st.session_state.get("leads_df")

if df is not None and not df.empty:
    # Metrics row
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Leads Found", len(df))
    col2.metric("🔴 High Priority (6+)", len(df[df["Pain Score"] >= 6]))
    col3.metric("🟠 Strong Signal (4-5)", len(df[(df["Pain Score"] >= 4) & (df["Pain Score"] < 6)]))
    col4.metric("Avg Pain Score", round(df["Pain Score"].mean(), 1))
    col5.metric("Deep Scans Used", len(df[df["Review Data Depth"] == "Deep scan"]))

    st.markdown("---")

    # Styled table
    styled_df = df.style.map(highlight_pain_score, subset=["Pain Score"])
    st.dataframe(styled_df, use_container_width=True, height=500)

    # CSV download
    csv = df.to_csv(index=False)
    search_location = st.session_state.get("search_location", "unknown")
    filename = f"kairos_leads_{search_location.replace(' ', '_').replace(',', '')}_{datetime.now().strftime('%Y%m%d')}.csv"
    st.download_button(
        label="⬇️ Download as CSV",
        data=csv,
        file_name=filename,
        mime="text/csv",
    )

    # Top 5 expanded view
    st.subheader("🏆 Top Leads")
    top5 = df.head(5)
    for _, row in top5.iterrows():
        with st.expander(f"{row['Clinic Name']} — Score {row['Pain Score']}"):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Phone:** {row['Phone Number'] or 'N/A'}")
                st.markdown(f"**Website:** {row['Website'] or 'N/A'}")
                st.markdown(f"**City:** {row['City']}")
                st.markdown(f"**Specialty:** {row['Specialty']}")
            with c2:
                st.markdown(f"**Extended Hours:** {row['Extended Hours']}")
                st.markdown(f"**Online Booking:** {row['Online Booking']}")
                st.markdown(f"**Review Data Depth:** {row['Review Data Depth']}")
                st.markdown(f"**Hours:** {row['Hours Summary']}")

            st.markdown("**Pain Signals:**")
            for signal in row["Pain Signal Type"].split(" | "):
                if signal and signal != "None detected":
                    st.markdown(f"- {signal}")

            st.markdown(f"**Outreach Angle:** {row['Outreach Angle']}")
            st.markdown(f"**Evidence:** {row['Evidence / Source']}")

elif df is not None and df.empty:
    st.warning("No leads matched the current filters. Try lowering the minimum pain score or changing the specialty filter.")
