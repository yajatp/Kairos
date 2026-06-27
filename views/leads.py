import html
import json
import math
import os
import threading
import time
from datetime import datetime

import folium
import pandas as pd
import requests
import streamlit as st
from folium.plugins import MeasureControl
from streamlit_folium import st_folium
from branca.element import MacroElement, Template


class _ImperialScale(MacroElement):
    """Miles-only Leaflet scale control, baked into the map init so it renders reliably under st_folium."""

    _name = "ImperialScale"
    _template = Template(
        """
        {% macro script(this, kwargs) %}
        L.control.scale({maxWidth: 100, metric: false, imperial: true}).addTo({{ this._parent.get_name() }});
        {% endmacro %}
        """
    )


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
from pipeline.reviews import scan_reviews
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
from utils.helpers import get_hours_summary
from utils.usage_tracker import (
    record_usage,
    record_run,
    save_lead,
    get_exact_run,
    get_known_place_ids,
    get_lead_run_info,
    estimated_google_cost,
    estimated_outscraper_cost,
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
    p["fallback_count"]  = 0
    p["run_errors"]      = []
    p["leads_df"]        = None
    p["error"]           = None
    p["search_location"] = location
    p["skipped_clinics"] = []

    _calls = {"geocode": 0, "search": 0, "detail": 0, "adzuna": 0, "outscraper_reviews": 0, "gemini": 0}
    leads  = []

    def log(msg: str) -> None:
        p["messages"].append(msg)

    try:
        log("Geocoding location...")
        try:
            lat, lng, resolved_location = geocode(location, GOOGLE_PLACES_API_KEY)
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
        location = resolved_location
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

        import concurrent.futures
        
        def _process_clinic(clinic):
            local_calls = {"detail": 0, "gemini": 0}
            local_errors = []
            fallback_count = 0
            
            details = get_clinic_details(clinic["place_id"], GOOGLE_PLACES_API_KEY)
            local_calls["detail"] += 1
            if not details:
                return None
                
            website_data  = check_website(details.get("website"))
            job_match     = match_clinic_to_job(details.get("name", ""), jobs)
            
            _gem_key = p.get("gemini_key", "")
            if _gem_key:
                from pipeline.review_scanner_ab import scan_method_b
                local_calls["gemini"] += 1
                try:
                    review_data = scan_method_b(details.get("reviews", []), _gem_key)
                    review_data["review_method"] = "ai"
                except Exception as _e:
                    review_data = scan_reviews(details.get("reviews", []))
                    review_data["review_method"] = "pattern_fallback"
                    fallback_count += 1
                    local_errors.append(f"AI review failed ({details.get('name','?')}): {str(_e)[:120]}")
            else:
                review_data = scan_reviews(details.get("reviews", []))
                review_data["review_method"] = "pattern"
                
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
                "extracted_email":        website_data.get("extracted_email", ""),
                "rating":                 details.get("rating", 0),
                "user_ratings_total":     details.get("user_ratings_total", 0),
            }

            pain_score, signals = calculate_pain_score(clinic_data)
            classification      = classify_clinic(details.get("name", ""), num_locations=1)

            res_lead = {
                "place_id":       clinic["place_id"],
                "details":        details,
                "clinic_data":    clinic_data,
                "specialty":      specialty,
                "pain_score":     pain_score,
                "signals":        signals,
                "job_match":      job_match,
                "review_data":    review_data,
                "classification": classification,
            }
            
            return {
                "lead": res_lead,
                "calls": local_calls,
                "errors": local_errors,
                "fallback_count": fallback_count,
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_clinic = {executor.submit(_process_clinic, c): c for c in new_clinics}
            
            completed_count = 0
            for future in concurrent.futures.as_completed(future_to_clinic):
                if p["stop_requested"]:
                    log(f"Stopped after {completed_count} of {total} clinics.")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                completed_count += 1
                p["progress"] = 30 + int((completed_count / total) * 40) if total else 70
                log(f"Fetching clinic details... ({completed_count}/{total})")
                
                try:
                    res = future.result()
                    if res:
                        leads.append(res["lead"])
                        _calls["detail"] += res["calls"]["detail"]
                        _calls["gemini"] += res["calls"]["gemini"]
                        p["fallback_count"] = p.get("fallback_count", 0) + res["fallback_count"]
                        p["run_errors"].extend(res["errors"])
                        
                        if is_borderline(res["lead"]["pain_score"]):
                            borderline_queue.append(len(leads) - 1)
                except Exception as e:
                    p["run_errors"].append(f"Unexpected parallel error: {e}")

        p["progress"] = 70

        if not p["stop_requested"] and borderline_queue:
            log(f"Deep review scans on {len(borderline_queue)} borderline clinics...")
            OUTSCRAPER_REVIEWS_PER_CALL = 10
            
            calls_made_lock = threading.Lock()
            calls_made = 0
            
            def _process_deep_scan(idx):
                nonlocal calls_made
                with calls_made_lock:
                    if calls_made >= 15:
                        return idx, {"error": "Per-run cap reached — Places sample only"}
                    calls_made += 1
                    
                if not OUTSCRAPER_API_KEY:
                    return idx, {"error": "Outscraper not configured — Places sample only"}
                
                deep_reviews = fetch_deep_reviews(leads[idx]["place_id"], OUTSCRAPER_API_KEY, OUTSCRAPER_REVIEWS_PER_CALL)
                if not deep_reviews:
                    return idx, {"error": "Outscraper returned no data — Places sample only"}
                    
                local_calls = {"outscraper": len(deep_reviews), "gemini": 0}
                local_errors = []
                fallback_count = 0
                
                _gem_key = p.get("gemini_key", "")
                if _gem_key:
                    from pipeline.review_scanner_ab import scan_method_b as _smb
                    local_calls["gemini"] += 1
                    try:
                        dr = _smb(deep_reviews, _gem_key)
                        dr["review_method"] = "ai"
                    except Exception as _e:
                        dr = scan_reviews(deep_reviews)
                        dr["review_method"] = "pattern_fallback"
                        fallback_count += 1
                        local_errors.append(f"AI deep scan failed ({leads[idx]['details'].get('name','?')}): {str(_e)[:120]}")
                else:
                    dr = scan_reviews(deep_reviews)
                    dr["review_method"] = "pattern"
                dr["review_source"] = "outscraper_deep"
                
                return idx, {
                    "deep_reviews": deep_reviews,
                    "dr": dr,
                    "calls": local_calls,
                    "errors": local_errors,
                    "fallback_count": fallback_count
                }

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_idx = {executor.submit(_process_deep_scan, idx): idx for idx in borderline_queue}
                
                completed_deep = 0
                for future in concurrent.futures.as_completed(future_to_idx):
                    if p["stop_requested"]:
                        log("Stopped during deep scans.")
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                        
                    completed_deep += 1
                    p["progress"] = 70 + int((completed_deep / len(borderline_queue)) * 20)
                    
                    try:
                        idx, res = future.result()
                        if "error" in res:
                            leads[idx]["clinic_data"]["enrichment_note"] = res["error"]
                            continue
                            
                        deep_reviews = res["deep_reviews"]
                        dr = res["dr"]
                        
                        record_usage(len(deep_reviews))
                        _calls["outscraper_reviews"] += res["calls"]["outscraper"]
                        _calls["gemini"] += res["calls"]["gemini"]
                        p["fallback_count"] = p.get("fallback_count", 0) + res["fallback_count"]
                        p["run_errors"].extend(res["errors"])
                        
                        leads[idx]["clinic_data"].update({
                            "pain_review_count":    dr["pain_review_count"],
                            "pain_categories":      dr["pain_categories"],
                            "worst_review_snippet": dr["worst_review_snippet"],
                            "review_source":        "outscraper_deep",
                            "enrichment_note":      f"Deep review scan via Outscraper (n={len(deep_reviews)})",
                        })
                        leads[idx]["review_data"] = dr
                        new_score, new_signals    = calculate_pain_score(leads[idx]["clinic_data"])
                        leads[idx]["pain_score"]  = new_score
                        leads[idx]["signals"]     = new_signals
                        
                    except Exception as e:
                        p["run_errors"].append(f"Unexpected deep scan error: {e}")

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

            from datetime import datetime as _dt
            final_leads.append({
                "City":                location,  # location is already the resolved_location format
                "Search Radius":       f"{radius_miles} mi",
                "Run Date":            _dt.utcnow().strftime("%Y-%m-%d"),
                "Place ID":            lead["place_id"],
                "Clinic Name":         details.get("name", ""),
                "Classification":      classification,
                "Specialty":           specialty,
                "Address":             details.get("formatted_address", ""),
                "Website":             details.get("website", ""),
                "Phone Number":        details.get("formatted_phone_number", ""),
                "Best Contact Found":  "Office Manager",
                "Contact Role":        "Office Manager",
                "Contact Email":       clinic_data.get("extracted_email", ""),
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
                "Review Method":       review_data.get("review_method", "pattern"),
                "reviews_json":        reviews_json,
            })

        # Record the run first so we can link saved leads to the run_id!
        run_id = None
        try:
            run_id = record_run(
                location=location,
                geocode_calls=_calls["geocode"],
                search_calls=_calls["search"],
                detail_calls=_calls["detail"],
                adzuna_calls=_calls["adzuna"],
                outscraper_reviews=_calls["outscraper_reviews"],
                clinics_found=len(leads),
                leads_found=len(final_leads),
                stopped_early=p.get("stop_requested", False),
                radius_miles=radius_miles,
                pattern_fallback_count=p.get("fallback_count", 0),
                run_errors=p.get("run_errors", []),
                gemini_calls=_calls["gemini"],
            )
            p["last_run_id"] = run_id
        except Exception as e:
            pass

        for lead, fl in zip(leads, final_leads):
            details        = lead["details"]
            clinic_data    = lead["clinic_data"]
            signals        = lead["signals"]
            specialty      = lead["specialty"]
            pain_score     = lead["pain_score"]
            classification = lead["classification"]
            outreach_angle = fl["Outreach Angle"]
            review_depth_label = fl["Review Data Depth"]
            reviews_json   = fl["reviews_json"]

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
                email=clinic_data.get("extracted_email", ""),
                run_id=run_id,
            )

        p["leads_df"] = pd.DataFrame(final_leads)
        p["progress"] = 100
        log(f"Done — {len(final_leads)} leads collected.")

        try:
            import os
            if os.path.exists("/Users/yajatparmar"):
                from datetime import datetime as _dt
                with open("test_runs_log.txt", "a") as f:
                    ts_str = _dt.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                    f.write(f"- Run: {location} at {radius_miles}mi radius, found {len(final_leads)} leads on {ts_str}\n")
        except Exception:
            pass

    except Exception as e:
        p["error"] = f"An unexpected error occurred: {e}"
    finally:
        if not p.get("last_run_id"):
            try:
                run_id = record_run(
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
                    pattern_fallback_count=p.get("fallback_count", 0),
                    run_errors=p.get("run_errors", []),
                    gemini_calls=_calls["gemini"],
                )
                p["last_run_id"] = run_id
            except Exception:
                pass

        # Push leads to Google Sheets (best-effort, non-blocking)
        try:
            from utils.sheets import append_leads_to_sheet
            if p.get("leads_df") is not None and not p["leads_df"].empty:
                from datetime import datetime as _dt
                sheets_result = append_leads_to_sheet(
                    df=p["leads_df"],
                    location=location,
                    run_date=_dt.utcnow().strftime("%Y-%m-%d"),
                )
                p["sheets_result"] = sheets_result
        except Exception:
            p["sheets_result"] = None

        p["last_calls"] = dict(_calls)
        p["running"] = False


