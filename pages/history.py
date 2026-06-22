from collections import defaultdict
from datetime import datetime

import streamlit as st

from utils.usage_tracker import get_run_history, estimated_google_cost

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

# ── B3 — Deep-link target run ────────────────────────────────────────────────────
_target_run_id = st.session_state.pop("history_target_run", None)

# ── Tabs ─────────────────────────────────────────────────────────────────────────
tab_chrono, tab_geo = st.tabs(["Chronological", "By Location"])

# ── Chronological ────────────────────────────────────────────────────────────────
with tab_chrono:
    st.caption("Most recent runs first.")

    for r in history:
        ts      = r.get("timestamp", "")
        g_cost  = estimated_google_cost(
            r.get("geocode_calls", 0), r.get("search_calls", 0), r.get("detail_calls", 0)
        )
        stopped  = r.get("stopped_early", False)
        ts_fmt   = _fmt_ts(ts)
        warn     = "⚠️ " if stopped else ""
        run_id   = r.get("id")
        expanded = (_target_run_id is not None and run_id == _target_run_id)

        label = f"{warn}{r.get('location', 'Unknown')} — {r.get('leads_found', 0)} leads · {ts_fmt}"

        with st.expander(label, expanded=expanded):
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

                for r in city_runs:
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

                st.markdown("---")
