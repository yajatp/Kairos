import base64
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from utils.theme import get_css

load_dotenv()

st.set_page_config(
    page_title="Kairos",
    page_icon="logo.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(get_css(), unsafe_allow_html=True)

_logo_bytes = Path("logo.png").read_bytes()
_logo_b64   = base64.b64encode(_logo_bytes).decode()

_how_to_page    = st.Page("pages/how_to.py",    title="How to Use",  icon=":material/help:")
_leads_page     = st.Page("pages/leads.py",     title="Find Leads",  icon=":material/search:",    default=True)
_api_usage_page = st.Page("pages/api_usage.py", title="API Usage",   icon=":material/bar_chart:")
_history_page   = st.Page("pages/history.py",   title="History",     icon=":material/history:")

pg = st.navigation([_how_to_page, _leads_page, _api_usage_page, _history_page])

with st.sidebar:
    st.markdown(
        f"<div class='workspace-header'>"
        f"<img src='data:image/png;base64,{_logo_b64}' class='workspace-logo' />"
        f"<div class='workspace-text'>"
        f"<div class='workspace-name'>Kairos</div>"
        f"<div class='workspace-tagline'>Automated lead generation</div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.page_link(_how_to_page,    label="How to Use",  icon=":material/help:")
    st.page_link(_leads_page,     label="Find Leads",  icon=":material/search:")
    st.page_link(_api_usage_page, label="API Usage",   icon=":material/bar_chart:")
    st.page_link(_history_page,   label="History",     icon=":material/history:")
    st.divider()

pg.run()
