def get_css() -> str:
    bg          = "#ffffff"
    bg_sidebar  = "#fafafa"
    bg_card     = "#ffffff"
    bg_hover    = "#f7f7f8"
    bg_group    = "#f7f7f8"
    bg_input    = "#ffffff"
    text        = "#282a30"
    text2       = "#6b6f76"
    text3       = "#8a8f98"
    border      = "#ededed"
    border2     = "#e6e6e6"
    shadow      = "0 1px 2px rgba(0,0,0,0.04)"
    accent      = "#3abdaf"

    return f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ── Base ─────────────────────────────────────── */
html, body, .stApp {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    -webkit-font-smoothing: antialiased !important;
}}
.stApp {{ background: {bg} !important; color: {text} !important; }}
[data-testid="stAppViewContainer"] {{ background: {bg} !important; }}
[data-testid="stMainBlockContainer"] {{
    background: {bg} !important;
    padding: 0 2.5rem 3rem !important;
    max-width: 1360px !important;
}}

/* ── Sidebar ──────────────────────────────────── */
[data-testid="stSidebar"] {{
    background: {bg_sidebar} !important;
    border-right: 1px solid {border} !important;
}}
[data-testid="stSidebar"] > div:first-child {{
    padding-top: 0 !important;
    display: flex !important;
    flex-direction: column !important;
}}
[data-testid="stSidebar"] * {{ color: {text} !important; }}

/* ── Button white text fix (must come after wildcard) ── */
[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
    color: #ffffff !important;
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"] *,
[data-testid="stSidebar"] .stButton > button[kind="primary"] p,
[data-testid="stSidebar"] .stButton > button[kind="primary"] span,
[data-testid="stSidebar"] .stButton > button[kind="primary"] div {{
    color: #ffffff !important;
}}

/* ── Hide default nav (replaced by st.page_link in sidebar) ── */
[data-testid="stSidebarNav"],
[data-testid="stSidebarNav"] *,
[data-testid="stSidebarNavItems"],
[data-testid="stSidebarNavSeparator"],
[data-testid="stSidebarNavLink"] {{
    display: none !important;
    border: none !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
}}

/* ── Page link nav items ──────────────────────── */
[data-testid="stSidebar"] [data-testid="stPageLink"] {{
    padding: 0 !important;
    margin: 0 !important;
    border: none !important;
    outline: none !important;
}}
[data-testid="stSidebar"] [data-testid="stPageLink"]:first-child {{
    margin-top: 6px !important;
}}
[data-testid="stSidebar"] [data-testid="stPageLink"] > div,
[data-testid="stSidebar"] [data-testid="stPageLink"] > div > div {{
    margin: 0 !important; padding: 0 !important; min-height: 0 !important;
    border: none !important; outline: none !important;
}}
[data-testid="stSidebar"] [data-testid="stPageLink"] a {{
    border-radius: 6px !important;
    padding: 5px 8px !important;
    font-size: 13px !important;
    font-weight: 400 !important;
    color: {text2} !important;
    text-decoration: none !important;
    transition: background 0.08s ease !important;
    display: flex !important; align-items: center !important;
    gap: 8px !important; height: 30px !important;
    margin: 0 !important;
}}
[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {{
    background: {bg_hover} !important; color: {text} !important;
}}
[data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"] {{
    background: {bg_hover} !important;
    color: {text} !important; font-weight: 500 !important;
}}

/* ── Sidebar dividers ── */
[data-testid="stSidebar"] hr {{
    border: none !important;
    border-top: 1px solid {border} !important;
    margin: 0 !important;
}}


/* ── Workspace header ─────────────────────────── */
.workspace-header {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 16px 13px;
    border-bottom: 1px solid {border};
}}
.workspace-logo {{
    width: 26px; height: 26px;
    object-fit: contain;
    flex: none;
    border-radius: 4px;
}}
.workspace-text {{
    display: flex;
    flex-direction: column;
    gap: 3px;
}}
.workspace-name {{
    font-size: 15px; font-weight: 700;
    color: {text}; letter-spacing: -0.03em;
    font-family: 'Inter', sans-serif;
    line-height: 1;
}}
.workspace-tagline {{
    font-size: 10px; font-weight: 400;
    color: {text3}; letter-spacing: 0.01em;
    line-height: 1;
    font-family: 'Inter', sans-serif;
}}


/* ── Sidebar section labels ───────────────────── */
[data-testid="stSidebar"] .stMarkdown p {{
    color: {text3} !important;
    font-size: 10.5px !important;
    font-weight: 600 !important;
    letter-spacing: 0.07em !important;
    text-transform: uppercase !important;
    margin: 14px 0 3px !important;
}}

