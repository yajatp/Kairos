from __future__ import annotations

import difflib
import logging
import requests

logger = logging.getLogger(__name__)

ADZUNA_QUERIES = [
    "dental receptionist",
    "front desk dental",
    "treatment coordinator dental",
    "insurance coordinator dental",
    "scheduling coordinator dental",
    "patient care coordinator dental",
]

STRIP_WORDS = {
    "dental", "dentistry", "smile", "smiles", "clinic", "family", "associates",
    "llc", "inc", "pllc", "dds", "dmd", "dr", "doctor", "office", "care",
    "center", "group", "practice",
}


def _normalize(name: str) -> str:
    import re
    name = name.lower()
    name = re.sub(r"[^\w\s]", " ", name)
    tokens = [t for t in name.split() if t not in STRIP_WORDS]
    return " ".join(tokens).strip()


def fetch_adzuna_jobs(location: str, app_id: str, app_key: str) -> list[dict]:
    if not app_id or not app_key:
        logger.warning("Adzuna credentials missing — skipping job signal")
        return []

    seen_companies = set()
    results = []

    for query in ADZUNA_QUERIES:
        try:
            resp = requests.get(
                "https://api.adzuna.com/v1/api/jobs/us/search/1",
                params={
                    "app_id": app_id,
                    "app_key": app_key,
                    "results_per_page": 50,
                    "what": query,
                    "where": location,
                    "distance": 50,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning(f"Adzuna returned {resp.status_code} for query '{query}'")
                continue
            data = resp.json()
            for job in data.get("results", []):
                company = job.get("company", {}).get("display_name", "")
                if not company:
                    continue
                normalized = _normalize(company)
                if normalized in seen_companies:
                    continue
                seen_companies.add(normalized)
                results.append({
                    "company_name": company,
                    "job_url": job.get("redirect_url", ""),
                    "job_title": job.get("title", ""),
                })
        except Exception as e:
            logger.warning(f"Adzuna error for query '{query}': {e}")

    return results


def match_clinic_to_job(clinic_name: str, jobs: list[dict], threshold: float = 0.55) -> dict | None:
    if not jobs:
        return None

    clinic_norm = _normalize(clinic_name)
    if not clinic_norm:
        return None

    best_match = None
    best_ratio = 0.0

    for job in jobs:
        company_norm = _normalize(job["company_name"])
        if not company_norm:
            continue
        ratio = difflib.SequenceMatcher(None, clinic_norm, company_norm).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = job

    if best_ratio >= threshold:
        return best_match
    return None