# ── Cached geocode for map preview (separate from pipeline geocode) ─────────────
@st.cache_data(show_spinner=False)
def _geocode_for_map(location_str: str, api_key: str):
    """Return (lat, lng, city_label) or None if geocoding fails."""
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": location_str, "key": api_key},
            timeout=8,
        )
        data = resp.json()
        if data.get("status") != "OK" or not data.get("results"):
            return None
        loc = data["results"][0]["geometry"]["location"]
        # Build a short city label from address components
        components = data["results"][0].get("address_components", [])
        city, state = "", ""
        for comp in components:
            if "locality" in comp["types"]:
                city = comp["short_name"]
            if "administrative_area_level_1" in comp["types"]:
                state = comp["short_name"]
        label = f"{city}, {state}" if city and state else location_str
        return loc["lat"], loc["lng"], label
    except Exception:
        return None


def _reverse_geocode(lat: float, lng: float, api_key: str):
    """Return 'City, ST' string from lat/lng, or None on failure."""
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"latlng": f"{lat},{lng}", "key": api_key},
            timeout=8,
        )
        data = resp.json()
        if data.get("status") != "OK" or not data.get("results"):
            return None
        components = data["results"][0].get("address_components", [])
        city, state = "", ""
        for comp in components:
            if "locality" in comp["types"]:
                city = comp["short_name"]
            if "administrative_area_level_1" in comp["types"]:
                state = comp["short_name"]
        if city and state:
            return f"{city}, {state}"
        return None
    except Exception:
        return None


