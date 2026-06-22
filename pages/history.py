from collections import defaultdict
from datetime import datetime

import pandas as pd
import streamlit as st

from utils.usage_tracker import get_run_history, estimated_google_cost, get_leads_for_run

_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "Washington D.C.",
}
_STATE_ABBRS = set(_STATE_NAMES.keys())


def _parse_location(loc: str) -> tuple[str, str]:
    if not loc or not loc.strip():
        return "Unknown", "Unknown"
    loc = loc.strip()
    parts = [p.strip() for p in loc.split(",")]
    if len(parts) >= 2:
        tail = parts[-1].split()[0].upper()
        if tail in _STATE_ABBRS:
            return _STATE_NAMES[tail], ", ".join(parts[:-1])
    words = loc.split()
    if len(words) >= 2 and words[-1].upper() in _STATE_ABBRS:
        return _STATE_NAMES[words[-1].upper()], " ".join(words[:-1])
    return "Other", loc


def _fmt_ts(ts: str, fmt: str = "%b %d, %Y  %H:%M") -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime(fmt)
    except Exception:
        return ts


def _leads_to_df(leads: list[dict]) -> pd.DataFrame:
    """Convert Supabase lead rows to a display DataFrame."""
    if not leads:
        return pd.DataFrame()
    rows = []
    for l in leads:
        rows.append({
            "Clinic Name":       l.get("name", ""),
            "Classification":    l.get("classification", ""),
            "Specialty":         l.get("specialty", ""),
            "Address":           l.get("address", ""),
            "Phone Number":      l.get("phone", ""),
            "Website":           l.get("website", ""),
            "Pain Score":        l.get("pain_score", 0),
            "Pain Signal Type":  l.get("signals", ""),
            "Outreach Angle":    l.get("outreach_angle", ""),
            "Google Rating":     l.get("rating", ""),
            "Total Reviews":     l.get("total_reviews", 0),
            "Extended Hours":    "Yes" if l.get("extended_hours") else "No",
            "Online Booking":    "Yes" if l.get("online_booking") else "No",
            "Review Data Depth": l.get("review_depth", ""),
        })
    return pd.DataFrame(rows)


