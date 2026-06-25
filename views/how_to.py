import streamlit as st
from utils.theme import get_css

st.markdown(get_css(), unsafe_allow_html=True)

st.markdown(
    "<div class='page-header-linear'>"
    "<span class='bc-parent'>Kairos</span>"
    "<span class='bc-sep'>›</span>"
    "<span class='bc-current'>How to Use</span>"
    "</div>",
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div style='padding: 24px 0 4px;'>
        <h1 style='font-size:24px !important; font-weight:700 !important; letter-spacing:-0.03em !important;'>
            Internal Reference
        </h1>
        <p style='color:#6b6f76; font-size:14px; margin-top:4px;'>
            Quick reference for running searches, reading signals, and exporting leads.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.divider()

# ── Pipeline stages ───────────────────────────────────────────────────────────────
st.markdown("### Pipeline")
st.markdown(
    """
    <div style='background:#f7f7f8;border:1px solid #ededed;border-radius:10px;padding:18px 22px;margin-bottom:16px'>
      <ol style='margin:0;padding-left:18px;color:#282a30;font-size:13px;line-height:2.2'>
        <li><strong>Geocode</strong> — resolves location to lat/lng (1 API call)</li>
        <li><strong>Clinic search</strong> — Google Places text search within radius (1 call per 20 results)</li>
        <li><strong>Adzuna jobs</strong> — checks for active front-desk hiring (1 call, national)</li>
        <li><strong>Place details + website</strong> — fetches hours, reviews, website for each clinic (1 call/clinic)</li>
        <li><strong>Outscraper deep scan</strong> — 10 lowest-rated reviews per borderline clinic (1 call/clinic, capped at 15/run)</li>
      </ol>
      <div style='margin-top:12px;font-size:12px;color:#6b6f76;border-top:1px solid #ededed;padding-top:10px'>
        Clinics already in Supabase are skipped — saves API calls and prevents duplicate leads.
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.divider()

# ── Pain score ────────────────────────────────────────────────────────────────────
st.markdown("### Pain Score (0–9)")

_score_cols = st.columns(4)
_scores = [
    ("6–9", "High Priority",   "#fef2f2", "#fecaca", "#b91c1c", "Multiple signals — reach out this week"),
    ("4–5", "Strong Signal",   "#fff7ed", "#fed7aa", "#c2410c", "Clear ops pain, worth a call"),
    ("2–3", "Moderate",        "#fefce8", "#fde68a", "#854d0e", "Some friction, lower urgency"),
    ("0–1", "Low Priority",    "#f0fdf4", "#bbf7d0", "#166534", "Likely well-run, skip for now"),
]
for col, (score, label, bg, border, color, desc) in zip(_score_cols, _scores):
    with col:
        st.markdown(
            f"<div style='background:{bg};border:1px solid {border};border-radius:8px;"
            f"padding:12px 14px;height:100%;'>"
            f"<div style='font-size:20px;font-weight:700;color:{color};letter-spacing:-0.02em'>{score}</div>"
            f"<div style='font-size:11px;font-weight:700;color:{color};margin:3px 0 6px'>{label}</div>"
            f"<div style='font-size:11px;color:#6b6f76;line-height:1.5'>{desc}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
st.divider()

# ── Pain signals ──────────────────────────────────────────────────────────────────
st.markdown("### Pain Signals")
st.markdown(
    "<p style='color:#6b6f76;font-size:13px;margin-bottom:14px'>"
    "Detected from Google reviews (rating ≤ 3), job postings, and website scan."
    "</p>",
    unsafe_allow_html=True,
)

_signals = [
    ("Front Desk",   "#ede9fe", "#6d28d9", "Receptionist attitude, disorganization, rudeness"),
    ("Phone",        "#dbeafe", "#1e40af", "Unanswered calls, voicemail black holes, hold issues"),
    ("Scheduling",   "#fce7f3", "#9d174d", "Long waits, cancellations, overbooking"),
    ("Insurance",    "#fff7ed", "#c2410c", "Billing errors, coverage confusion, overcharges"),
    ("Paperwork",    "#fefce8", "#854d0e", "Intake forms, records, fax dependencies"),
    ("Hiring",       "#dcfce7", "#15803d", "Active job listing for admin/front-desk role (strong buy signal)"),
]

_sig_c1, _sig_c2 = st.columns(2)
for i, (name, bg, color, desc) in enumerate(_signals):
    with (_sig_c1 if i % 2 == 0 else _sig_c2):
        st.markdown(
            f"<div style='background:{bg};border-radius:8px;padding:11px 14px;margin-bottom:8px'>"
            f"<span style='font-weight:700;color:{color};font-size:13px'>{name}</span>"
            f"<div style='font-size:12px;color:#374151;margin-top:3px;line-height:1.5'>{desc}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

st.divider()

# ── Export options ────────────────────────────────────────────────────────────────
st.markdown("### Export Options")
st.markdown(
    """
    <div style='background:#f7f7f8;border:1px solid #ededed;border-radius:10px;padding:18px 22px;'>
      <div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:13px;color:#282a30'>
        <div><strong>CSV (full)</strong> — all columns, raw data</div>
        <div><strong>XLSX (formatted)</strong> — color-coded pain scores, frozen header</div>
        <div><strong>Phones &amp; Emails</strong> — name, phone, email, address only</div>
        <div><strong>Outreach List</strong> — name, signals, score, angle, phone, email</div>
      </div>
      <div style='margin-top:12px;font-size:12px;color:#6b6f76;border-top:1px solid #ededed;padding-top:10px'>
        Google Sheets auto-syncs after every run, organized by state tab. Use <strong>Sync History</strong>
        in the History page to backfill any runs that missed the auto-sync.
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.divider()

# ── Practice classification ───────────────────────────────────────────────────────
st.markdown("### Practice Classification")
_class_cols = st.columns(4)
_classifications = [
    ("Independent", "#ede9fe", "#6d28d9", "Single-location, owner-operated"),
    ("DSO",         "#dbeafe", "#1e40af", "Dental Service Organization — corporate network"),
    ("Chain",       "#fce7f3", "#9d174d", "Multi-location branded practice"),
    ("Unknown",     "#f3f4f6", "#374151", "Couldn't classify from available data"),
]
for col, (label, bg, color, desc) in zip(_class_cols, _classifications):
    with col:
        st.markdown(
            f"<div style='background:{bg};border:1px solid {color}22;border-radius:8px;"
            f"padding:12px 14px;height:100%;'>"
            f"<div style='font-weight:700;color:{color};font-size:13px;margin-bottom:5px'>{label}</div>"
            f"<div style='font-size:12px;color:#374151;line-height:1.5'>{desc}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
st.divider()

# ── Notes for local dev ───────────────────────────────────────────────────────────
st.markdown("### Local Dev Notes")
st.markdown(
    """
    <div style='background:#f7f7f8;border:1px solid #ededed;border-radius:10px;padding:18px 22px;font-size:13px;color:#282a30;line-height:2'>
      <div>All runs are saved to <strong>Supabase</strong> regardless of environment.</div>
      <div>Sheets auto-sync runs at the end of every pipeline — use <strong>Sync History</strong> to backfill if it fails.</div>
      <div>Review analysis mode: <strong>Pattern (fast)</strong> is the default. Switch to <strong>AI (accurate)</strong> once a GEMINI_API_KEY is configured.</div>
      <div>Local-only guard: <code style='background:#ededed;padding:1px 5px;border-radius:3px'>os.path.exists("/Users/yajatparmar")</code> gates the test run log.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown("<div style='height:40px'></div>", unsafe_allow_html=True)