# ── Sidebar controls ────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("Location")
    if "_map_clicked_location" in st.session_state:
        st.session_state["location_input"] = st.session_state.pop("_map_clicked_location")
    if "location_input" not in st.session_state:
        st.session_state["location_input"] = ""
    location = st.text_input(
        "Location",
        placeholder="City, State or ZIP",
        label_visibility="collapsed",
        disabled=_p["running"],
        key="location_input",
    )

    if "radius_miles_slider" not in st.session_state:
        st.session_state["radius_miles_slider"] = 25

    _temp_center_lat, _temp_center_lng = 39.5, -98.35
    if location and len(location) >= 3 and GOOGLE_PLACES_API_KEY:
        _geo_temp = _geocode_for_map(location, GOOGLE_PLACES_API_KEY)
        if _geo_temp:
            _temp_center_lat, _temp_center_lng, _ = _geo_temp

    _curr_rad = st.session_state["radius_miles_slider"]
    _dynamic_map_key = f"folium_map_{_temp_center_lat}_{_temp_center_lng}_{_curr_rad}"

    # Purge stale map state for any radius other than the current one.
    # Without this, revisiting a radius (e.g. 25→10→25) restores the old zoom
    # from the prior visit and the zoom-sync code overrides the slider choice.
    for _stale_key in [k for k in st.session_state if k.startswith("folium_map_") and k != _dynamic_map_key]:
        del st.session_state[_stale_key]

    if _dynamic_map_key in st.session_state and st.session_state[_dynamic_map_key] is not None:
        _map_state = st.session_state[_dynamic_map_key]
        if isinstance(_map_state, dict) and "zoom" in _map_state:
            _map_zoom_val = _map_state["zoom"]
            _rad_to_zoom = {10: 9, 25: 8, 50: 7}
            _expected_zoom = _rad_to_zoom.get(_curr_rad, 8)
            # Only sync when the user manually scrolled the map (zoom differs from what
            # the slider would set), not when we just rendered at the programmatic zoom.
            if abs(_map_zoom_val - _expected_zoom) >= 1:
                if _map_zoom_val >= 9:
                    _new_rad = 10
                elif _map_zoom_val == 8:
                    _new_rad = 25
                else:
                    _new_rad = 50
                if _new_rad != _curr_rad:
                    st.session_state["radius_miles_slider"] = _new_rad
                    st.rerun()

    st.markdown("Search Radius")
    radius_miles = st.select_slider(
        "Radius",
        options=[10, 25, 50],
        key="radius_miles_slider",
        label_visibility="collapsed",
        disabled=_p["running"],
        format_func=lambda x: f"{x} mi",
    )

    # ── Mini map preview ────────────────────────────────────────────────────────
    _map_center_lat, _map_center_lng, _map_zoom = 39.5, -98.35, 3
    _map_marker = None

    if location and len(location) >= 3 and GOOGLE_PLACES_API_KEY:
        _geo = _geocode_for_map(location, GOOGLE_PLACES_API_KEY)
        if _geo:
            _map_center_lat, _map_center_lng, _city_label = _geo
            _zoom_map = {10: 9, 25: 8, 50: 7}
            _map_zoom = _zoom_map.get(radius_miles, 10)
            _map_marker = (_map_center_lat, _map_center_lng, _city_label)

    _m = folium.Map(
        location=[_map_center_lat, _map_center_lng],
        zoom_start=_map_zoom,
        tiles="OpenStreetMap",
        zoom_control=True,
        scrollWheelZoom=True,
        attributionControl=False,
    )

    if _map_marker:
        folium.Marker(
            location=[_map_marker[0], _map_marker[1]],
            popup=_map_marker[2],
            icon=folium.Icon(color="purple", icon="circle", prefix="fa"),
        ).add_to(_m)
        folium.Circle(
            location=[_map_marker[0], _map_marker[1]],
            radius=radius_miles * 1609.34,
            color="#6366f1",
            fill=True,
            fill_color="#6366f1",
            fill_opacity=0.1,
            weight=1.5,
        ).add_to(_m)

    MeasureControl(
        position="topright",
        primary_length_unit="miles",
        secondary_length_unit="feet",
        primary_area_unit="sqmiles",
    ).add_to(_m)

    _m.add_child(_ImperialScale())

    _map_data = st_folium(
        _m,
        height=220,
        use_container_width=True,
        returned_objects=["last_clicked", "zoom"],
        key=_dynamic_map_key,
    )

    # Click-to-select: reverse geocode the clicked point
    if _map_data and _map_data.get("last_clicked"):
        _clicked = _map_data["last_clicked"]
        _clicked_lat = _clicked.get("lat")
        _clicked_lng = _clicked.get("lng")
        last_processed = st.session_state.get("_last_clicked_processed")
        if last_processed != (_clicked_lat, _clicked_lng):
            st.session_state["_last_clicked_processed"] = (_clicked_lat, _clicked_lng)
            if _clicked_lat is not None and _clicked_lng is not None and GOOGLE_PLACES_API_KEY:
                _rev = _reverse_geocode(_clicked_lat, _clicked_lng, GOOGLE_PLACES_API_KEY)
                if _rev and _rev != st.session_state.get("location_input", ""):
                    st.session_state["_map_clicked_location"] = _rev
                    st.rerun()

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

    st.markdown("---")

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

    from utils.usage_tracker import get_monthly_stats
    _stats = get_monthly_stats()
    _reviews_used = _stats.get("outscraper", {}).get("reviews_used", 0)
    st.caption(f"Outscraper: {_reviews_used} reviews used this month")


