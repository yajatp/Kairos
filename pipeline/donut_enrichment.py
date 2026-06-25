from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from pipeline.classifier import classify_clinic
from pipeline.website import _EMAIL_NOISE

logger = logging.getLogger(__name__)

_CREDENTIAL_RE = re.compile(
    r'(?:Dr\.?\s+)?'
    r'([A-Z][a-zA-Z\'-]+(?:\s+[A-Z]\.?\s*)?[A-Z][a-zA-Z\'-]+)'
    r'\s*,?\s+'
    r'(D\.?D\.?S\.?|D\.?M\.?D\.?)',
)

_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_MAILTO_RE = re.compile(r'mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', re.IGNORECASE)

_TEAM_PAGE_KEYWORDS = ["about", "team", "doctor", "meet", "staff", "bio", "dr", "provider", "dentist"]

_MIN_VISIBLE_TEXT_LEN = 300


def _get_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "head"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def _score_url_for_team(url: str) -> int:
    path = urlparse(url).path.lower()
    return sum(1 for kw in _TEAM_PAGE_KEYWORDS if kw in path)


def _fetch_page(url: str) -> tuple[str, str]:
    """Returns (html, visible_text). Falls back to Playwright if text is too short."""
    try:
        resp = requests.get(
            url,
            timeout=4,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
        )
        html = resp.text
    except Exception as e:
        logger.debug("requests fetch failed for %s: %s", url, e)
        return "", ""

    text = _get_visible_text(html)
    # NOTE: Playwright fallback disabled to speed up Streamlit Cloud deploys.
    # Set _PLAYWRIGHT_ENABLED = True to re-enable headless browser scraping.
    _PLAYWRIGHT_ENABLED = False
    if _PLAYWRIGHT_ENABLED and len(text) < _MIN_VISIBLE_TEXT_LEN:
        pw_text = _fetch_with_playwright(url)
        if pw_text:
            return html, pw_text
    return html, text


_pw_browser_ready: bool = False


def _ensure_playwright_browser() -> bool:
    """Download Chromium binary on first use (no-op if already present)."""
    global _pw_browser_ready
    if _pw_browser_ready:
        return True
    try:
        import subprocess
        result = subprocess.run(
            ["playwright", "install", "chromium"],
            capture_output=True,
            timeout=180,
        )
        _pw_browser_ready = result.returncode == 0
        if not _pw_browser_ready:
            logger.warning("playwright install chromium exited %d", result.returncode)
        return _pw_browser_ready
    except Exception as e:
        logger.warning("Could not install Playwright Chromium: %s", e)
        return False


