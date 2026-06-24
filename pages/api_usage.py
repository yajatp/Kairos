from datetime import datetime

import streamlit as st

from utils.usage_tracker import (
    get_monthly_stats,
    get_run_history,
    estimated_google_cost,
    estimated_outscraper_cost,
    using_supabase,
    GOOGLE_MONTHLY_CREDIT_USD,
    GOOGLE_GEOCODE_COST,
    GOOGLE_SEARCH_COST,
    GOOGLE_DETAIL_COST,
    OUTSCRAPER_REVIEW_COST,
    OUTSCRAPER_BILLING_OFFSET_USD,
    ADZUNA_DAILY_LIMIT,
)

# ── Page header ─────────────────────────────────────────────────────────────────
st.markdown(
    "<div class='page-header-linear'>"
    "<span class='bc-parent'>Kairos</span>"
    "<span class='bc-sep'>›</span>"
    "<span class='bc-current'>API Usage</span>"
    "</div>",
    unsafe_allow_html=True,
)

if using_supabase():
    st.success("Connected to Supabase — usage data is shared across all machines.")

stats = get_monthly_stats()
g = stats["google"]
a = stats["adzuna"]
o = stats["outscraper"]

month_label = datetime.strptime(stats["year_month"], "%Y-%m").strftime("%B %Y")
st.caption(f"Showing data for {month_label} · Resets automatically each calendar month")

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ── Google APIs ──────────────────────────────────────────────────────────────────
st.markdown("### Google Maps Platform")
st.caption(
    f"Geocoding \\${GOOGLE_GEOCODE_COST}/call · "
    f"Text Search \\${GOOGLE_SEARCH_COST}/call · "
    f"Place Details \\${GOOGLE_DETAIL_COST}/call · "
    f"\\${GOOGLE_MONTHLY_CREDIT_USD:.0f}/month free credit"
)

gc = g.get("geocode_calls", 0)
sc = g.get("search_calls", 0)
dc = g.get("detail_calls", 0)
total_cost       = estimated_google_cost(gc, sc, dc)
credit_used_pct  = min(total_cost / GOOGLE_MONTHLY_CREDIT_USD, 1.0)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Geocode Calls",       gc, help=f"${gc * GOOGLE_GEOCODE_COST:.3f} est.")
col2.metric("Text Search Calls",   sc, help=f"${sc * GOOGLE_SEARCH_COST:.3f} est.")
col3.metric("Place Detail Calls",  dc, help=f"${dc * GOOGLE_DETAIL_COST:.3f} est.")
col4.metric("Est. Cost",           f"${total_cost:.2f}", help=f"Out of ${GOOGLE_MONTHLY_CREDIT_USD:.0f} free credit")

st.progress(
    credit_used_pct,
    text=f"${total_cost:.2f} / ${GOOGLE_MONTHLY_CREDIT_USD:.0f} free credit used ({credit_used_pct*100:.1f}%)",
)

st.markdown("---")

# ── Outscraper ───────────────────────────────────────────────────────────────────
st.markdown("### Outscraper — Deep Reviews")
st.caption(
    f"\\${OUTSCRAPER_REVIEW_COST}/review · "
    f"includes \\${OUTSCRAPER_BILLING_OFFSET_USD:.2f} pre-tracking offset — "
    "reset to 0 when switching to company APIs"
)

reviews_used = o.get("reviews_used", 0)
o_cost_month = estimated_outscraper_cost(reviews_used)

col1, col2, col3 = st.columns(3)
col1.metric("Reviews Pulled This Month", reviews_used)
col2.metric("Est. Outscraper Cost",      f"${o_cost_month:.2f}")
col3.metric("Month",                     datetime.now().strftime("%B %Y"))

st.markdown("---")

# ── Adzuna ───────────────────────────────────────────────────────────────────────
st.markdown("### Adzuna — Job Signals")
st.caption(f"Evaluation-use limit: ~{ADZUNA_DAILY_LIMIT} calls/day")

adzuna_calls = a.get("job_fetch_calls", 0)
col1, col2   = st.columns(2)
col1.metric("Job Fetch Calls This Month", adzuna_calls)
col2.metric("Est. Calls Today", "—", help="Per-day tracking not yet implemented")

st.info("Adzuna data is used under evaluation terms. Review their commercial licensing before production use.")

st.markdown("---")

# ── Recent runs ──────────────────────────────────────────────────────────────────
st.markdown("### Recent Runs")
st.caption("Last 20 runs")

history = get_run_history(20)

if not history:
    st.caption("No runs recorded yet.")
else:
    rows = []
    for r in history:
        ts = r.get("timestamp", "")
        try:
            ts_fmt = datetime.fromisoformat(ts).strftime("%b %d %H:%M")
        except Exception:
            ts_fmt = ts

        g_cost = estimated_google_cost(
            r.get("geocode_calls", 0),
            r.get("search_calls", 0),
            r.get("detail_calls", 0),
        )
        o_cost = estimated_outscraper_cost(r.get("outscraper_reviews", 0))
        rows.append({
            "Time":               ts_fmt,
            "Location":           r.get("location", ""),
            "Clinics Found":      r.get("clinics_found", 0),
            "Leads Output":       r.get("leads_found", 0),
            "Geocodes":           r.get("geocode_calls", 0),
            "Searches":           r.get("search_calls", 0),
            "Details":            r.get("detail_calls", 0),
            "Outscraper Reviews": r.get("outscraper_reviews", 0),
            "Google Cost":        f"${g_cost:.3f}",
            "Outscraper Cost":    f"${o_cost:.3f}",
            "Total Cost":         f"${g_cost + o_cost:.3f}",
            "Stopped Early":      "Yes" if r.get("stopped_early") else "—",
        })

    st.dataframe(rows, use_container_width=True, hide_index=True)

st.markdown("---")
st.caption(
    "Google cost estimates use published Maps Platform pricing. "
    "Outscraper estimated at $3/1,000 reviews. "
    "Check your billing dashboards for actuals."
)