/* ── Buttons ──────────────────────────────────── */
.stButton > button {{
    font-family: 'Inter', sans-serif !important;
    font-weight: 500 !important; font-size: 13px !important;
    border-radius: 7px !important; padding: 6px 13px !important;
    border: 1px solid {border2} !important;
    background: {bg_card} !important; color: {text} !important;
    transition: all 0.08s ease !important;
    letter-spacing: -0.01em !important;
    box-shadow: {shadow} !important;
    min-height: 34px !important;
}}
.stButton > button:hover {{
    background: {bg_hover} !important; box-shadow: none !important;
}}
.stButton > button[kind="primary"] {{
    background: {text} !important;
    color: #ffffff !important;
    border-color: {text} !important;
    font-weight: 600 !important; box-shadow: none !important;
}}
.stButton > button[kind="primary"]:hover {{ opacity: 0.84 !important; }}
.stButton > button[kind="secondary"] {{
    background: {bg_card} !important;
    color: {text2} !important; border-color: {border} !important;
    box-shadow: none !important;
}}

/* ── Text input ───────────────────────────────── */
.stTextInput > div > div > input {{
    background: {bg_input} !important; border: 1px solid {border} !important;
    border-radius: 7px !important; color: {text} !important;
    font-family: 'Inter', sans-serif !important; font-size: 13px !important;
    padding: 7px 11px !important; box-shadow: none !important;
    transition: border-color 0.12s, box-shadow 0.12s !important;
}}
.stTextInput > div > div > input:focus {{
    border-color: {accent} !important;
    box-shadow: 0 0 0 2px {accent}22 !important; outline: none !important;
}}
.stTextInput > div > div > input::placeholder {{ color: {text3} !important; }}

/* ── Sliders ──────────────────────────────────── */
.stSlider [data-baseweb="slider"] [role="slider"] {{
    background: {accent} !important; border-color: {accent} !important;
}}
div[data-testid="stSelectSlider"] [role="slider"] {{
    background: {accent} !important; border-color: {accent} !important;
}}

/* ── Multiselect ──────────────────────────────── */
.stMultiSelect [data-baseweb="select"] > div:first-child {{
    background: {bg_input} !important; border: 1px solid {border} !important;
    border-radius: 7px !important; font-size: 13px !important;
    min-height: auto !important;
}}
.stMultiSelect [data-baseweb="tag"] {{
    background: {bg_hover} !important; border: 1px solid {border2} !important;
    border-radius: 4px !important; color: {text} !important; font-size: 11.5px !important;
}}

/* ── Pills ────────────────────────────────────── */
[data-testid="stPillsInput"] {{
    gap: 5px !important;
    flex-wrap: wrap !important;
}}
[data-testid="stPillsInput"] button {{
    font-family: 'Inter', sans-serif !important;
    font-size: 11.5px !important; font-weight: 400 !important;
    border-radius: 5px !important;
    padding: 3px 9px !important;
    border: 1px solid {border2} !important;
    background: {bg_card} !important;
    color: {text2} !important;
    transition: all 0.08s ease !important;
    box-shadow: none !important;
    min-height: 26px !important;
}}
[data-testid="stPillsInput"] button[aria-pressed="true"] {{
    background: {text} !important;
    color: #ffffff !important;
    border-color: {text} !important;
    font-weight: 500 !important;
}}
[data-testid="stPillsInput"] button:hover {{
    background: {bg_hover} !important;
    border-color: {border2} !important;
}}

/* ── Selectbox ────────────────────────────────── */
.stSelectbox [data-baseweb="select"] > div {{
    background: {bg_input} !important; border: 1px solid {border} !important;
    border-radius: 7px !important; color: {text} !important; font-size: 13px !important;
}}

/* ── Segmented control ────────────────────────── */
[data-testid="stSegmentedControl"] {{
    background: {bg_hover} !important;
    border: 1px solid {border} !important;
    border-radius: 8px !important;
    padding: 3px !important;
    gap: 2px !important;
}}
[data-testid="stSegmentedControl"] button {{
    font-family: 'Inter', sans-serif !important;
    font-size: 12.5px !important; font-weight: 400 !important;
    border-radius: 6px !important; padding: 4px 12px !important;
    color: {text2} !important;
    border: 1px solid transparent !important;
    background: transparent !important;
    transition: all 0.08s ease !important;
}}
[data-testid="stSegmentedControl"] button[aria-checked="true"] {{
    background: {bg_card} !important;
    color: {text} !important; font-weight: 500 !important;
    box-shadow: {shadow} !important;
    border-color: {border2} !important;
}}

