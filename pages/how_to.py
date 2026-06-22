import streamlit as st
from utils.theme import get_css

st.markdown(get_css(), unsafe_allow_html=True)

# ── Page header ─────────────────────────────────────────────────────────────────
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
    <div style='padding: 32px 0 8px;'>
        <h1 style='font-size:26px !important; font-weight:700 !important; letter-spacing:-0.03em !important;'>
            How to Use Kairos
        </h1>
        <p style='color:#6b6f76; font-size:14px; margin-top:6px;'>
            Your AI-powered dental practice lead intelligence platform
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.divider()

# ── Section 1: What is Kairos? ───────────────────────────────────────────────────
st.markdown("### 🎯 What is Kairos?")
st.info(
    "Kairos helps dental sales reps find **high-signal independent practices** that are struggling "
    "with admin and scheduling overhead — the ones most likely to benefit from your solution. "
    "It does this by analyzing **Google reviews**, **job postings**, **website features**, and "
    "**operating patterns** to surface practices actively experiencing operational pain."
)

st.divider()

# ── Section 2: Quick Start ───────────────────────────────────────────────────────
st.markdown("### 🚀 Quick Start")

st.markdown(
    """
    <div style='
        background:#f7f7f8; border:1px solid #ededed; border-radius:10px;
        padding:20px 24px; margin-bottom:16px;
    '>
        <div style='font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em;
                    color:#8a8f98; margin-bottom:12px;'>Step 1 — Enter a Location</div>
        <ul style='margin:0; padding-left:18px; color:#282a30; font-size:13px; line-height:2;'>
            <li>Type any <strong>city, state, or ZIP code</strong> in the search box</li>
            <li>Choose your <strong>search radius</strong> (10, 25, or 50 miles)</li>
            <li>Optionally filter by <strong>specialty</strong> or <strong>practice type</strong></li>
            <li>Click <strong>"Find Leads"</strong></li>
        </ul>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div style='
        background:#f7f7f8; border:1px solid #ededed; border-radius:10px;
        padding:20px 24px; margin-bottom:16px;
    '>
        <div style='font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em;
                    color:#8a8f98; margin-bottom:12px;'>Step 2 — The Pipeline Runs (5 stages)</div>
        <ol style='margin:0; padding-left:18px; color:#282a30; font-size:13px; line-height:2.1;'>
            <li><strong>Geocoding</strong> — converts your location to coordinates</li>
            <li><strong>Clinic Search</strong> — finds dental practices via Google Places</li>
            <li><strong>Job Matching</strong> — checks Adzuna for admin hiring signals</li>
            <li><strong>Enrichment</strong> — checks each clinic's website, hours, and reviews</li>
            <li><strong>Deep Review Scan</strong> — Outscraper deep-dives on borderline clinics</li>
        </ol>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div style='
        background:#f7f7f8; border:1px solid #ededed; border-radius:10px;
        padding:20px 24px; margin-bottom:16px;
    '>
        <div style='font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em;
                    color:#8a8f98; margin-bottom:14px;'>Step 3 — Read Your Results</div>
        <p style='margin:0 0 10px; font-size:13px; color:#282a30;'>
            <strong>Pain Score (0–9)</strong>: Higher = more operational pain
        </p>
    """,
    unsafe_allow_html=True,
)

_score_cols = st.columns(4)
with _score_cols[0]:
    st.markdown(
        "<div style='background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:12px 14px;text-align:center;'>"
        "<div style='font-size:18px;font-weight:700;color:#b91c1c;letter-spacing:-0.02em;'>6–9</div>"
        "<div style='font-size:11px;font-weight:600;color:#b91c1c;margin-top:3px;'>High Priority</div>"
        "<div style='font-size:11px;color:#6b6f76;margin-top:4px;'>Multiple strong signals</div>"
        "</div>",
        unsafe_allow_html=True,
    )
