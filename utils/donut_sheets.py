from __future__ import annotations

import json
import logging
import os
from datetime import date

logger = logging.getLogger(__name__)

DONUT_SHEET_NAME = "Kairos Donut Scraper"
_AREA_INDEX_TAB = "_area_index"
_AREA_INDEX_HEADERS = [
    "tab_name", "polygon_geojson", "centroid_lat", "centroid_lng",
    "buffer_miles", "last_run_date",
]
_IOU_SAME_AREA_THRESHOLD = 0.85

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

OUTPUT_HEADERS = [
    "Run Date",
    "Area / Tab Name",
    "Place ID",
    "Clinic Name",
    "Classification",
    "Address",
    "Latitude",
    "Longitude",
    "Inclusion Zone",
    "Phone Number",
    "Website",
    "Email",
    "Email Source",
    "Head Dentist / Key Staff",
    "Staff Extraction Source",
    "Hours - Monday",
    "Hours - Tuesday",
    "Hours - Wednesday",
    "Hours - Thursday",
    "Hours - Friday",
    "Hours - Saturday",
    "Hours - Sunday",
    "Notes",
]


def _get_or_create_donut_spreadsheet(client):
    """Open the Donut Scraper sheet by env var ID, by name, or create it fresh."""
    sheet_id = os.getenv("DONUT_SPREADSHEET_ID", "").strip()
    if sheet_id:
        try:
            return client.open_by_key(sheet_id)
        except Exception as e:
            logger.warning("Could not open DONUT_SPREADSHEET_ID %s: %s", sheet_id, e)

    try:
        return client.open(DONUT_SHEET_NAME)
    except Exception:
        pass

    ss = client.create(DONUT_SHEET_NAME)
    logger.info("Created new Donut Scraper sheet: %s", ss.id)
    return ss


def _get_area_index(spreadsheet) -> list[dict]:
    try:
        ws = spreadsheet.worksheet(_AREA_INDEX_TAB)
        return ws.get_all_records()
    except Exception:
        return []


def _upsert_area_index_row(
    spreadsheet,
    tab_name: str,
    polygon_geojson: str,
    centroid_lat: float,
    centroid_lng: float,
    buffer_miles: float,
    run_date: str,
) -> None:
    try:
        ws = spreadsheet.worksheet(_AREA_INDEX_TAB)
    except Exception:
        ws = spreadsheet.add_worksheet(title=_AREA_INDEX_TAB, rows=500, cols=10)
        ws.append_row(_AREA_INDEX_HEADERS, value_input_option="RAW")

    rows = ws.get_all_values()
    new_row = [tab_name, polygon_geojson, centroid_lat, centroid_lng, buffer_miles, run_date]

    for i, row in enumerate(rows[1:], start=2):
        if row and row[0] == tab_name:
            ws.update(f"A{i}:F{i}", [new_row])
            return

    ws.append_row(new_row, value_input_option="RAW")


def _find_matching_area(area_index: list[dict], polygon_coords: list[list[float]]) -> dict | None:
    """Return the area record with the best IoU above the threshold, or None."""
    from pipeline.donut_search import compute_polygon_iou

    best_match = None
    best_iou = 0.0
    for area in area_index:
        try:
            existing_coords = json.loads(area.get("polygon_geojson", "[]"))
            iou = compute_polygon_iou(polygon_coords, existing_coords)
            if iou > best_iou:
                best_iou = iou
                best_match = area
        except Exception:
            continue

    if best_iou >= _IOU_SAME_AREA_THRESHOLD and best_match:
        return best_match
    return None


def _build_output_rows(
    clinics: list[dict], tab_name: str, run_date: str,
) -> list[list]:
    def callable_rank(c: dict) -> int:
        has_phone = bool(c.get("phone"))
        has_contact = bool(c.get("head_dentist") or c.get("email"))
        if has_phone and has_contact:
            return 0
        if has_phone:
            return 1
        if has_contact:
            return 2
        return 3

    sorted_clinics = sorted(clinics, key=callable_rank)

    rows = []
    for c in sorted_clinics:
        hours = c.get("hours_by_day", {})
        row = [
            run_date,
            tab_name,
            c.get("place_id", ""),
            c.get("name", ""),
            c.get("classification", ""),
            c.get("address", ""),
            c.get("lat", ""),
            c.get("lng", ""),
            c.get("inclusion_zone", "").capitalize(),
            c.get("phone", ""),
            c.get("website", ""),
            c.get("email", ""),
            c.get("email_source", ""),
            c.get("head_dentist", ""),
            c.get("staff_source", ""),
        ]
        for day in _DAYS:
            row.append(hours.get(day, ""))
        row.append(c.get("notes", ""))
        rows.append(row)

    return rows


def write_run_to_sheet(
    clinics: list[dict],
    polygon_coords: list[list[float]],
    area_name: str | None,
    buffer_miles: float,
    run_date: str | None = None,
) -> dict:
    """
    Write a Donut Scraper run to the Google Sheet.

    Returns {"tab": tab_name, "rows_written": N, "sheet_url": url, "sheet_id": id}
    or {"error": message}.
    """
    from utils.sheets import get_sheets_client

    client = get_sheets_client()
    if client is None:
        return {"error": "Google Sheets not configured (GOOGLE_SERVICE_ACCOUNT_JSON missing)"}

    if run_date is None:
        run_date = date.today().isoformat()

    try:
        ss = _get_or_create_donut_spreadsheet(client)
    except Exception as e:
        return {"error": f"Could not open/create Donut Scraper sheet: {e}"}

    area_index = _get_area_index(ss)

    lats = [c[1] for c in polygon_coords]
    lngs = [c[0] for c in polygon_coords]
    centroid_lat = sum(lats) / len(lats)
    centroid_lng = sum(lngs) / len(lngs)

    match = _find_matching_area(area_index, polygon_coords)
    if match:
        tab_name = match["tab_name"]
    else:
        if area_name and area_name.strip():
            tab_name = area_name.strip()[:50]
        else:
            tab_name = f"{run_date} ({centroid_lat:.2f}, {centroid_lng:.2f})"

    rows = _build_output_rows(clinics, tab_name, run_date)

    try:
        ws = ss.worksheet(tab_name)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(
            title=tab_name,
            rows=max(len(rows) + 20, 100),
            cols=len(OUTPUT_HEADERS) + 2,
        )

    ws.update([OUTPUT_HEADERS] + rows, value_input_option="RAW")

    _upsert_area_index_row(
        ss,
        tab_name,
        json.dumps(polygon_coords),
        centroid_lat,
        centroid_lng,
        buffer_miles,
        run_date,
    )

    sheet_url = f"https://docs.google.com/spreadsheets/d/{ss.id}"
    return {
        "tab": tab_name,
        "rows_written": len(rows),
        "sheet_url": sheet_url,
        "sheet_id": ss.id,
    }


def get_saved_areas() -> list[dict]:
    """Return list of saved area records from _area_index for the re-run dropdown."""
    from utils.sheets import get_sheets_client

    client = get_sheets_client()
    if client is None:
        return []
    try:
        ss = _get_or_create_donut_spreadsheet(client)
        return _get_area_index(ss)
    except Exception:
        return []