/* ── Metrics ──────────────────────────────────── */
[data-testid="stMetric"] {{
    background: {bg_card} !important; border: 1px solid {border} !important;
    border-radius: 8px !important; padding: 13px 15px !important;
    box-shadow: {shadow} !important;
}}
[data-testid="stMetricLabel"] > div {{
    color: {text2} !important; font-size: 10.5px !important;
    font-weight: 600 !important; text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
}}
[data-testid="stMetricValue"] > div,
[data-testid="stMetricValue"] p {{
    font-family: 'Inter', sans-serif !important;
    color: {text} !important; font-size: 20px !important;
    font-weight: 700 !important; letter-spacing: -0.03em !important;
}}

/* ── Progress ─────────────────────────────────── */
.stProgress > div > div > div {{
    background: {bg_hover} !important; border-radius: 4px !important; height: 5px !important;
}}
.stProgress > div > div > div > div {{
    background: {accent} !important; border-radius: 4px !important;
}}

/* ── Tabs ─────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
    background: transparent !important; border-bottom: 1px solid {border} !important;
    gap: 0 !important; padding: 0 !important;
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent !important; color: {text2} !important;
    font-size: 13px !important; font-weight: 400 !important;
    padding: 7px 16px !important; border-bottom: 2px solid transparent !important;
    margin-bottom: -1px !important; transition: all 0.1s !important;
}}
.stTabs [data-baseweb="tab"]:hover {{ color: {text} !important; }}
.stTabs [data-baseweb="tab"][aria-selected="true"] {{
    color: {text} !important; border-bottom: 2px solid {text} !important;
    font-weight: 500 !important;
}}
.stTabs [data-baseweb="tab-panel"] {{ background: transparent !important; padding: 1.25rem 0 0 !important; }}

/* ── Expanders as issue rows ──────────────────── */
[data-testid="stExpander"] {{
    border: none !important;
    border-bottom: 1px solid {border} !important;
    border-radius: 0 !important;
    background: {bg_card} !important;
    box-shadow: none !important;
    margin: 0 !important;
}}
[data-testid="stExpander"] summary {{
    background: {bg_card} !important; color: {text} !important;
    font-weight: 400 !important; font-size: 13px !important;
    padding: 9px 14px !important; border-radius: 0 !important;
    transition: background 0.08s ease !important;
    min-height: 40px !important;
    display: flex !important; align-items: center !important;
    letter-spacing: -0.01em !important;
}}
[data-testid="stExpander"] summary:hover {{ background: {bg_hover} !important; }}
[data-testid="stExpander"] > div > div {{
    background: {bg_card} !important;
    border-top: 1px solid {border} !important;
    padding: 16px !important;
}}

/* ── Lead group headers ───────────────────────── */
.lead-group-header {{
    display: flex; align-items: center; gap: 8px;
    padding: 7px 14px;
    background: {bg_group};
    border-top: 1px solid {border};
    border-bottom: 1px solid {border};
    margin-top: 10px;
}}
.lgd {{ width: 8px; height: 8px; border-radius: 50%; flex: none; display: inline-block; }}
.lgn {{ font-size: 12.5px; font-weight: 600; color: {text}; letter-spacing: -0.01em; }}
.lgc {{ font-size: 12px; color: {text3}; }}

/* ── Stat blocks ──────────────────────────────── */
.stat-blocks {{ display: flex; gap: 10px; flex-wrap: wrap; }}
.stat-block {{
    background: {bg_card}; border: 1px solid {border};
    border-radius: 8px; padding: 13px 15px;
    box-shadow: {shadow}; flex: 1; min-width: 110px;
}}
.stat-block .sl {{
    font-size: 10.5px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.07em; color: {text2}; margin-bottom: 5px;
}}
.stat-block .sv {{
    font-size: 21px; font-weight: 700; color: {text};
    letter-spacing: -0.03em; line-height: 1;
}}
.stat-block .ss {{ font-size: 11px; color: {text3}; margin-top: 3px; }}

/* ── Page breadcrumb header ───────────────────── */
.page-header-linear {{
    height: 46px; display: flex; align-items: center; gap: 8px;
    border-bottom: 1px solid {border};
    margin: 0 -2.5rem; padding: 0 2.5rem;
    margin-bottom: 20px;
}}
.bc-parent {{ font-size: 13px; color: {text2}; }}
.bc-sep {{ font-size: 12px; color: {text3}; margin: 0 1px; }}
.bc-current {{ font-size: 13px; font-weight: 500; color: {text}; }}

