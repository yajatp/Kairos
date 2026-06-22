"""
Usage tracking with two backends:
  - Supabase (cloud, universal) when SUPABASE_URL + SUPABASE_KEY are set
  - Local JSON file (fallback for solo / offline use)

Supabase DDL — run both statements once in Supabase SQL editor:

    CREATE TABLE runs (
        id                 BIGSERIAL PRIMARY KEY,
        timestamp          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        location           TEXT,
        geocode_calls      INT DEFAULT 0,
        search_calls       INT DEFAULT 0,
        detail_calls       INT DEFAULT 0,
        adzuna_calls       INT DEFAULT 0,
        outscraper_reviews INT DEFAULT 0,
        clinics_found      INT DEFAULT 0,
        leads_found        INT DEFAULT 0,
        stopped_early      BOOLEAN DEFAULT FALSE
    );

    CREATE TABLE leads (
        id              BIGSERIAL PRIMARY KEY,
        place_id        TEXT NOT NULL,
        run_location    TEXT,
        name            TEXT,
        address         TEXT,
        phone           TEXT,
        website         TEXT,
        specialty       TEXT,
        classification  TEXT,
        pain_score      INT,
        signals         TEXT,
        outreach_angle  TEXT,
        rating          FLOAT,
        total_reviews   INT,
        extended_hours  BOOLEAN DEFAULT FALSE,
        online_booking  BOOLEAN DEFAULT FALSE,
        review_depth    TEXT,
        scored_at       TIMESTAMPTZ DEFAULT NOW()
    );

NOTE: leads is append-only — each run adds new rows, so you can track how a
clinic's score changes across multiple runs of the same city.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
TRACKER_FILE = Path("api_usage.json")

OUTSCRAPER_MONTHLY_LIMIT    = 400
GOOGLE_MONTHLY_CREDIT_USD   = 200.0
GOOGLE_GEOCODE_COST         = 0.005
GOOGLE_SEARCH_COST          = 0.032
GOOGLE_DETAIL_COST          = 0.017
ADZUNA_DAILY_LIMIT          = 250

_SUPABASE_URL: str = ""
_SUPABASE_KEY: str = ""
_creds_loaded: bool = False


def _ensure_creds() -> None:
    global _SUPABASE_URL, _SUPABASE_KEY, _creds_loaded
    if _creds_loaded:
        return
    _SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    _SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
    if not (_SUPABASE_URL and _SUPABASE_KEY):
        try:
            import streamlit as st
            _SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
            _SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")
        except Exception:
            pass
    _creds_loaded = True


def _supabase_ok() -> bool:
    _ensure_creds()
    return bool(_SUPABASE_URL and _SUPABASE_KEY)


def _headers(prefer: str = "return=minimal") -> dict:
    _ensure_creds()
    h = {
        "apikey": _SUPABASE_KEY,
        "Authorization": f"Bearer {_SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


# ── Helpers ───────────────────────────────────────────────────────────────────

def estimated_google_cost(geocode: int, searches: int, details: int) -> float:
    return (
        geocode  * GOOGLE_GEOCODE_COST +
        searches * GOOGLE_SEARCH_COST  +
        details  * GOOGLE_DETAIL_COST
    )


def _current_ym() -> str:
    return datetime.now().strftime("%Y-%m")


# ── Local JSON helpers ────────────────────────────────────────────────────────

def _blank_month() -> dict:
    return {
        "year_month": _current_ym(),
        "google":     {"geocode_calls": 0, "search_calls": 0, "detail_calls": 0},
        "adzuna":     {"job_fetch_calls": 0},
        "outscraper": {"reviews_used": 0},
    }


def _local_load() -> dict:
    if not TRACKER_FILE.exists():
        return {"month": _blank_month(), "runs": []}
    try:
        raw = json.loads(TRACKER_FILE.read_text())
        if raw.get("month", {}).get("year_month") != _current_ym():
            raw["month"] = _blank_month()
        return raw
    except Exception as e:
        logger.warning(f"Could not read usage tracker: {e}")
        return {"month": _blank_month(), "runs": []}


def _local_save(state: dict) -> None:
    try:
        TRACKER_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        logger.warning(f"Could not write usage tracker: {e}")


# ── Public read API ───────────────────────────────────────────────────────────

def get_monthly_stats() -> dict:
    if _supabase_ok():
        try:
            start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
            resp = requests.get(
                f"{_SUPABASE_URL}/rest/v1/runs",
                headers=_headers(prefer=""),
                params={
                    "timestamp": f"gte.{start}",
                    "select": "geocode_calls,search_calls,detail_calls,adzuna_calls,outscraper_reviews",
                },
                timeout=8,
            )
            runs = resp.json() if resp.ok else []
            return {
                "year_month": _current_ym(),
                "google": {
                    "geocode_calls": sum(r.get("geocode_calls", 0) for r in runs),
                    "search_calls":  sum(r.get("search_calls",  0) for r in runs),
                    "detail_calls":  sum(r.get("detail_calls",  0) for r in runs),
                },
                "adzuna":     {"job_fetch_calls":  sum(r.get("adzuna_calls", 0) for r in runs)},
                "outscraper": {"reviews_used": sum(r.get("outscraper_reviews", 0) for r in runs)},
            }
        except Exception as e:
            logger.warning(f"Supabase monthly stats failed: {e}")

    return _local_load()["month"]


def get_run_history(limit: int = 20) -> list[dict]:
    if _supabase_ok():
        try:
            resp = requests.get(
                f"{_SUPABASE_URL}/rest/v1/runs",
                headers=_headers(prefer=""),
                params={"order": "timestamp.desc", "limit": limit},
                timeout=8,
            )
            if resp.ok:
                rows = resp.json()
                # Normalise field names to match local format
                return [
                    {
                        "timestamp":           r.get("timestamp", ""),
                        "location":            r.get("location", ""),
                        "geocode_calls":       r.get("geocode_calls", 0),
                        "search_calls":        r.get("search_calls", 0),
                        "detail_calls":        r.get("detail_calls", 0),
                        "adzuna_calls":        r.get("adzuna_calls", 0),
                        "outscraper_reviews":  r.get("outscraper_reviews", 0),
                        "clinics_found":       r.get("clinics_found", 0),
                        "leads_found":         r.get("leads_found", 0),
                        "stopped_early":       r.get("stopped_early", False),
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning(f"Supabase run history failed: {e}")

    return list(reversed(_local_load()["runs"][-limit:]))


def get_remaining_outscraper() -> int:
    stats = get_monthly_stats()
    used = stats["outscraper"].get("reviews_used", 0)
    return max(0, OUTSCRAPER_MONTHLY_LIMIT - used)


def get_remaining_budget() -> int:
    return get_remaining_outscraper()


# ── Public write API ──────────────────────────────────────────────────────────

def record_run(
    location: str,
    geocode_calls: int,
    search_calls: int,
    detail_calls: int,
    adzuna_calls: int,
    outscraper_reviews: int,
    clinics_found: int,
    leads_found: int,
    stopped_early: bool = False,
) -> None:
    payload = {
        "timestamp":          datetime.utcnow().isoformat() + "Z",
        "location":           location,
        "geocode_calls":      geocode_calls,
        "search_calls":       search_calls,
        "detail_calls":       detail_calls,
        "adzuna_calls":       adzuna_calls,
        "outscraper_reviews": outscraper_reviews,
        "clinics_found":      clinics_found,
        "leads_found":        leads_found,
        "stopped_early":      stopped_early,
    }

    if _supabase_ok():
        try:
            resp = requests.post(
                f"{_SUPABASE_URL}/rest/v1/runs",
                headers=_headers(),
                json=payload,
                timeout=8,
            )
            if not resp.ok:
                logger.warning(f"Supabase insert failed: {resp.status_code} {resp.text}")
            return
        except Exception as e:
            logger.warning(f"Supabase record_run failed: {e} — falling back to local")

    # Local fallback
    state = _local_load()
    m = state["month"]
    m["google"]["geocode_calls"] += geocode_calls
    m["google"]["search_calls"]  += search_calls
    m["google"]["detail_calls"]  += detail_calls
    m["adzuna"]["job_fetch_calls"] += adzuna_calls
    m["outscraper"]["reviews_used"] += outscraper_reviews
    state["runs"].append(payload)
    _local_save(state)


def record_usage(reviews_pulled: int) -> None:
    """Legacy shim — Outscraper reviews are now tracked via record_run."""
    if _supabase_ok():
        return  # record_run handles it end-to-end
    state = _local_load()
    state["month"]["outscraper"]["reviews_used"] = (
        state["month"]["outscraper"].get("reviews_used", 0) + reviews_pulled
    )
    _local_save(state)


def using_supabase() -> bool:
    return _supabase_ok()


# ── Leads persistence (Supabase-only — no local fallback) ─────────────────────

def save_lead(
    place_id: str,
    run_location: str,
    name: str,
    address: str,
    phone: str,
    website: str,
    specialty: str,
    classification: str,
    pain_score: int,
    signals: str,
    outreach_angle: str,
    rating: float,
    total_reviews: int,
    extended_hours: bool,
    online_booking: bool,
    review_depth: str,
    reviews_json: str = None,  # -- Run: ALTER TABLE leads ADD COLUMN IF NOT EXISTS reviews_json TEXT;
) -> None:
    """Upsert a scored lead by place_id. Silent no-op when Supabase is not configured."""
    if not _supabase_ok():
        return
    payload = {
        "place_id":       place_id,
        "run_location":   run_location,
        "name":           name,
        "address":        address,
        "phone":          phone,
        "website":        website,
        "specialty":      specialty,
        "classification": classification,
        "pain_score":     pain_score,
        "signals":        signals,
        "outreach_angle": outreach_angle,
        "rating":         rating,
        "total_reviews":  total_reviews,
        "extended_hours": extended_hours,
        "online_booking": online_booking,
        "review_depth":   review_depth,
        "scored_at":      datetime.utcnow().isoformat() + "Z",
        "reviews_json":   reviews_json,
    }
    try:
        resp = requests.post(
            f"{_SUPABASE_URL}/rest/v1/leads",
            headers=_headers(),
            json=payload,
            timeout=8,
        )
        if not resp.ok:
            logger.warning(f"Supabase save_lead failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.warning(f"save_lead failed: {e}")


def get_leads(location: str | None = None, limit: int = 200) -> list[dict]:
    """Fetch persisted leads from Supabase, optionally filtered by location."""
    if not _supabase_ok():
        return []
    params: dict = {"order": "pain_score.desc", "limit": limit}
    if location:
        params["run_location"] = f"ilike.*{location}*"
    try:
        resp = requests.get(
            f"{_SUPABASE_URL}/rest/v1/leads",
            headers=_headers(prefer=""),
            params=params,
            timeout=8,
        )
        return resp.json() if resp.ok else []
    except Exception as e:
        logger.warning(f"get_leads failed: {e}")
        return []