def _render_run_expander(r: dict, key_prefix: str) -> None:
    """Render the full content of a single run expander."""
    ts      = r.get("timestamp", "")
    g_cost  = estimated_google_cost(
        r.get("geocode_calls", 0), r.get("search_calls", 0), r.get("detail_calls", 0)
    )
    stopped = r.get("stopped_early", False)
    ts_fmt  = _fmt_ts(ts)
    location = r.get("location", "")
    fname_base = (
        f"kairos_{location.replace(' ','_').replace(',','')}_{datetime.now().strftime('%Y%m%d')}"
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Results**")
        st.write(f"Clinics processed: {r.get('clinics_found', 0)}")
        st.write(f"Leads output: {r.get('leads_found', 0)}")
        if stopped:
            st.warning("Stopped early by user")
    with col2:
        st.markdown("**API Calls**")
        st.write(f"Geocode: {r.get('geocode_calls', 0)}")
        st.write(f"Text Search: {r.get('search_calls', 0)}")
        st.write(f"Place Details: {r.get('detail_calls', 0)}")
        st.write(f"Adzuna: {r.get('adzuna_calls', 0)}")
        st.write(f"Outscraper reviews: {r.get('outscraper_reviews', 0)}")
    with col3:
        st.markdown("**Cost**")
        st.write(f"Est. Google cost: ${g_cost:.3f}")
        st.write(f"Timestamp: {ts_fmt}")

    st.markdown("---")

    # ── View Leads toggle ─────────────────────────────────────────────────────
    view_key = f"{key_prefix}_view_leads"
    if st.button("View Leads", key=f"{key_prefix}_btn_view"):
        st.session_state[view_key] = not st.session_state.get(view_key, False)

    if st.session_state.get(view_key, False):
        leads = get_leads_for_run(location, ts)
        if not leads:
            st.info("No leads found in Supabase for this run. Leads are only available when Supabase is configured and the run saved leads.")
        else:
            leads_df = _leads_to_df(leads)
            st.caption(f"{len(leads)} leads for this run")

            # ── Export buttons ────────────────────────────────────────────────
            exp_c1, exp_c2, exp_c3 = st.columns([4, 1.2, 1.2])
            with exp_c2:
                st.download_button(
                    "Export CSV",
                    data=leads_df.to_csv(index=False),
                    file_name=f"{fname_base}.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key=f"{key_prefix}_csv",
                )
            with exp_c3:
                try:
                    from utils.export import df_to_xlsx_bytes
                    xlsx_bytes = df_to_xlsx_bytes(leads_df)
                    st.download_button(
                        "Export XLSX",
                        data=xlsx_bytes,
                        file_name=f"{fname_base}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key=f"{key_prefix}_xlsx",
                    )
                except Exception:
                    st.caption("XLSX unavailable")

            # ── Add to Sheet button ───────────────────────────────────────────
            sheets_state_key = f"{key_prefix}_sheets_result"
            if st.button("Add to Sheet", key=f"{key_prefix}_btn_sheets"):
                from utils.sheets import append_leads_to_sheet
                run_date = _fmt_ts(ts, "%Y-%m-%d")
                result = append_leads_to_sheet(leads_df, location, run_date)
                st.session_state[sheets_state_key] = result

            sheets_result = st.session_state.get(sheets_state_key)
            if sheets_result is not None:
                if "error" in sheets_result:
                    if sheets_result["error"] == "Sheets not configured":
                        st.info("Google Sheets not configured — add `GOOGLE_SERVICE_ACCOUNT_JSON` to secrets.")
                    else:
                        st.error(f"Sheets error: {sheets_result['error']}")
                else:
                    added   = sheets_result.get("added", 0)
                    skipped = sheets_result.get("skipped", 0)
                    tab     = sheets_result.get("tab", "")
                    if added == 0 and skipped > 0:
                        st.success(f"All {skipped} leads already in sheet → {tab}")
                    else:
                        st.success(f"Added {added} leads to {tab}" + (f" ({skipped} skipped)" if skipped else ""))

            # ── Lead cards ────────────────────────────────────────────────────
            from utils.helpers import render_lead_card

            sorted_leads = sorted(leads, key=lambda l: l.get("pain_score", 0), reverse=True)
            for lead in sorted_leads:
                score = lead.get("pain_score", 0)
                name  = lead.get("name", "Unknown")
                city_parts = [p.strip() for p in lead.get("address", "").split(",")]
                city  = city_parts[-3] if len(city_parts) >= 3 else (city_parts[-2] if len(city_parts) >= 2 else "")
                label = f"{name}  ·  {city}  ·  Score {score}"
                with st.expander(label, expanded=False):
                    render_lead_card(lead)


# ── Page header ─────────────────────────────────────────────────────────────────
st.markdown(
    "<div class='page-header-linear'>"
    "<span class='bc-parent'>Kairos</span>"
    "<span class='bc-sep'>›</span>"
    "<span class='bc-current'>History</span>"
    "</div>",
    unsafe_allow_html=True,
)

history = get_run_history(200)

if not history:
    st.markdown(
        """
        <div class='empty-state'>
          <div class='empty-state-title'>No runs yet</div>
          <div class='empty-state-body'>
            Go to Find Leads and run a search — every run is recorded here automatically.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

# ── Summary stats ────────────────────────────────────────────────────────────────
total_runs   = len(history)
total_leads  = sum(r.get("leads_found", 0) for r in history)
total_cost   = sum(
    estimated_google_cost(r.get("geocode_calls", 0), r.get("search_calls", 0), r.get("detail_calls", 0))
    for r in history
)
unique_cities = len({r.get("location", "") for r in history})

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Runs",            total_runs)
c2.metric("Total Leads Generated", total_leads)
c3.metric("Unique Locations",      unique_cities)
c4.metric("Est. Cumulative Cost",  f"${total_cost:.2f}")

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
st.markdown("---")

# ── Tabs ─────────────────────────────────────────────────────────────────────────
tab_chrono, tab_geo = st.tabs(["Chronological", "By Location"])

# ── Chronological ────────────────────────────────────────────────────────────────
with tab_chrono:
    st.caption("Most recent runs first.")

    for i, r in enumerate(history):
        ts      = r.get("timestamp", "")
        stopped = r.get("stopped_early", False)
        ts_fmt  = _fmt_ts(ts)
        warn    = "⚠️ " if stopped else ""
        label   = f"{warn}{r.get('location', 'Unknown')} — {r.get('leads_found', 0)} leads · {ts_fmt}"

        with st.expander(label, expanded=False):
            _render_run_expander(r, key_prefix=f"chrono_{i}")

# ── By Location ──────────────────────────────────────────────────────────────────
with tab_geo:
    st.caption("Grouped by state, then city.")

    geo: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in history:
        state, city = _parse_location(r.get("location", ""))
        geo[state][city].append(r)

    for state in sorted(geo.keys()):
        cities      = geo[state]
        state_runs  = sum(len(runs) for runs in cities.values())
        state_leads = sum(run.get("leads_found", 0) for runs in cities.values() for run in runs)
        state_label = f"**{state}** — {state_runs} run{'s' if state_runs != 1 else ''}, {state_leads} leads"

        with st.expander(state_label, expanded=False):
            for city in sorted(cities.keys()):
                city_runs  = sorted(cities[city], key=lambda r: r.get("timestamp", ""), reverse=True)
                city_leads = sum(r.get("leads_found", 0) for r in city_runs)
                run_word   = "run" if len(city_runs) == 1 else "runs"

                st.markdown(
                    f"**{city}** &nbsp;"
                    f"<span style='font-size:12px;color:#9ca3af'>"
                    f"{len(city_runs)} {run_word} · {city_leads} leads total"
                    f"</span>",
                    unsafe_allow_html=True,
                )

                for j, r in enumerate(city_runs):
                    g_cost  = estimated_google_cost(
                        r.get("geocode_calls", 0),
                        r.get("search_calls", 0),
                        r.get("detail_calls", 0),
                    )
                    stopped = r.get("stopped_early", False)
                    ts_fmt  = _fmt_ts(r.get("timestamp", ""))

                    rc = st.columns([3, 1, 1, 1, 1, 1])
                    rc[0].markdown(
                        f"{'⚠️ ' if stopped else ''}{ts_fmt}"
                        + (" *(stopped)*" if stopped else "")
                    )
                    rc[1].metric("Leads",    r.get("leads_found", 0))
                    rc[2].metric("Clinics",  r.get("clinics_found", 0))
                    rc[3].metric("Searches", r.get("search_calls", 0))
                    rc[4].metric("Details",  r.get("detail_calls", 0))
                    rc[5].metric("Cost",     f"${g_cost:.3f}")

                    # Per-run expander with leads / export / sheets
                    run_ts_fmt = _fmt_ts(r.get("timestamp", ""))
                    with st.expander(f"Details & Leads — {run_ts_fmt}", expanded=False):
                        _render_run_expander(r, key_prefix=f"geo_{state}_{city}_{j}")

                st.markdown("---")
