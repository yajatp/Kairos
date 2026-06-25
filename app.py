import base64
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from utils.theme import get_css

load_dotenv()

st.set_page_config(
    page_title="Kairos",
    page_icon="favicon.png",
    layout="wide",
    initial_sidebar_state="expanded",
)


_logo_bytes = Path("logo.png").read_bytes()
_logo_b64   = base64.b64encode(_logo_bytes).decode()

_how_to_page      = st.Page("views/how_to.py",       title="How to Use",   icon=":material/help:",        default=True)
_leads_page       = st.Page("views/leads.py",        title="Find Leads",   icon=":material/search:")
_donut_page       = st.Page("views/donut_scraper.py", title="Donut Scraper", icon=":material/map:")
_api_usage_page   = st.Page("views/api_usage.py",    title="API Usage",    icon=":material/bar_chart:")
_history_page     = st.Page("views/history.py",      title="History",      icon=":material/history:")

pg = st.navigation([_how_to_page, _leads_page, _donut_page, _api_usage_page, _history_page])

with st.sidebar:
    st.markdown(get_css(), unsafe_allow_html=True)
    st.markdown(
        f"<div class='workspace-header'>"
        f"<img src='data:image/png;base64,{_logo_b64}' class='workspace-logo' />"
        f"<div class='workspace-text'>"
        f"<div class='workspace-name'>Kairos</div>"
        f"<div class='workspace-tagline'>Automated lead generation</div>"
        f"</div>"
        f"</div>"
        f"<div class='sidebar-nav-divider'></div>",
        unsafe_allow_html=True,
    )
    st.page_link(_how_to_page,    label="How to Use",  icon=":material/help:")
    st.page_link(_leads_page,     label="Find Leads",  icon=":material/search:")
    st.page_link(_donut_page,     label="Donut Scraper", icon=":material/map:")
    st.page_link(_api_usage_page, label="API Usage",   icon=":material/bar_chart:")
    st.page_link(_history_page,   label="History",     icon=":material/history:")

pg.run()

# Inject JS after every page render to color lead expanders by pain score.
# MutationObserver keeps it live as Streamlit rerenders without needing a re-inject.
import streamlit.components.v1 as _components
_components.html("""
<script>
(function() {
    function paint() {
        try {
            var doc = window.parent.document;
            doc.querySelectorAll('[data-testid="stExpander"]').forEach(function(el) {
                var s = el.querySelector('summary');
                if (!s) return;
                var m = (s.textContent || '').match(/Score\\s+(\\d+(?:\\.\\d+)?)/);
                if (!m) return;
                var score = parseFloat(m[1]);
                var bg, bc;
                if      (score >= 6) { bg = 'rgba(239,68,68,0.09)';   bc = 'rgba(239,68,68,0.4)'; }
                else if (score >= 4) { bg = 'rgba(249,115,22,0.09)';  bc = 'rgba(249,115,22,0.4)'; }
                else if (score >= 2) { bg = 'rgba(234,179,8,0.09)';   bc = 'rgba(234,179,8,0.4)'; }
                else                 { bg = 'rgba(34,197,94,0.09)';   bc = 'rgba(34,197,94,0.4)'; }
                el.style.setProperty('background', bg, 'important');
                el.style.setProperty('border-color', bc, 'important');
            });
        } catch(e) {}
    }
    paint();
    try {
        var obs = new MutationObserver(function() { setTimeout(paint, 80); });
        obs.observe(window.parent.document.body, { childList: true, subtree: true });
    } catch(e) {}
})();
</script>
""", height=0)
