from __future__ import annotations

import re

_STRIP_WORDS = {
    "dental", "dentistry", "smile", "smiles", "family", "associates",
    "llc", "inc", "pllc", "dds", "dmd", "dr", "doctor", "office", "care",
    "center", "group", "practice", "clinic",
}


def normalize_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^\w\s]", " ", name)
    tokens = [t for t in name.split() if t not in _STRIP_WORDS]
    return " ".join(tokens).strip()


def miles_to_meters(miles: int) -> int:
    return int(miles * 1609.34)


def truncate(text: str, max_len: int = 200) -> str:
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def extract_city(formatted_address: str) -> str:
    if not formatted_address:
        return ""
    parts = [p.strip() for p in formatted_address.split(",")]
    if len(parts) >= 3:
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else ""


def get_hours_summary(opening_hours: dict | None) -> str:
    if not opening_hours:
        return "Hours not available"
    weekday_text = opening_hours.get("weekday_text")
    if weekday_text:
        return "; ".join(weekday_text)
    return "Hours not available"