def _fetch_with_playwright(url: str) -> str:
    """Headless render fallback for JS-heavy sites. Silent no-op if Playwright not available."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ""

    if not _ensure_playwright_browser():
        return ""

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=20000, wait_until="networkidle")
            text = page.inner_text("body")
            browser.close()
            return " ".join(text.split())
    except Exception as e:
        logger.debug("Playwright failed for %s: %s", url, e)
        return ""


def _extract_internal_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_domain = urlparse(base_url).netloc
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        full = urljoin(base_url, href)
        if urlparse(full).netloc == base_domain:
            links.append(full)
    return list(dict.fromkeys(links))


def _scrape_clinic_pages(website_url: str) -> tuple[str, str]:
    """
    Returns (combined_text, email).
    Fetches homepage + top 2 team-page candidates.
    """
    homepage_html, homepage_text = _fetch_page(website_url)
    if not homepage_html:
        return "", ""

    raw_emails = _MAILTO_RE.findall(homepage_html) + _EMAIL_RE.findall(homepage_html.lower())
    email = ""
    for e in dict.fromkeys(raw_emails):
        if not any(noise in e.lower() for noise in _EMAIL_NOISE):
            email = e.lower()
            break

    links = _extract_internal_links(homepage_html, website_url)
    scored = sorted(
        [(url, _score_url_for_team(url)) for url in links if _score_url_for_team(url) > 0],
        key=lambda x: -x[1],
    )
    top_urls = [u for u, _ in scored[:2]]

    all_texts = [homepage_text]
    for url in top_urls:
        _, page_text = _fetch_page(url)
        if page_text:
            all_texts.append(page_text)

    return " ".join(all_texts), email


def _extract_dentist_regex(text: str) -> dict:
    matches = _CREDENTIAL_RE.findall(text)
    if not matches:
        return {"name": None, "credential": None}
    name, cred = matches[0]
    return {"name": name.strip(), "credential": cred.strip()}


def _call_gemini_structured(prompt: str, schema: dict, api_key: str, retries: int = 3) -> dict | list:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ImportError("google-genai not installed")

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
    )

    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=prompt,
                config=config,
            )
            return json.loads(response.text)
        except Exception as e:
            err = str(e)
            if "429" in err and attempt < retries - 1:
                m = re.search(r"retry in (\d+)", err)
                wait = int(m.group(1)) + 2 if m else 65
                time.sleep(wait)
            else:
                raise


_INDEPENDENT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "head_dentist": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING"},
                "credential": {"type": "STRING"},
                "role": {"type": "STRING"},
                "confidence": {"type": "STRING"},
            },
        },
        "email": {
            "type": "OBJECT",
            "properties": {
                "address": {"type": "STRING"},
                "confidence": {"type": "STRING"},
            },
        },
    },
}

_DSO_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "staff": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "role": {"type": "STRING"},
                    "is_location_specific": {"type": "BOOLEAN"},
                    "confidence": {"type": "STRING"},
                },
            },
        },
        "email": {
            "type": "OBJECT",
            "properties": {
                "address": {"type": "STRING"},
                "confidence": {"type": "STRING"},
            },
        },
    },
}

_ROLE_PRIORITY = {
    "owner": 0,
    "lead dentist": 1,
    "head dentist": 1,
    "office manager": 2,
    "practice manager": 2,
    "associate dentist": 3,
    "associate": 3,
    "dentist": 3,
}


def _role_rank(role: str) -> int:
    r = role.lower()
    for key, rank in _ROLE_PRIORITY.items():
        if key in r:
            return rank
    return 99


def _confidence_rank(confidence: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(confidence.lower(), 3)


def _extract_independent(clinic: dict, text: str, gemini_key: str) -> None:
    regex_result = _extract_dentist_regex(text)

    if regex_result["name"]:
        clinic["head_dentist"] = (
            f"{regex_result['name']}, {regex_result['credential']}"
            if regex_result["credential"]
            else regex_result["name"]
        )
        clinic["staff_source"] = "Regex"
        return

    if not gemini_key:
        clinic["head_dentist"] = ""
        clinic["staff_source"] = "Not Found"
        return

    prompt = (
        "You are analyzing dental practice website text to identify the head/owner dentist "
        "and contact email. Return null for any field you cannot find with confidence.\n\n"
        "Text (truncated to 4000 chars):\n"
        f"{text[:4000]}\n\n"
        "Return the head dentist (owner or primary dentist, not an associate), their credential, "
        "role (owner/associate/unclear), confidence (high/medium/low), and email if present."
    )

    try:
        result = _call_gemini_structured(prompt, _INDEPENDENT_SCHEMA, gemini_key)
        dentist = result.get("head_dentist", {})
        name = dentist.get("name") or ""
        cred = dentist.get("credential") or ""
        confidence = dentist.get("confidence", "low")

        if name:
            clinic["head_dentist"] = f"{name}, {cred}".rstrip(", ") if cred else name
            clinic["staff_source"] = f"Gemini ({confidence} confidence)"
        else:
            clinic["head_dentist"] = ""
            clinic["staff_source"] = "Not Found"

        if not clinic.get("email"):
            email_info = result.get("email", {})
            addr = email_info.get("address") or ""
            if addr and "@" in addr and not any(n in addr.lower() for n in _EMAIL_NOISE):
                clinic["email"] = addr.lower()
                clinic["email_source"] = f"Gemini ({email_info.get('confidence', 'low')} confidence)"
    except Exception as e:
        logger.warning("Gemini extraction failed for %s: %s", clinic.get("name"), e)
        clinic["head_dentist"] = ""
        clinic["staff_source"] = "Not Found"


def _extract_dso(clinic: dict, text: str, gemini_key: str) -> None:
    if not gemini_key:
        clinic["head_dentist"] = ""
        clinic["staff_source"] = "Not Found"
        return

    prompt = (
        "You are analyzing a DSO/chain dental location's website text. "
        "Extract every named staff member found — dentists, office manager, etc. "
        "Focus on people plausibly present at this physical location. "
        "Exclude regional/corporate titles (Regional VP, District Manager, etc.).\n\n"
        "Text (truncated to 4000 chars):\n"
        f"{text[:4000]}\n\n"
        "For each person: name, role, is_location_specific (true/false), confidence (high/medium/low). "
        "Also extract a contact email if present."
    )

    try:
        result = _call_gemini_structured(prompt, _DSO_SCHEMA, gemini_key)
        staff = result.get("staff", [])

        if not staff:
            clinic["head_dentist"] = ""
            clinic["staff_source"] = "Not Found"
            return

        # Filter to location-specific, sort by role seniority then confidence
        local_staff = [s for s in staff if s.get("is_location_specific", True)]
        if not local_staff:
            local_staff = staff

        local_staff.sort(
            key=lambda s: (
                _role_rank(s.get("role", "")),
                _confidence_rank(s.get("confidence", "low")),
            )
        )

        # Keep top entries: high-confidence first, cap at 4 unless all are strong
        surfaced = [s for s in local_staff if s.get("confidence") in ("high", "medium")][:4]
        if not surfaced:
            surfaced = local_staff[:2]

        parts = [
            f"{s['name']} ({s.get('role', 'Staff')})"
            for s in surfaced
            if s.get("name")
        ]
        clinic["head_dentist"] = "; ".join(parts)
        clinic["staff_source"] = "Gemini"

        if not clinic.get("email"):
            email_info = result.get("email", {})
            addr = email_info.get("address") or ""
            if addr and "@" in addr and not any(n in addr.lower() for n in _EMAIL_NOISE):
                clinic["email"] = addr.lower()
                clinic["email_source"] = f"Gemini ({email_info.get('confidence', 'low')} confidence)"
    except Exception as e:
        logger.warning("Gemini DSO extraction failed for %s: %s", clinic.get("name"), e)
        clinic["head_dentist"] = ""
        clinic["staff_source"] = "Not Found"


def enrich_clinic(clinic: dict, gemini_key: str = "") -> dict:
    """
    Add email, email_source, head_dentist, staff_source, notes, classification to clinic.
    Modifies the dict in-place and returns it.
    """
    name = clinic.get("name", "")
    clinic["classification"] = classify_clinic(name)
    is_dso = clinic["classification"] == "DSO"

    website = clinic.get("website", "")
    if not website:
        clinic.setdefault("email", "")
        clinic.setdefault("email_source", "Not Found")
        clinic.setdefault("head_dentist", "")
        clinic.setdefault("staff_source", "Not Found")
        clinic["notes"] = "No website found – manual lookup needed."
        return clinic

    all_text, email = _scrape_clinic_pages(website)

    clinic["email"] = email
    clinic["email_source"] = "Regex" if email else "Not Found"
    clinic["notes"] = ""

    if not all_text:
        clinic["head_dentist"] = ""
        clinic["staff_source"] = "Not Found"
        return clinic

    if not is_dso:
        _extract_independent(clinic, all_text, gemini_key)
    else:
        _extract_dso(clinic, all_text, gemini_key)

    return clinic