with _score_cols[1]:
    st.markdown(
        "<div style='background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;padding:12px 14px;text-align:center;'>"
        "<div style='font-size:18px;font-weight:700;color:#c2410c;letter-spacing:-0.02em;'>4–5</div>"
        "<div style='font-size:11px;font-weight:600;color:#c2410c;margin-top:3px;'>Strong Signal</div>"
        "<div style='font-size:11px;color:#6b6f76;margin-top:4px;'>Clear pain points</div>"
        "</div>",
        unsafe_allow_html=True,
    )
with _score_cols[2]:
    st.markdown(
        "<div style='background:#fefce8;border:1px solid #fde68a;border-radius:8px;padding:12px 14px;text-align:center;'>"
        "<div style='font-size:18px;font-weight:700;color:#854d0e;letter-spacing:-0.02em;'>2–3</div>"
        "<div style='font-size:11px;font-weight:600;color:#854d0e;margin-top:3px;'>Moderate</div>"
        "<div style='font-size:11px;color:#6b6f76;margin-top:4px;'>Worth watching</div>"
        "</div>",
        unsafe_allow_html=True,
    )
with _score_cols[3]:
    st.markdown(
        "<div style='background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:12px 14px;text-align:center;'>"
        "<div style='font-size:18px;font-weight:700;color:#166534;letter-spacing:-0.02em;'>0–1</div>"
        "<div style='font-size:11px;font-weight:600;color:#166534;margin-top:3px;'>Low Priority</div>"
        "<div style='font-size:11px;color:#6b6f76;margin-top:4px;'>Likely well-managed</div>"
        "</div>",
        unsafe_allow_html=True,
    )

st.markdown("<div style='margin-bottom:16px'></div>", unsafe_allow_html=True)

st.markdown(
    """
    <div style='
        background:#f7f7f8; border:1px solid #ededed; border-radius:10px;
        padding:20px 24px; margin-bottom:16px;
    '>
        <div style='font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em;
                    color:#8a8f98; margin-bottom:12px;'>Step 4 — Drill Into a Lead</div>
        <ul style='margin:0; padding-left:18px; color:#282a30; font-size:13px; line-height:2;'>
            <li>Click any lead to <strong>expand its full profile</strong></li>
            <li>See pain signals, evidence snippets, and <strong>outreach angle</strong></li>
            <li>Click individual signal tags (Front Desk, Phone, etc.) to see the
                <strong>specific reviews</strong> that triggered that signal, with highlights</li>
        </ul>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div style='
        background:#f7f7f8; border:1px solid #ededed; border-radius:10px;
        padding:20px 24px; margin-bottom:16px;
    '>
        <div style='font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em;
                    color:#8a8f98; margin-bottom:12px;'>Step 5 — Export Your Results</div>
        <ul style='margin:0; padding-left:18px; color:#282a30; font-size:13px; line-height:2;'>
            <li><strong>CSV export</strong>: quick download of all results</li>
            <li><strong>XLSX export</strong>: formatted spreadsheet with color-coded scores</li>
            <li><strong>Google Sheets</strong>: automatically synced after each run, organized by state/city</li>
        </ul>
    </div>
    """,
    unsafe_allow_html=True,
)

st.divider()

# ── Section 3: Pain Signal Glossary ─────────────────────────────────────────────
st.markdown("### 🔍 Pain Signal Glossary")
st.markdown(
    "<p style='color:#6b6f76; font-size:13px; margin-bottom:16px;'>"
    "These are the signals Kairos detects from reviews, job postings, and website data."
    "</p>",
    unsafe_allow_html=True,
)

_signals = [
    ("🖥", "Front Desk", "#ede9fe", "#6d28d9", "Complaints about receptionist attitude, disorganization, or rudeness"),
    ("📞", "Phone", "#dbeafe", "#1e40af", "Patients can't reach the office — calls go unanswered"),
    ("📅", "Scheduling", "#fce7f3", "#9d174d", "Appointment booking problems, long waits, or cancellations"),
    ("🧾", "Insurance", "#fff7ed", "#c2410c", "Billing errors, coverage confusion, or incorrect charges"),
    ("📄", "Paperwork", "#fefce8", "#854d0e", "Intake form issues, records management, or fax problems"),
    ("💼", "Hiring", "#dcfce7", "#15803d", "Active job posting for admin/front-desk roles (strong signal)"),
]