# ── Page header ─────────────────────────────────────────────────────────────────
st.markdown(
    "<div class='page-header-linear'>"
    "<span class='bc-parent'>Kairos</span>"
    "<span class='bc-sep'>›</span>"
    "<span class='bc-current'>Find Leads</span>"
    "</div>",
    unsafe_allow_html=True,
)

from utils.sheets import SPREADSHEET_ID as _LEADS_SPREADSHEET_ID

st.link_button(
    "Open Google Sheet",
    f"https://docs.google.com/spreadsheets/d/{_LEADS_SPREADSHEET_ID}",
    icon=":material/table_chart:",
)

# ── API warnings ────────────────────────────────────────────────────────────────
if not GOOGLE_PLACES_API_KEY:
    st.error("Google Places API key not configured. Add `GOOGLE_PLACES_API_KEY` to your `.env` file.")
if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
    st.warning("Adzuna API not configured — hiring signals will be skipped.")
if not OUTSCRAPER_API_KEY:
    st.info("Outscraper not configured — deep review scans will be skipped.")


@st.dialog("Run Already Exists")
def confirm_run_dialog(location_str, radius, date_str, pipeline_state, max_res):
    st.write(
        f"You already searched **{location_str}** at a **{radius}mi radius** on **{date_str}**."
    )
    st.write("Would you like to proceed anyway or cancel?")
    col_cancel, col_proceed = st.columns(2)
    with col_cancel:
        if st.button("Cancel Search", use_container_width=True):
            st.rerun()
    with col_proceed:
        if st.button("Proceed Anyway", use_container_width=True, type="primary"):
            pipeline_state["running"]    = True
            pipeline_state["leads_df"]   = None
            pipeline_state["gemini_key"] = _get_secret("GEMINI_API_KEY")
            threading.Thread(
                target=_run_pipeline,
                args=(pipeline_state, location_str, radius, max_res),
                daemon=True,
            ).start()
            st.rerun()


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
    if prior_run:
        from datetime import datetime as _dt
        try:
            prior_ts = _dt.fromisoformat(prior_run["timestamp"].replace("Z", "+00:00"))
            prior_date_str = prior_ts.strftime("%b %d, %Y")
        except Exception:
            prior_date_str = prior_run.get("timestamp", "")
        confirm_run_dialog(location.strip(), radius_miles, prior_date_str, _p, max_results)
        st.stop()

    _p["running"]    = True
    _p["leads_df"]   = None
    _p["gemini_key"] = _get_secret("GEMINI_API_KEY")

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
    if st.button("New Search", type="secondary"):
        _p["leads_df"] = None
        _p["error"] = None
        st.rerun()

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
                    f":material/history: {len(skipped)} clinic{'s' if len(skipped) != 1 else ''} "
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
                                st.session_state["history_target_lead_place_id"] = sc['place_id']
                                st.switch_page("views/history.py")

        # ── Stat blocks ─────────────────────────────
        high_ct   = len(df[df["Pain Score"] >= 6])
        strong_ct = len(df[(df["Pain Score"] >= 4) & (df["Pain Score"] < 6)])
        avg_score = round(df["Pain Score"].mean(), 1)
        deep_ct   = len(df[df["Review Data Depth"] == "Deep scan"])
        hiring_ct = len(df[df["Pain Signal Type"].str.contains("iring", na=False)])

        _lc       = _p.get("last_calls", {})
        _g_cost   = estimated_google_cost(_lc.get("geocode", 0), _lc.get("search", 0), _lc.get("detail", 0))
        _o_cost   = estimated_outscraper_cost(_lc.get("outscraper_reviews", 0))
        _t_cost   = _g_cost + _o_cost

        st.markdown(
            f"<div class='stat-blocks' style='margin:20px 0 18px'>"
            f"<div class='stat-block'><div class='sl'>Total Leads</div><div class='sv'>{len(df)}</div></div>"
            f"<div class='stat-block'><div class='sl'>High Priority</div>"
            f"<div class='sv' style='color:#ef4444'>{high_ct}</div><div class='ss'>Score ≥ 6</div></div>"
            f"<div class='stat-block'><div class='sl'>Strong Signal</div>"
            f"<div class='sv' style='color:#f97316'>{strong_ct}</div><div class='ss'>Score 4–5</div></div>"
            f"<div class='stat-block'><div class='sl'>Avg Score</div><div class='sv'>{avg_score}</div></div>"
            f"<div class='stat-block'><div class='sl'>Deep Scans</div>"
            f"<div class='sv'>{deep_ct}</div><div class='ss'>Outscraper enriched</div></div>"
            f"<div class='stat-block'><div class='sl'>Hiring Signals</div>"
            f"<div class='sv'>{hiring_ct}</div><div class='ss'>Hiring detected</div></div>"
            f"<div class='stat-block'><div class='sl'>Run Cost</div>"
            f"<div class='sv'>${_t_cost:.3f}</div>"
            f"<div class='ss'>Google ${_g_cost:.3f} · OS ${_o_cost:.3f}</div></div>"
            f"</div>",
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
            # Sheets status
            sheets_result = _p.get("sheets_result")
            if sheets_result is not None:
                if "error" in sheets_result:
                    if sheets_result["error"] == "Sheets not configured":
                        st.caption("Sheets: not configured")
                    else:
                        st.caption(f"Sheets: error — {sheets_result['error']}")
                else:
                    tab = sheets_result.get("tab", "")
                    added = sheets_result.get("added", 0)
                    skipped = sheets_result.get("skipped", 0)
                    st.caption(f"Sheets: {added} added, {skipped} skipped → {tab}")
        with tool_c2:
            sort_by = st.selectbox(
                "Sort",
                options=["Pain Score ↓", "Rating ↓", "Rating ↑", "Name ↑"],
                label_visibility="collapsed",
                key="leads_sort",
            )
        with tool_c3:
            loc = _p.get("search_location", "unknown")
            fname_base = f"kairos_{loc.replace(' ','_').replace(',','')}_{datetime.now().strftime('%Y%m%d')}"
            with st.popover("Export", use_container_width=True):
                st.download_button(
                    "CSV (full)",
                    data=view_df.to_csv(index=False),
                    file_name=f"{fname_base}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
                try:
                    from utils.export import df_to_xlsx_bytes
                    st.download_button(
                        "XLSX (formatted)",
                        data=df_to_xlsx_bytes(view_df),
                        file_name=f"{fname_base}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )
                except Exception:
                    pass
                st.markdown("---")
                phones_emails = view_df[["Clinic Name", "Phone Number", "Contact Email", "Address"]].copy()
                st.download_button(
                    "Phones & Emails",
                    data=phones_emails.to_csv(index=False),
                    file_name=f"{fname_base}_contacts.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
                outreach = view_df[["Clinic Name", "Pain Signal Type", "Pain Score", "Outreach Angle", "Phone Number", "Contact Email"]].copy()
                st.download_button(
                    "Outreach List",
                    data=outreach.to_csv(index=False),
                    file_name=f"{fname_base}_outreach.csv",
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

        # Fallback banner — shown when Gemini was unavailable for some clinics
        if _p.get("fallback_count", 0) > 0:
            st.warning(
                f"{_p['fallback_count']} clinic(s) used pattern matching — "
                "Gemini was unavailable during this run. "
                "Leads marked 'pattern' may have lower review accuracy."
            )

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
                method = row.get("Review Method", "")
                method_flag = "  · pattern" if method == "pattern_fallback" else ""

                label = f"{name}  ·  {city}  ·  Score {score}{rating_str}{method_flag}"

                with st.expander(label, expanded=False):
                    from utils.helpers import render_lead_card
                    render_lead_card(row)

# ── Landing / idle state ─────────────────────────────────────────────────────────
elif leads_df is None and not _p["running"] and not _p["error"]:
    from utils.usage_tracker import get_run_history as _get_run_history
    _hist = _get_run_history(limit=200)
    _total_runs   = len(_hist)
    _total_leads  = sum(r.get("leads_found", 0) for r in _hist)
    _unique_cities = len({r.get("location", "") for r in _hist})

    # ── Stats row ────────────────────────────────────────────────────────────
    if _total_runs > 0:
        _sc1, _sc2, _sc3 = st.columns(3)
        _sc1.metric("Total Runs", _total_runs)
        _sc2.metric("Leads Found", _total_leads)
        _sc3.metric("Cities Searched", _unique_cities)
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── How it works ─────────────────────────────────────────────────────────
    st.markdown(
        """
        <div style='background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;padding:24px 28px;margin:8px 0 16px'>
          <div style='font-size:15px;font-weight:600;color:#183e34;margin-bottom:16px'>How it works</div>
          <div style='display:flex;flex-direction:column;gap:14px'>
            <div style='display:flex;align-items:flex-start;gap:14px'>
              <div style='min-width:28px;height:28px;border-radius:50%;background:#183e34;color:#ffffff;font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center'>1</div>
              <div style='color:#282a30;font-size:14px;padding-top:4px'>Enter a city + radius in the sidebar to define your search area</div>
            </div>
            <div style='display:flex;align-items:flex-start;gap:14px'>
              <div style='min-width:28px;height:28px;border-radius:50%;background:#183e34;color:#ffffff;font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center'>2</div>
              <div style='color:#282a30;font-size:14px;padding-top:4px'>Click <strong>Find Leads</strong> — we scan Google Maps for dental clinics and cross-reference Adzuna job listings for hiring signals</div>
            </div>
            <div style='display:flex;align-items:flex-start;gap:14px'>
              <div style='min-width:28px;height:28px;border-radius:50%;background:#183e34;color:#ffffff;font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center'>3</div>
              <div style='color:#282a30;font-size:14px;padding-top:4px'>Review scored leads sorted by pain signal strength — high-priority clinics at the top</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Recent activity ───────────────────────────────────────────────────────
    if _hist:
        from utils.usage_tracker import estimated_google_cost as _egc
        from utils.helpers import safe_parse_datetime as _spd
        _recent = _hist[:5]
        st.markdown(
            "<div style='font-size:11px;font-weight:700;color:#6b6f76;margin:4px 0 8px;"
            "text-transform:uppercase;letter-spacing:0.07em'>Recent Activity</div>",
            unsafe_allow_html=True,
        )
        for _ri, _r in enumerate(_recent):
            _r_loc    = _r.get("location", "Unknown")
            _r_leads  = _r.get("leads_found", 0)
            _r_clinics = _r.get("clinics_found", 0)
            _r_rad    = _r.get("radius_miles", 25) or 25
            _r_ts     = _r.get("timestamp", "")
            _r_id     = _r.get("id")
            _r_cost   = _egc(_r.get("geocode_calls", 0), _r.get("search_calls", 0), _r.get("detail_calls", 0))
            try:
                _r_date = _spd(_r_ts).strftime("%b %d") if _r_ts else ""
            except Exception:
                _r_date = _r_ts
            with st.expander(f"{_r_loc}  ·  {_r_leads} leads  ·  {_r_date}", expanded=False):
                st.markdown(
                    f"<div style='font-size:13px;color:#282a30;line-height:1.9'>"
                    f"Radius: <strong>{_r_rad} mi</strong> &nbsp;·&nbsp; "
                    f"Clinics scanned: <strong>{_r_clinics}</strong> &nbsp;·&nbsp; "
                    f"Leads: <strong>{_r_leads}</strong>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                if _r_id is not None:
                    if st.button(
                        "View full run in History",
                        key=f"_ra_view_{_ri}",
                        use_container_width=True,
                    ):
                        st.session_state["history_target_run"] = _r_id
                        st.switch_page("views/history.py")
