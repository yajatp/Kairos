from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from datetime import date

logger = logging.getLogger(__name__)

_STATE_ZIP_RE = re.compile(r"^([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?$")
_SECOND_CITY_MIN_SHARE = 0.30

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
    "AI Extraction",
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
    # Blank trailing columns for manual outreach tracking. "Outreach Notes" rather
    # than "Notes" to avoid colliding with the auto-filled Notes column above.
    "Status",
    "Outreach Notes",
    "Last Contacted",
    "Follow-up Date",
    "Outcome",
]
_MANUAL_OUTREACH_COLS = ["Status", "Outreach Notes", "Last Contacted", "Follow-up Date", "Outcome"]


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


def _parse_city_state(address: str) -> tuple[str, str] | None:
    """Pull (city, state) out of a Google formatted address, or None."""
    if not address:
        return None
        
    # Match standard format: "... Allen, TX 75013..."
    m = re.search(r",\s*([^,]+?),\s*([A-Z]{2})\s*\d{5}", address)
    if m:
        return m.group(1).strip(), m.group(2).strip()
        
    # Match format without zip: "... Allen, TX, USA"
    m = re.search(r",\s*([^,]+?),\s*([A-Z]{2})(?:,\s*USA)?$", address)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # Fallback to part iteration
    parts = [p.strip() for p in address.split(",") if p.strip()]
    for i, part in enumerate(parts):
        m = _STATE_ZIP_RE.match(part)
        if m and i > 0:
            return parts[i - 1], m.group(1)
    return None


def _derive_primary_location(clinics: list[dict]) -> str:
    """Name the run after where its clinics actually are.

    Returns "City, ST", or "City1 & City2, ST" when a second city holds a
    meaningful share (the donut straddles a line). "" if nothing parseable.
    """
    counts: Counter[tuple[str, str]] = Counter()
    for c in clinics:
        cs = _parse_city_state(c.get("address", ""))
        if cs:
            counts[cs] += 1
    if not counts:
        return ""

    total = sum(counts.values())
    ranked = counts.most_common(2)
    (top_city, top_state), _ = ranked[0]

    if len(ranked) > 1:
        (c2_city, c2_state), c2_n = ranked[1]
        if c2_n / total >= _SECOND_CITY_MIN_SHARE:
            if c2_state == top_state:
                return f"{top_city} & {c2_city}, {top_state}"
            return f"{top_city}, {top_state} & {c2_city}, {c2_state}"
    return f"{top_city}, {top_state}"


def _unique_tab_name(ss, base: str) -> str:
    """Return base (<=50 chars), suffixing ` 2`, ` 3`... if the tab exists."""
    existing = {w.title for w in ss.worksheets()}
    if base[:50] not in existing:
        return base[:50]
    n = 2
    while f"{base} {n}"[:50] in existing:
        n += 1
    return f"{base} {n}"[:50]


