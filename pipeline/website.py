import logging
import requests

logger = logging.getLogger(__name__)

DIGITAL_TOOL_KEYWORDS = [
    "zocdoc", "solutionreach", "lighthouse360", "weave", "nexhealth", "localmed",
    "doctible", "dental intel", "eaglesoft", "dentrix", "carestack", "open dental",
    "online booking", "book online", "schedule online", "patient portal",
    "request appointment",
]

ONLINE_BOOKING_KEYWORDS = [
    "book now", "schedule now", "book appointment", "request appointment", "online booking",
]

HIRING_BANNER_KEYWORDS = [
    "we're hiring", "now hiring", "join our team", "careers", "we are hiring", "open positions",
]

_DEFAULTS = {
    "uses_digital_tools": False,
    "has_online_booking": False,
    "has_hiring_banner": False,
    "detected_tools": [],
}


def check_website(url: str) -> dict:
    if not url:
        return dict(_DEFAULTS)

    try:
        resp = requests.get(
            url,
            timeout=4,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
        )
        text = resp.text.lower()
    except Exception as e:
        logger.warning(f"Website check failed for {url}: {e}")
        return dict(_DEFAULTS)

    detected_tools = [kw for kw in DIGITAL_TOOL_KEYWORDS if kw in text]
    uses_digital_tools = len(detected_tools) > 0
    has_online_booking = any(kw in text for kw in ONLINE_BOOKING_KEYWORDS)
    has_hiring_banner = any(kw in text for kw in HIRING_BANNER_KEYWORDS)

    if has_online_booking and "online booking" not in detected_tools:
        detected_tools.append("online booking")

    return {
        "uses_digital_tools": uses_digital_tools,
        "has_online_booking": has_online_booking,
        "has_hiring_banner": has_hiring_banner,
        "detected_tools": detected_tools,
    }