/* ── Headings ─────────────────────────────────── */
h1 {{
    color: {text} !important; font-size: 18px !important;
    font-weight: 600 !important; letter-spacing: -0.02em !important;
    line-height: 1.3 !important; margin: 0 !important;
}}
h2 {{ color: {text} !important; font-size: 15px !important; font-weight: 600 !important; letter-spacing: -0.02em !important; }}
h3 {{ color: {text} !important; font-size: 13.5px !important; font-weight: 600 !important; letter-spacing: -0.01em !important; margin: 0 !important; }}

/* ── Divider ──────────────────────────────────── */
hr {{ border: none !important; border-top: 1px solid {border} !important; margin: 14px 0 !important; }}

/* ── Dataframe ────────────────────────────────── */
.stDataFrame {{
    border: 1px solid {border} !important; border-radius: 8px !important;
    overflow: hidden !important; box-shadow: {shadow} !important;
}}

/* ── Alerts ───────────────────────────────────── */
.stAlert {{ border-radius: 7px !important; font-size: 13px !important; }}
[data-testid="stNotification"] {{ border-radius: 7px !important; font-size: 13px !important; }}

/* ── Caption ──────────────────────────────────── */
[data-testid="stCaptionContainer"] p {{ color: {text2} !important; font-size: 12px !important; }}

/* ── Markdown ─────────────────────────────────── */
.stMarkdown p, .stMarkdown li, [data-testid="stMarkdownContainer"] p {{
    color: {text} !important; font-size: 13px !important; line-height: 1.6 !important;
}}
.stMarkdown strong {{ color: {text} !important; font-weight: 600 !important; }}

/* ── Hide Streamlit chrome ────────────────────── */
#MainMenu {{ visibility: hidden !important; }}
footer {{ visibility: hidden !important; }}
[data-testid="stDecoration"] {{ display: none !important; }}
[data-testid="stStatusWidget"] {{ display: none !important; }}
[data-testid="manage-app-button"] {{ display: none !important; }}

/* ── Scrollbar ────────────────────────────────── */
::-webkit-scrollbar {{ width: 5px; height: 5px; }}
::-webkit-scrollbar-track {{ background: {bg_sidebar}; }}
::-webkit-scrollbar-thumb {{ background: {border2}; border-radius: 3px; }}

/* ── Pain score badge ─────────────────────────── */
.ps-badge {{
    display: inline-flex; align-items: center; gap: 5px;
    padding: 2px 9px; border-radius: 4px;
    font-size: 12px; font-weight: 600;
}}

/* ── Pain guide sidebar ───────────────────────── */
.pain-guide {{ font-size: 12px; line-height: 2.1; padding-bottom: 12px; }}
.pain-guide-title {{
    font-size: 10.5px; font-weight: 600; letter-spacing: 0.07em;
    text-transform: uppercase; color: {text3}; margin-bottom: 8px;
}}
.pain-pill {{
    display: inline-block; padding: 1px 7px; border-radius: 4px;
    font-size: 11px; font-weight: 600; white-space: nowrap; margin-right: 6px;
}}

/* ── Empty state ──────────────────────────────── */
.empty-state {{ text-align: center; padding: 5rem 2rem; }}
.empty-state-icon {{ font-size: 34px; margin-bottom: 14px; opacity: 0.4; display: block; }}
.empty-state-title {{
    font-size: 17px; font-weight: 600; color: {text};
    letter-spacing: -0.02em; margin-bottom: 8px;
}}
.empty-state-body {{
    font-size: 13px; color: {text2};
    max-width: 380px; margin: 0 auto; line-height: 1.75;
}}
.how-it-works {{ margin: 24px auto 0; max-width: 340px; text-align: left; }}
.hw-title {{
    font-size: 10.5px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.07em; color: {text3}; margin-bottom: 12px;
}}
.hw-step {{
    display: flex; align-items: flex-start; gap: 10px;
    margin-bottom: 8px; font-size: 13px; color: {text2}; line-height: 1.5;
}}
.hw-num {{
    width: 17px; height: 17px; border-radius: 50%;
    border: 1px solid {border2}; display: flex; align-items: center;
    justify-content: center; font-size: 10px; font-weight: 600;
    color: {text3}; flex: none; margin-top: 1px;
}}
</style>"""