def _build_output_rows(
    clinics: list[dict], tab_name: str, run_date: str, gemini_used: bool = False,
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
            "Gemini" if gemini_used else "Off",
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
        row.extend("" for _ in _MANUAL_OUTREACH_COLS)
        rows.append(row)

    return rows


def write_run_to_sheet(
    clinics: list[dict],
    polygon_coords: list[list[float]],
    area_name: str | None,
    buffer_miles: float,
    run_date: str | None = None,
    gemini_used: bool = False,
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
        # Upgrade coordinate-based tab names (e.g. "2026-06-25 (33.11, -96.67)")
        if re.search(r"\(\s*-?\d+\.\d+,\s*-?\d+\.\d+\s*\)", tab_name):
            primary = _derive_primary_location(clinics)
            if primary:
                new_base = f"{primary} (auto)"
                new_tab_name = _unique_tab_name(ss, new_base)
                try:
                    try:
                        ws = ss.worksheet(tab_name)
                        ws.update_title(new_tab_name)
                    except Exception:
                        pass # Tab might have been manually deleted from sheets
                    
                    # Update the area index to replace the old name so it doesn't get orphaned
                    try:
                        idx_ws = ss.worksheet(_AREA_INDEX_TAB)
                        idx_rows = idx_ws.get_all_values()
                        for i, r in enumerate(idx_rows):
                            if r and r[0] == tab_name:
                                idx_ws.update_cell(i + 1, 1, new_tab_name)
                                break
                    except Exception as e:
                        logger.warning("Failed to update area index after rename: %s", e)
                        
                    tab_name = new_tab_name
                    logger.info("Upgraded coordinate tab to %s", tab_name)
                except Exception as e:
                    logger.warning("Failed to rename tab: %s", e)
    elif area_name and area_name.strip():
        tab_name = area_name.strip()[:50]
    else:
        primary = _derive_primary_location(clinics)
        if primary:
            base = f"{primary} (auto)"
        else:
            base = f"{run_date} ({centroid_lat:.2f}, {centroid_lng:.2f}) (auto)"
        tab_name = _unique_tab_name(ss, base)

    rows = _build_output_rows(clinics, tab_name, run_date, gemini_used)

    try:
        ws = ss.worksheet(tab_name)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(
            title=tab_name,
            rows=max(len(rows) + 20, 100),
            cols=len(OUTPUT_HEADERS) + 2,
        )

    ws.update([OUTPUT_HEADERS] + rows, value_input_option="USER_ENTERED")

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


def get_all_donut_worksheet_records() -> list[tuple[str, list[dict]]]:
    """Read every area tab's rows once (excludes ``_area_index``).

    Returns ``(tab_title, records)`` pairs. Used for bulk prefetch so a History
    page with many Donut runs reads the sheet a single time instead of once per
    run; pair with :func:`match_donut_run_records` to slice out a single run.
    """
    from utils.sheets import get_sheets_client

    client = get_sheets_client()
    if client is None:
        return []
    try:
        ss = _get_or_create_donut_spreadsheet(client)
    except Exception as e:
        logger.warning("Could not open Donut sheet for bulk read: %s", e)
        return []

    out: list[tuple[str, list[dict]]] = []
    for ws in ss.worksheets():
        if ws.title == _AREA_INDEX_TAB:
            continue
        try:
            out.append((ws.title, ws.get_all_records()))
        except Exception:
            continue
    return out


def match_donut_run_records(
    all_ws: list[tuple[str, list[dict]]], location: str, run_date_iso: str
) -> list[dict]:
    """Slice the rows for one run out of already-read worksheet records.

    Match on Run Date, preferring the tab whose name corresponds to the run's
    location; fall back to all rows on that date.
    """
    loc = (location or "").strip().lower()
    preferred: list[dict] = []
    fallback: list[dict] = []
    for title, records in all_ws:
        tab_match = bool(loc) and (loc in title.lower() or title.lower() in loc)
        for rec in records:
            if str(rec.get("Run Date", "")).strip() != run_date_iso:
                continue
            (preferred if tab_match else fallback).append(rec)
    return preferred or fallback


def get_donut_clinics_for_run(location: str, run_date_iso: str) -> list[dict]:
    """Read dentist rows for one Donut run back from the Google Sheet.

    Donut clinics aren't stored per-run in Supabase — only in the Donut Sheet,
    keyed by Run Date + area tab. Each returned dict is keyed by ``OUTPUT_HEADERS``.
    """
    return match_donut_run_records(
        get_all_donut_worksheet_records(), location, run_date_iso
    )


def append_donut_clinics_to_sheet(records: list[dict], tab_name: str) -> dict:
    """Idempotently append donut dentist rows to their area tab, dedup by Place ID.

    Mirrors ``append_leads_to_sheet``: existing rows are kept, only missing Place
    IDs are added. Returns ``{"added": N, "skipped": M, "tab": tab_name}``.
    """
    from utils.sheets import get_sheets_client

    client = get_sheets_client()
    if client is None:
        return {"added": 0, "skipped": 0, "tab": tab_name, "error": "Sheets not configured"}
    if not records:
        return {"added": 0, "skipped": 0, "tab": tab_name}

    tab_name = (tab_name or "").strip()[:50] or "Donut Run"
    pid_idx = OUTPUT_HEADERS.index("Place ID")
    try:
        ss = _get_or_create_donut_spreadsheet(client)
        try:
            ws = ss.worksheet(tab_name)
        except Exception:
            ws = ss.add_worksheet(
                title=tab_name,
                rows=max(len(records) + 20, 100),
                cols=len(OUTPUT_HEADERS) + 2,
            )
            ws.append_row(OUTPUT_HEADERS, value_input_option="RAW")

        existing_values = ws.get_all_values()
        existing_rows = existing_values[1:] if len(existing_values) > 1 else []
        merged: dict[str, list] = {}
        order: list[str] = []
        for row in existing_rows:
            if len(row) > pid_idx and str(row[pid_idx]).strip():
                pid = str(row[pid_idx]).strip()
                if pid not in merged:
                    order.append(pid)
                merged[pid] = row

        added = skipped = 0
        for rec in records:
            pid = str(rec.get("Place ID", "")).strip()
            if not pid:
                continue
            if pid in merged:
                skipped += 1
                continue
            merged[pid] = [str(rec.get(h, "")) for h in OUTPUT_HEADERS]
            order.append(pid)
            added += 1

        all_rows = [merged[p] for p in order]
        ws.clear()
        ws.update([OUTPUT_HEADERS] + all_rows, value_input_option="USER_ENTERED")
        return {"added": added, "skipped": skipped, "tab": tab_name}
    except Exception as e:
        logger.warning("append_donut_clinics_to_sheet failed: %s", e)
        return {"added": 0, "skipped": 0, "tab": tab_name, "error": str(e)}


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