_sig_col1, _sig_col2 = st.columns(2)
for i, (icon, name, bg, color, desc) in enumerate(_signals):
    target_col = _sig_col1 if i % 2 == 0 else _sig_col2
    with target_col:
        st.markdown(
            f"<div style='background:{bg};border-radius:8px;padding:12px 14px;margin-bottom:10px;'>"
            f"<div style='font-size:15px;margin-bottom:4px;'>{icon} "
            f"<span style='font-weight:600;color:{color};font-size:13px;'>{name}</span></div>"
            f"<div style='font-size:12px;color:#374151;line-height:1.5;'>{desc}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

st.divider()

# ── Section 4: Practice Classification ──────────────────────────────────────────
st.markdown("### 🏥 Practice Classification")

_class_cols = st.columns(4)
_classifications = [
    ("Independent", "#ede9fe", "#6d28d9", "Single-location, owner-operated practice"),
    ("DSO", "#dbeafe", "#1e40af", "Dental Service Organization (corporate-owned network)"),
    ("Chain", "#fce7f3", "#9d174d", "Multi-location branded practice"),
    ("Unknown", "#f3f4f6", "#374151", "Could not determine from available data"),
]
for col, (label, bg, color, desc) in zip(_class_cols, _classifications):
    with col:
        st.markdown(
            f"<div style='background:{bg};border:1px solid {color}22;border-radius:8px;"
            f"padding:13px 14px;height:100%;'>"
            f"<div style='font-weight:700;color:{color};font-size:13px;margin-bottom:6px;'>{label}</div>"
            f"<div style='font-size:12px;color:#374151;line-height:1.5;'>{desc}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

st.divider()

# ── Section 5: History & Overlap Detection ───────────────────────────────────────
st.markdown("### 📂 History & Overlap Detection")

_hist_col1, _hist_col2 = st.columns(2)
with _hist_col1:
    st.success(
        "**All searches are saved to History automatically.**\n\n"
        "If you search an area you've already covered, Kairos will warn you. "
        "Clinics you've already seen are skipped to save API costs."
    )
with _hist_col2:
    st.info(
        "**Use History to re-export past searches** or add them to Google Sheets.\n\n"
        "History is stored locally and persists between sessions."
    )

st.divider()

# ── Section 6: Tips & Best Practices ────────────────────────────────────────────
st.markdown("### 💡 Tips & Best Practices")

_tips = [
    ("🗺", "Start with 25 mi radius for dense metro areas, 50 mi for rural or suburban areas."),
    ("🔥", "High Priority leads (score 6+) = reach out this week — they are actively hurting."),
    ("💼", "Check job board signals: a practice hiring front desk staff is actively feeling the pain."),
    ("⭐", "Look at review counts: 75+ reviews at 4★+ means high active patient volume — more ops load."),
    ("📊", "Export to XLSX for color-coded scores you can share with your team or manager."),
    ("🔄", "Re-run searches monthly — pain signals change as practices hire, fire, and grow."),
]

for icon, tip in _tips:
    st.markdown(
        f"<div style='display:flex;align-items:flex-start;gap:12px;padding:10px 0;"
        f"border-bottom:1px solid #ededed;'>"
        f"<span style='font-size:16px;flex:none;margin-top:1px;'>{icon}</span>"
        f"<span style='font-size:13px;color:#282a30;line-height:1.6;'>{tip}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:40px'></div>", unsafe_allow_html=True)

# ── Footer CTA ───────────────────────────────────────────────────────────────────
st.markdown(
    "<div style='text-align:center;padding:32px 0 16px;'>"
    "<div style='font-size:22px;font-weight:700;letter-spacing:-0.03em;color:#282a30;"
    "margin-bottom:8px;'>Ready to find your next deal?</div>"
    "<div style='font-size:13px;color:#6b6f76;'>Head to <strong>Find Leads</strong> and run your first search.</div>"
    "</div>",
    unsafe_allow_html=True,
)
