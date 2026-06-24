"""Google Sheets integration for Kairos lead export."""

from __future__ import annotations

import json
import logging
import os
import re

import pandas as pd

logger = logging.getLogger(__name__)

SPREADSHEET_ID = "1UlBdK2z7UsP-_IFYhxK5IImmHCOGFKKvaGHUDw_dXHs"

_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "Washington D.C.",
}
_STATE_ABBRS = set(_STATE_NAMES.keys())


def _parse_tab_name(location: str) -> str:
    """Convert a location string to a state tab name like 'Texas'."""
    if not location or not location.strip():
        return "Other"
    loc = location.strip()
    parts = [p.strip() for p in loc.split(",")]
    if len(parts) >= 2:
        tail = parts[-1].split()[0].upper()
        if tail in _STATE_ABBRS:
            return _STATE_NAMES[tail]
    words = loc.split()
    if len(words) >= 2 and words[-1].upper() in _STATE_ABBRS:
        state = words[-1].upper()
        return _STATE_NAMES[state]
    # Check if any state name or abbreviation is directly in the string
    loc_upper = loc.upper()
    for abbr, full_name in _STATE_NAMES.items():
        if f" {abbr}" in loc_upper or f",{abbr}" in loc_upper or full_name.upper() in loc_upper:
            return full_name
    return "Other"


def _load_service_account_info() -> dict | None:
    """Load service account JSON from env var or Streamlit secret."""
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        try:
            import streamlit as st
            raw = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        except Exception:
            pass
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Could not parse GOOGLE_SERVICE_ACCOUNT_JSON: {e}")
        return None


