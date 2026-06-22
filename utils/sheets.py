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
    """Convert a location string to a sheet tab name like 'TX - Dallas'."""
    if not location or not location.strip():
        return "Unknown"
    loc = location.strip()
    parts = [p.strip() for p in loc.split(",")]
    if len(parts) >= 2:
        tail = parts[-1].split()[0].upper()
        if tail in _STATE_ABBRS:
            city = ", ".join(parts[:-1])
            return f"{tail} - {city}"
    words = loc.split()
    if len(words) >= 2 and words[-1].upper() in _STATE_ABBRS:
        state = words[-1].upper()
        city = " ".join(words[:-1])
        return f"{state} - {city}"
    # ZIP or unrecognised format — use as-is
    return re.sub(r"[^\w\s\-]", "", loc)[:50]


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
    """Append leads to the Google Sheet, skipping duplicates by place_id.

    Returns a dict: ``{"added": N, "skipped": M, "tab": tab_name}``.
    """
    client = get_sheets_client()
    if client is None:
        return {"added": 0, "skipped": 0, "tab": "", "error": "Sheets not configured"}

    tab_name = _parse_tab_name(location)

    try:
        spreadsheet = client.open_by_key(SPREADSHEET_ID)

        # Build headers: Run Date + all DataFrame columns
        df_cols = list(df.columns)
        headers = ["Run Date"] + df_cols

        # Determine the place_id column name (may vary)
        place_id_col: str | None = None
        for candidate in ("place_id", "Place ID", "place id"):
            if candidate in df_cols:
                place_id_col = candidate
                break

        ws = _get_or_create_worksheet(spreadsheet, tab_name, headers)

        # Read existing place_ids from column A (first data column after header)
        existing_rows = ws.get_all_values()
        existing_place_ids: set[str] = set()
        if len(existing_rows) > 1:
            # Column A is "Run Date"; column B would be first df col.
            # If place_id_col is set, find its header position in the sheet.
            if place_id_col and headers:
                try:
                    pid_col_idx = headers.index(place_id_col)
                    for data_row in existing_rows[1:]:
                        if len(data_row) > pid_col_idx and data_row[pid_col_idx]:
                            existing_place_ids.add(str(data_row[pid_col_idx]).strip())
                except ValueError:
                    pass

        rows_to_add: list[list] = []
        skipped = 0

        for _, row in df.iterrows():
            if place_id_col:
                pid = str(row.get(place_id_col, "")).strip()
                if pid and pid in existing_place_ids:
                    skipped += 1
                    continue
            values = [run_date] + [row.get(col, "") for col in df_cols]
            rows_to_add.append(values)
            if place_id_col:
                existing_place_ids.add(str(row.get(place_id_col, "")))

        if rows_to_add:
            ws.append_rows(rows_to_add, value_input_option="RAW")

        return {"added": len(rows_to_add), "skipped": skipped, "tab": tab_name}

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
        # Find place_id column index
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
