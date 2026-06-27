from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import importlib
import utils.usage_tracker
importlib.reload(utils.usage_tracker)

from utils.usage_tracker import get_run_history, estimated_google_cost, estimated_outscraper_cost, estimated_gemini_cost, get_leads_for_run, OUTSCRAPER_BILLING_OFFSET_USD, get_leads_for_runs_bulk
from utils.helpers import safe_parse_datetime

# Section accent colors — match the API Usage page so the tools read consistently.
_C_LEADS = "#14756a"   # deep teal
_C_DONUT = "#b9692f"   # warm amber

_LEADS_SHEET_URL = "https://docs.google.com/spreadsheets/d/1UlBdK2z7UsP-_IFYhxK5IImmHCOGFKKvaGHUDw_dXHs"


def _donut_sheet_url() -> str:
    import os
    sid = os.getenv("DONUT_SPREADSHEET_ID", "").strip() or "1eEpIsP6zVoshFOayOr3sY_KybBAzc16K1RuNPMVfnd4"
    return f"https://docs.google.com/spreadsheets/d/{sid}"


def _section_banner(title: str, subtitle: str, color: str, bg: str) -> None:
    st.markdown(
        f"<div style='background:{bg};border-left:5px solid {color};border-radius:10px;"
        f"padding:12px 16px;margin:6px 0 16px;'>"
        f"<div style='font-size:19px;font-weight:700;color:{color};letter-spacing:-0.02em;'>{title}</div>"
        f"<div style='font-size:12px;color:#6b6f76;margin-top:3px;'>{subtitle}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

def toggle_view_leads(view_key: str) -> None:
    st.session_state[view_key] = not st.session_state.get(view_key, False)


def _fmt_ts(ts: str, fmt: str = "%b %d, %Y  %H:%M") -> str:
    try:
        return safe_parse_datetime(ts).strftime(fmt)
    except Exception:
        return ts


def _leads_to_df(leads: list[dict], radius_miles: int = 25, run_date: str = "") -> pd.DataFrame:
    """Convert Supabase lead rows to a display DataFrame with standardized columns."""
    from utils.helpers import extract_city
    import json
    if not leads:
        return pd.DataFrame()
    rows = []
    for l in leads:
        # Reconstruct Notes: Rating + Enrichment notes
        rating = l.get("rating", "")
        tot_rev = l.get("total_reviews", 0)
        notes_parts = [f"Rating: {rating} ({tot_rev} reviews)"]
        depth = l.get("review_depth", "")
        if depth:
            notes_parts.append(depth)

        # Reconstruct Evidence
        evidence = "No direct evidence found"
        raw_rj = l.get("reviews_json")
        worst_snippet = ""
        if raw_rj:
            try:
                rj = json.loads(raw_rj) if isinstance(raw_rj, str) else raw_rj
                if rj:
                    worst = min(rj, key=lambda x: x.get("rating", 5))
                    worst_snippet = worst.get("text", "")
            except Exception:
                pass

        evidence_parts = []
        sig_str = l.get("signals", "")
        if "Hiring" in sig_str:
            evidence_parts.append("Hiring signal detected")
        if worst_snippet:
            evidence_parts.append(f'Review: "{worst_snippet[:200]}"')
        if evidence_parts:
            evidence = " | ".join(evidence_parts)

        r_date = run_date
        if not r_date and l.get("scored_at"):
            try:
                r_date = safe_parse_datetime(l.get("scored_at")).strftime("%Y-%m-%d")
            except Exception:
                r_date = l.get("scored_at")
        if not r_date:
            r_date = "Unknown"

        rows.append({
            "City":                l.get("run_location") or extract_city(l.get("address", "")),
            "Search Radius":       f"{radius_miles} mi",
            "Run Date":            r_date,
            "Place ID":            l.get("place_id", ""),
            "Clinic Name":         l.get("name", ""),
            "Classification":      l.get("classification", ""),
            "Specialty":           l.get("specialty", ""),
            "Address":             l.get("address", ""),
            "Website":             l.get("website", ""),
            "Phone Number":        l.get("phone", ""),
            "Best Contact Found":  "Office Manager",
            "Contact Role":        "Office Manager",
            "Contact Email":       "",
            "LinkedIn":            "",
            "Number of Locations": 1,
            "Pain Signal Type":    l.get("signals") or "None detected",
            "Evidence / Source":   evidence,
            "Pain Score":          l.get("pain_score", 0),
            "Outreach Angle":      l.get("outreach_angle", ""),
            "Notes":               " | ".join(notes_parts),
            "Google Rating":       rating,
            "Total Reviews":       tot_rev,
            "Hours Summary":       "",
            "Extended Hours":      "Yes" if l.get("extended_hours") else "No",
            "Online Booking":      "Yes" if l.get("online_booking") else "No",
            "Review Data Depth":   depth,
            "reviews_json":        l.get("reviews_json"),
        })
    return pd.DataFrame(rows)


def _render_run_expander(r: dict, key_prefix: str, target_lead_place_id: str | None = None) -> None:
    """Render the full content of a single run expander."""
    import json
    ts      = r.get("timestamp", "")
    run_id  = r.get("id")
    g_cost  = estimated_google_cost(
        r.get("geocode_calls", 0), r.get("search_calls", 0), r.get("detail_calls", 0)
    )
    o_cost  = estimated_outscraper_cost(r.get("outscraper_reviews", 0))
    t_cost  = g_cost + o_cost
    stopped = r.get("stopped_early", False)
    ts_fmt  = _fmt_ts(ts)
    location = r.get("location", "")
    radius_miles = r.get("radius_miles", 25)
    if not radius_miles:
        radius_miles = 25

    fname_base = (
        f"kairos_{location.replace(' ','_').replace(',','')}_{datetime.now().strftime('%Y%m%d')}"
    )

    # ── Lazy leads cache ─────────────────────────────────────────────────────────
    leads_cache_key = f"_leads_{run_id}" if run_id else f"_leads_{ts}"
    view_key = f"{key_prefix}_view_leads"

    # Deep-link: force view open and ensure cache is populated immediately
    if target_lead_place_id is not None and view_key not in st.session_state:
        st.session_state[view_key] = True

    # Fetch only when View Leads is active AND not already cached
    if st.session_state.get(view_key, False) and leads_cache_key not in st.session_state:
        with st.spinner("Loading leads..."):
            try:
                st.session_state[leads_cache_key] = get_leads_for_run(location, ts, run_id=run_id)
            except Exception:
                st.warning("Connection issue — click View Leads again to retry.")
                st.session_state[view_key] = False
                st.stop()

    leads = st.session_state.get(leads_cache_key, [])
    leads_df = (
        _leads_to_df(leads, radius_miles=radius_miles, run_date=_fmt_ts(ts, "%Y-%m-%d"))
        if leads else pd.DataFrame()
    )

    fallback_ct = r.get("pattern_fallback_count")  # None = pre-AI run; 0 = full AI; >0 = had fallbacks
    run_errors_raw = r.get("run_errors", "") or ""
    _stopped_html = ("<br><span style='color:#c2410c;font-size:12px;font-weight:500'>Stopped early</span>"
                     if stopped else "")
    _legacy_html = ("<br><span style='color:#6b6f76;font-size:12px;font-weight:500'>"
                    "Legacy run — pattern matching only</span>"
                    if fallback_ct is None else "")
    _fallback_html = (f"<br><span style='color:#b45309;font-size:12px;font-weight:500'>"
                      f"Pattern fallback: {fallback_ct} clinic(s)</span>"
                      if fallback_ct else "")
    st.markdown(
        "<div style='background:rgba(24,62,53,0.06);border-radius:8px;padding:14px 16px;"
        "border-left:3px solid #3abdaf;margin-bottom:12px'>"
        "<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px'>"
        "<div>"
        "<div style='font-size:10px;font-weight:700;color:#6b6f76;text-transform:uppercase;"
        "letter-spacing:0.07em;margin-bottom:8px'>Results</div>"
        f"<div style='font-size:13px;color:#282a30;line-height:1.8'>"
        f"Clinics processed: <strong>{r.get('clinics_found', 0)}</strong><br>"
        f"Leads output: <strong>{r.get('leads_found', 0)}</strong>{_stopped_html}{_legacy_html}{_fallback_html}</div></div>"
        "<div>"
        "<div style='font-size:10px;font-weight:700;color:#6b6f76;text-transform:uppercase;"
        "letter-spacing:0.07em;margin-bottom:8px'>API Calls</div>"
        f"<div style='font-size:13px;color:#282a30;line-height:1.8'>"
        f"Geocode: {r.get('geocode_calls', 0)}<br>"
        f"Text Search: {r.get('search_calls', 0)}<br>"
        f"Place Details: {r.get('detail_calls', 0)}<br>"
        f"Adzuna: {r.get('adzuna_calls', 0)}<br>"
        f"Outscraper: {r.get('outscraper_reviews', 0)}</div></div>"
        "<div>"
        "<div style='font-size:10px;font-weight:700;color:#6b6f76;text-transform:uppercase;"
        "letter-spacing:0.07em;margin-bottom:8px'>Cost</div>"
        f"<div style='font-size:13px;color:#282a30;line-height:1.8'>"
        f"Google: ${g_cost:.3f}<br>"
        f"Outscraper: ${o_cost:.3f}<br>"
        f"<strong>Total: ${t_cost:.3f}</strong><br>"
        f"<span style='color:#6b6f76;font-size:12px'>{ts_fmt}</span></div></div>"
        "</div></div>",
        unsafe_allow_html=True,
    )

    if run_errors_raw:
        try:
            import json as _json
            _errs = _json.loads(run_errors_raw) if isinstance(run_errors_raw, str) else run_errors_raw
        except Exception:
            _errs = [str(run_errors_raw)]
        with st.expander(f"Run errors ({len(_errs)})", expanded=False):
            for _err in _errs:
                st.caption(_err)

    st.markdown("---")

    # ── Export & Sheets buttons directly in summary ──────────────────────────
    exp_c1, exp_c2, exp_c3 = st.columns([1, 1, 1])
    with exp_c1:
        st.button(
            "View Leads",
            key=f"{key_prefix}_btn_view",
            on_click=toggle_view_leads,
            args=(view_key,),
            use_container_width=True,
        )
    with exp_c2:
        sheets_state_key = f"{key_prefix}_sheets_result"
        if leads_df.empty:
            st.button("Add to Sheet", disabled=True, use_container_width=True, key=f"{key_prefix}_btn_sheets")
            st.caption("Click 'View Leads' to load data")
        else:
            if st.button("Add to Sheet", key=f"{key_prefix}_btn_sheets", use_container_width=True):
                from utils.sheets import append_leads_to_sheet
                run_date = _fmt_ts(ts, "%Y-%m-%d")
                result = append_leads_to_sheet(leads_df, location, run_date)
                st.session_state[sheets_state_key] = result
    with exp_c3:
        with st.popover("Export", use_container_width=True):
            if not leads_df.empty:
                st.download_button(
                    "CSV",
                    data=leads_df.to_csv(index=False),
                    file_name=f"{fname_base}.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key=f"{key_prefix}_csv",
                )
                try:
                    from utils.export import df_to_xlsx_bytes
                    st.download_button(
                        "XLSX",
                        data=df_to_xlsx_bytes(leads_df),
                        file_name=f"{fname_base}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key=f"{key_prefix}_xlsx",
                    )
                except Exception:
                    pass
                st.markdown("---")
                phones_emails = leads_df[["Clinic Name", "Phone Number", "Contact Email", "Address"]].copy()
                st.download_button(
                    "Phones & Emails",
                    data=phones_emails.to_csv(index=False),
                    file_name=f"{fname_base}_contacts.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key=f"{key_prefix}_contacts",
                )
                outreach = leads_df[["Clinic Name", "Pain Signal Type", "Pain Score", "Outreach Angle", "Phone Number", "Contact Email"]].copy()
                st.download_button(
                    "Outreach List",
                    data=outreach.to_csv(index=False),
                    file_name=f"{fname_base}_outreach.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key=f"{key_prefix}_outreach",
                )
            else:
                st.caption("Click 'View Leads' to load data")

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

    st.markdown("---")

    if st.session_state.get(view_key, False):
        if not leads:
            st.info("No leads found in Supabase for this run. Leads are only available when Supabase is configured and the run saved leads.")
        else:
            st.markdown(
                "<div style='border-left:3px solid #183e34;padding-left:10px;margin:8px 0'>"
                "<span style='color:#183e34;font-weight:600'>Leads — sorted by pain score</span>"
                "</div>",
                unsafe_allow_html=True,
            )
            st.caption(f"{len(leads)} leads for this run")
            from utils.helpers import render_lead_card

            sorted_leads = sorted(leads, key=lambda l: l.get("pain_score", 0), reverse=True)
            for lead in sorted_leads:
                score = lead.get("pain_score", 0)
                name  = lead.get("name", "Unknown")
                city_parts = [p.strip() for p in lead.get("address", "").split(",")]
                city  = city_parts[-3] if len(city_parts) >= 3 else (city_parts[-2] if len(city_parts) >= 2 else "")
                label = f"{name}  ·  {city}  ·  Score {score}"
                is_lead_expanded = (target_lead_place_id is not None and lead.get("place_id") == target_lead_place_id)
                if is_lead_expanded:
                    st.markdown("<div id='target-lead-anchor'></div>", unsafe_allow_html=True)
                with st.expander(label, expanded=is_lead_expanded):
                    render_lead_card(lead)

            if target_lead_place_id is not None:
                scroll_js = """
                <script>
                    let attempts = 0;
                    const interval = setInterval(() => {
                        attempts++;
                        try {
                            const parentDoc = window.parent.document;
                            const target = parentDoc.getElementById('target-lead-anchor');
                            if (target) {
                                target.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                clearInterval(interval);
                            }
                        } catch (e) {
                            console.error("CORS / iframe access error:", e);
                            clearInterval(interval);
                        }
                        if (attempts > 50) {
                            clearInterval(interval);
                        }
                    }, 100);
                </script>
                """
                st.components.v1.html(scroll_js, height=0, width=0)


def _render_donut_run_expander(r: dict, key_prefix: str) -> None:
    """Render a single Donut Scraper run. Donut clinic rows live in the Google Sheet,
    not Supabase, so this shows the run summary + a link to the sheet (no View Leads)."""
    ts       = r.get("timestamp", "")
    search_c = r.get("search_calls", 0)
    gem_c    = r.get("gemini_calls", 0)
    g_cost   = estimated_google_cost(0, search_c, 0)
    gem_cost = estimated_gemini_cost(gem_c)
    t_cost   = g_cost + gem_cost
    ts_fmt   = _fmt_ts(ts)
    gem_used = "Yes" if gem_c else "No"

    st.markdown(
        "<div style='background:rgba(207,124,63,0.08);border-radius:8px;padding:14px 16px;"
        "border-left:3px solid #b9692f;margin-bottom:12px'>"
        "<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px'>"
        "<div>"
        "<div style='font-size:10px;font-weight:700;color:#6b6f76;text-transform:uppercase;"
        "letter-spacing:0.07em;margin-bottom:8px'>Results</div>"
        f"<div style='font-size:13px;color:#282a30;line-height:1.8'>"
        f"Clinics found: <strong>{r.get('clinics_found', 0)}</strong><br>"
        f"AI extraction: <strong>{gem_used}</strong></div></div>"
        "<div>"
        "<div style='font-size:10px;font-weight:700;color:#6b6f76;text-transform:uppercase;"
        "letter-spacing:0.07em;margin-bottom:8px'>API Calls</div>"
        f"<div style='font-size:13px;color:#282a30;line-height:1.8'>"
        f"Text Search: {search_c}<br>"
        f"Gemini: {gem_c}</div></div>"
        "<div>"
        "<div style='font-size:10px;font-weight:700;color:#6b6f76;text-transform:uppercase;"
        "letter-spacing:0.07em;margin-bottom:8px'>Cost</div>"
        f"<div style='font-size:13px;color:#282a30;line-height:1.8'>"
        f"Google: ${g_cost:.3f}<br>"
        f"Gemini: ${gem_cost:.4f}<br>"
        f"<strong>Total: ${t_cost:.3f}</strong><br>"
        f"<span style='color:#6b6f76;font-size:12px'>{ts_fmt}</span></div></div>"
        "</div></div>",
        unsafe_allow_html=True,
    )

    _ = key_prefix  # reserved for future per-run widgets
    st.caption("Clinic rows for this run live in the Donut Scraper Google Sheet.")
    st.link_button(
        "Open in Google Sheet",
        _donut_sheet_url(),
        icon=":material/table_chart:",
        use_container_width=False,
    )


# ── Page header ─────────────────────────────────────────────────────────────────
st.markdown(
    "<div class='page-header-linear'>"
    "<span class='bc-parent'>Kairos</span>"
    "<span class='bc-sep'>›</span>"
    "<span class='bc-current'>History</span>"
    "</div>",
    unsafe_allow_html=True,
)

if "history_limit" not in st.session_state:
    st.session_state["history_limit"] = 25

with st.spinner("Loading run history..."):
    history = get_run_history(st.session_state["history_limit"])

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

# ── Split runs by tool ───────────────────────────────────────────────────────────
leads_runs = [r for r in history if r.get("source") != "donut"]
donut_runs = [r for r in history if r.get("source") == "donut"]

# ── Prefetch leads in bulk for Find Leads runs so View Leads is instant ──────────
_run_ids_to_fetch = []
for r in leads_runs:
    _pf_id = r.get("id")
    if _pf_id is None:
        continue
    _pf_key = f"_leads_{_pf_id}"
    if _pf_key in st.session_state:
        continue
    if r.get("leads_found", 0) == 0:
        st.session_state[_pf_key] = []
        continue
    if r.get("pattern_fallback_count") is not None:
        _run_ids_to_fetch.append(_pf_id)

if _run_ids_to_fetch:
    try:
        _bulk_leads = get_leads_for_runs_bulk(_run_ids_to_fetch)
        for _rid in _run_ids_to_fetch:
            st.session_state[f"_leads_{_rid}"] = _bulk_leads.get(_rid, [])
    except Exception:
        pass

# ── Deep-link target run (Find Leads) ────────────────────────────────────────────
_target_run_id = st.session_state.pop("history_target_run", None)
_target_lead_place_id = st.session_state.pop("history_target_lead_place_id", None)


def _refresh_button(key: str) -> None:
    if st.button("Refresh", help="Reload run history from database", use_container_width=True, key=key):
        for k in list(st.session_state.keys()):
            if k.startswith("_leads_"):
                del st.session_state[k]
        st.session_state["history_limit"] = 25
        st.cache_data.clear()
        st.rerun()


def _load_more_button(key: str) -> None:
    if len(history) >= st.session_state["history_limit"]:
        if st.button("Load more runs", key=key):
            st.session_state["history_limit"] += 25
            st.rerun()


st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

# ── Tabs ─────────────────────────────────────────────────────────────────────────
tab_leads, tab_donut = st.tabs(["Find Leads", "Donut Scraper"])

# ── Find Leads ────────────────────────────────────────────────────────────────────
with tab_leads:
    _section_banner(
        "Find Leads — Run History",
        "Lead-gen runs, most recent first.",
        _C_LEADS, "rgba(58, 189, 175, 0.14)",
    )

    fl_leads = sum(r.get("leads_found", 0) for r in leads_runs)
    fl_locs  = len({r.get("location", "") for r in leads_runs})
    fl_cost  = sum(
        estimated_google_cost(r.get("geocode_calls", 0), r.get("search_calls", 0), r.get("detail_calls", 0))
        + estimated_outscraper_cost(r.get("outscraper_reviews", 0))
        + estimated_gemini_cost(r.get("gemini_calls", 0))
        for r in leads_runs
    ) + OUTSCRAPER_BILLING_OFFSET_USD

    c1, c2, c3, c4, c_ref = st.columns([1, 1, 1, 1, 0.6])
    c1.metric("Total Runs",            len(leads_runs))
    c2.metric("Total Leads Generated", fl_leads)
    c3.metric("Unique Locations",      fl_locs)
    c4.metric("Est. Cumulative Cost",  f"${fl_cost:.2f}")
    with c_ref:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        _refresh_button("refresh_leads")

    sc1, sc2 = st.columns(2)
    with sc1:
        st.link_button("Open Google Sheet", _LEADS_SHEET_URL,
                       icon=":material/table_chart:", use_container_width=True)
    with sc2:
        if st.button("Sync History", type="secondary", use_container_width=True,
                     key="sync_history_to_sheets_btn",
                     help="Backfill Supabase history to the lead-gen Google Sheet"):
            with st.spinner("Syncing legacy history..."):
                try:
                    from scratch.sync_sheets_backfill import run_backfill
                    res = run_backfill()
                    if "error" in res:
                        st.error(f"Sync failed: {res['error']}")
                    else:
                        st.success(
                            f"Synced! Updated {res['updated_runs']} runs, "
                            f"{res['updated_leads']} leads. Sheet updated."
                        )
                except Exception as e:
                    st.error(f"Sync failed: {e}")

    st.markdown("---")

    if not leads_runs:
        st.caption("No Find Leads runs yet.")
    for i, r in enumerate(leads_runs):
        ts       = r.get("timestamp", "")
        stopped  = r.get("stopped_early", False)
        ts_fmt   = _fmt_ts(ts)
        warn     = ":material/warning: " if stopped else ""
        run_id   = r.get("id")
        expanded = (_target_run_id is not None and run_id == _target_run_id)
        _pfc     = r.get("pattern_fallback_count")
        _ai_tag  = "  ·  pattern matching" if _pfc is None else ("  ·  pattern fallback" if _pfc else "")
        label    = f"{warn}{r.get('location', 'Unknown')} — {r.get('leads_found', 0)} leads · {ts_fmt}{_ai_tag}"

        with st.expander(label, expanded=expanded):
            _render_run_expander(
                r,
                key_prefix=f"leads_{i}",
                target_lead_place_id=(_target_lead_place_id if expanded else None),
            )

    _load_more_button("leads_load_more")

# ── Donut Scraper ──────────────────────────────────────────────────────────────────
with tab_donut:
    _section_banner(
        "Donut Scraper — Run History",
        "Area scraper runs, most recent first.",
        _C_DONUT, "rgba(207, 124, 63, 0.12)",
    )

    dn_clinics = sum(r.get("clinics_found", 0) for r in donut_runs)
    dn_areas   = len({r.get("location", "") for r in donut_runs})
    dn_cost    = sum(
        estimated_google_cost(0, r.get("search_calls", 0), 0)
        + estimated_gemini_cost(r.get("gemini_calls", 0))
        for r in donut_runs
    )

    c1, c2, c3, c4, c_ref = st.columns([1, 1, 1, 1, 0.6])
    c1.metric("Total Runs",          len(donut_runs))
    c2.metric("Total Clinics Found", dn_clinics)
    c3.metric("Unique Areas",        dn_areas)
    c4.metric("Est. Cumulative Cost", f"${dn_cost:.2f}")
    with c_ref:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        _refresh_button("refresh_donut")

    st.link_button("Open Google Sheet", _donut_sheet_url(),
                   icon=":material/table_chart:", use_container_width=False)

    st.markdown("---")

    if not donut_runs:
        st.caption("No Donut Scraper runs recorded yet — tracking starts from now.")
    for i, r in enumerate(donut_runs):
        ts_fmt  = _fmt_ts(r.get("timestamp", ""))
        gem_tag = "  ·  AI extraction" if r.get("gemini_calls", 0) else ""
        label   = f"{r.get('location', 'Unknown area')} — {r.get('clinics_found', 0)} clinics · {ts_fmt}{gem_tag}"
        with st.expander(label, expanded=False):
            _render_donut_run_expander(r, key_prefix=f"donut_{i}")

    _load_more_button("donut_load_more")

# ── Test Runs Log collapsible section ──────────────────────────────────────────
import os
if os.path.exists("/Users/yajatparmar"):
    with st.expander(":material/assignment: Test Runs Log (History)", expanded=False):
        if os.path.exists("test_runs_log.txt"):
            try:
                with open("test_runs_log.txt", "r") as f:
                    log_content = f.read()
                if log_content.strip():
                    st.code(log_content, language="markdown")
                    st.caption("Copy the block above to keep track of runs executed.")
                else:
                    st.info("Log is currently empty.")
            except Exception as e:
                st.error(f"Could not read test runs log: {e}")
        else:
            st.info("No test runs logged yet.")