def get_sheets_client():
    """Return an authenticated gspread client, or None if not configured."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        logger.warning("gspread or google-auth not installed")
        return None

    info = _load_service_account_info()
    if not info:
        return None

    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        logger.warning(f"get_sheets_client failed: {e}")
        return None


def _get_or_create_worksheet(spreadsheet, tab_name: str, headers: list[str]):
    """Return the worksheet with ``tab_name``, creating it with headers if needed."""
    try:
        ws = spreadsheet.worksheet(tab_name)
        return ws
    except Exception:
        pass
    # Create new sheet
    ws = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=len(headers) + 2)
    ws.append_row(headers, value_input_option="RAW")
    return ws


def append_leads_to_sheet(
    df: pd.DataFrame,
    location: str,
    run_date: str,
) -> dict:
    """Append leads to the Google Sheet, merging and sorting rows by city/radius/score.

    Returns a dict: ``{"added": N, "skipped": M, "tab": tab_name}``.
    """
    client = get_sheets_client()
    if client is None:
        return {"added": 0, "skipped": 0, "tab": "", "error": "Sheets not configured"}

    tab_name = _parse_tab_name(location)

    try:
        spreadsheet = client.open_by_key(SPREADSHEET_ID)

        # Standard headers
        headers = [
            "City", "Search Radius", "Run Date", "Place ID", "Clinic Name", "Classification", "Specialty",
            "Address", "Website", "Phone Number", "Best Contact Found", "Contact Role", "Contact Email",
            "LinkedIn", "Number of Locations", "Pain Signal Type", "Evidence / Source", "Pain Score",
            "Outreach Angle", "Notes", "Google Rating", "Total Reviews", "Hours Summary", "Extended Hours",
            "Online Booking", "Review Data Depth", "Review Method", "Run Errors", "reviews_json"
        ]

        ws = _get_or_create_worksheet(spreadsheet, tab_name, headers)

        # Retrieve existing rows
        existing_values = ws.get_all_values()
        existing_rows = []
        old_headers = []
        if len(existing_values) > 0:
            old_headers = [h.strip() for h in existing_values[0]]
            if len(existing_values) > 1:
                existing_rows = existing_values[1:]

        # Auto-migrate columns if the old header format is found
        if old_headers and old_headers != headers:
            migrated_rows = []
            for row in existing_rows:
                row_dict = {}
                for idx, h in enumerate(old_headers):
                    if idx < len(row):
                        row_dict[h] = row[idx]
                
                new_row = []
                for h in headers:
                    new_row.append(row_dict.get(h, ""))
                migrated_rows.append(new_row)
            existing_rows = migrated_rows

        # Create a dictionary of existing rows indexed by Place ID (index 3)
        merged_data: dict[str, list] = {}
        for row in existing_rows:
            if len(row) > 3 and row[3]:
                pid = str(row[3]).strip()
                merged_data[pid] = row

        skipped = 0
        added = 0

        # Loop through df and add/overwrite in merged_data
        for _, row in df.iterrows():
            pid = str(row.get("Place ID", row.get("place_id", ""))).strip()
            if not pid:
                continue

            run_date_val = row.get("Run Date", row.get("run_date", run_date))

            # Compile new row values matching standard headers
            new_row_values = [
                row.get("City", row.get("city", location)),
                row.get("Search Radius", row.get("search_radius", "")),
                run_date_val,
                pid,
                row.get("Clinic Name", row.get("name", "")),
                row.get("Classification", row.get("classification", "")),
                row.get("Specialty", row.get("specialty", "")),
                row.get("Address", row.get("address", "")),
                row.get("Website", row.get("website", "")),
                row.get("Phone Number", row.get("phone", "")),
                row.get("Best Contact Found", "Office Manager"),
                row.get("Contact Role", "Office Manager"),
                row.get("Contact Email", ""),
                row.get("LinkedIn", ""),
                row.get("Number of Locations", 1),
                row.get("Pain Signal Type", row.get("signals", "")),
                row.get("Evidence / Source", ""),
                row.get("Pain Score", row.get("pain_score", 0)),
                row.get("Outreach Angle", row.get("outreach_angle", "")),
                row.get("Notes", ""),
                row.get("Google Rating", row.get("rating", "")),
                row.get("Total Reviews", row.get("total_reviews", 0)),
                row.get("Hours Summary", ""),
                row.get("Extended Hours", "Yes" if row.get("Extended Hours") == "Yes" or row.get("extended_hours") is True else "No"),
                row.get("Online Booking", "Yes" if row.get("Online Booking") == "Yes" or row.get("online_booking") is True else "No"),
                row.get("Review Data Depth", row.get("review_depth", "")),
                row.get("Review Method", row.get("review_method", "")),
                row.get("Run Errors", row.get("run_errors", "")),
                row.get("reviews_json", ""),
            ]

            if pid in merged_data:
                skipped += 1
            else:
                merged_data[pid] = new_row_values
                added += 1

        # Now sort the entire list of rows by City (index 0), then Search Radius (index 1), then Pain Score (index 17) descending.
        all_rows = list(merged_data.values())

        def parse_radius(val) -> int:
            try:
                digits = re.findall(r'\d+', str(val))
                if digits:
                    return int(digits[0])
            except Exception:
                pass
            return 9999

        def parse_pain_score(val) -> float:
            try:
                return float(val)
            except Exception:
                return 0.0

        all_rows.sort(
            key=lambda r: (
                str(r[0]).lower() if len(r) > 0 else "",
                parse_radius(r[1]) if len(r) > 1 else 9999,
                -parse_pain_score(r[17]) if len(r) > 17 else 0.0
            )
        )

        ws.clear()
        ws.update([headers] + all_rows)

        return {"added": added, "skipped": skipped, "tab": tab_name}

    except Exception as e:
        logger.warning(f"append_leads_to_sheet failed: {e}")
        return {"added": 0, "skipped": 0, "tab": tab_name, "error": str(e)}


def check_if_in_sheet(place_id: str, location: str) -> bool:
    """Return True if a lead with this place_id already exists in the location's tab."""
    client = get_sheets_client()
    if client is None:
        return False

    tab_name = _parse_tab_name(location)
    try:
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        ws = spreadsheet.worksheet(tab_name)
        all_values = ws.get_all_values()
        if len(all_values) < 2:
            return False
        header = all_values[0]
        for candidate in ("place_id", "Place ID"):
            if candidate in header:
                col_idx = header.index(candidate)
                for data_row in all_values[1:]:
                    if len(data_row) > col_idx and data_row[col_idx].strip() == place_id:
                        return True
                return False
        return False
    except Exception as e:
        logger.warning(f"check_if_in_sheet failed: {e}")
        return False
