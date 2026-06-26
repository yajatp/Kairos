"""Deduplicate same-address clinic listings and extract free doctor names.

Google Places Nearby Search returns separate entries for the same physical
practice when Google has listings under the clinic name, the doctor's name,
and variant brand names.  This module merges those into a single row and
pre-fills the head_dentist field for free — no Gemini call required.

Algorithm (validated against 23 real ambiguous address groups via web search):

1. Group by normalised address
2. Classify each listing name as "person" or "business"
3. Sub-cluster by phone (same phone = definitely same practice)
4. Within each sub-cluster pick the business name as clinic, fold person names
   into head_dentist
5. If only ONE business exists at the address, fold remaining person-only
   sub-clusters into it (validated: Allen Dental Center, Enamel, Brident …)
6. If multiple businesses exist, person-only sub-clusters stay separate
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

logger = logging.getLogger(__name__)

# ── Name classification ──────────────────────────────────────────────────────

_CREDENTIAL_WORDS = {
    "dds", "dmd", "md", "do", "phd", "ms", "fagd", "magd",
    "ficd", "facd", "dabp", "facs",
}

_DR_PREFIX_RE = re.compile(r"^Dr\.?\s+", re.IGNORECASE)

_CREDENTIAL_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(c) for c in _CREDENTIAL_WORDS) + r")\b",
    re.IGNORECASE,
)

_BUSINESS_SUFFIXES = re.compile(
    r"\b(?:dental|dentistry|orthodontics|orthodontist|endodontics|pediatric|"
    r"family|center|clinic|associates|group|partners|specialists|surgery|"
    r"implant|smile|smiles|braces|oral|perio|prosth|cosmetic|"
    r"health|wellness|care|kids|jupiter|comfort|gentle|bright|"
    r"refresh|brident|aspen|heartland|pacific)\b",
    re.IGNORECASE,
)


def _looks_like_person(name: str) -> bool:
    """Return True if the listing name looks like a person (doctor) rather than
    a business.  Uses credential detection and the 'Dr.' prefix as primary
    signals, but guards against false positives on business names that happen
    to contain a doctor's name (e.g. 'Dr. Rebecca Bork Family Dentistry').
    """
    clean = name.strip()
    if not clean:
        return False

    has_credential = bool(_CREDENTIAL_RE.search(clean))
    has_dr_prefix = bool(_DR_PREFIX_RE.match(clean))
    has_business_word = bool(_BUSINESS_SUFFIXES.search(clean))

    # "Dr. Rebecca Bork Family Dentistry" → business (has a business word),
    # but we still extract the doctor name from it later.
    if has_business_word:
        return False

    if has_credential or has_dr_prefix:
        return True

    # Bare "Firstname Lastname" with no other context — a person if it's
    # exactly 2–4 title-case words with no business keywords.
    words = clean.split()
    if 2 <= len(words) <= 4 and all(w[0].isupper() and w[1:].replace("'", "").replace("-", "").islower() for w in words if len(w) > 1):
        return True

    return False


def _extract_doctor_from_name(name: str) -> str | None:
    """Pull a clean doctor name out of a listing name.

    Handles:
      "Dr. Paul Ezzo, DDS PhD"  → "Paul Ezzo, DDS"
      "Christine J. Coke, DDS, MD" → "Christine J. Coke, DDS"
      "Nguyen Bach Cuc DDS"     → "Nguyen Bach Cuc, DDS"
      "Dr. Rebecca Bork Family Dentistry" → "Rebecca Bork"
      "Dickey Family Dentistry"  → None (no person signal)
    """
    clean = name.strip()
    if not clean:
        return None

    # Strip "Dr." prefix
    clean = _DR_PREFIX_RE.sub("", clean).strip()

    # If there's a business suffix, try to extract the person part
    biz_match = _BUSINESS_SUFFIXES.search(clean)
    if biz_match:
        # Check if the name is split by a delimiter like colon, dash, or pipe
        parts = re.split(r"[:|\-–—]", clean)
        if len(parts) > 1:
            # Find the part that has a credential or Dr. prefix
            for p in parts:
                p_clean = p.strip()
                if _CREDENTIAL_RE.search(p_clean) or _DR_PREFIX_RE.match(p_clean):
                    # Extract from just this part
                    extracted = _extract_doctor_from_name(p_clean)
                    if extracted:
                        return extracted
        
        # Fallback: assume the person is before the business suffix
        person_part = clean[: biz_match.start()].strip(" -–—,")
        if person_part and len(person_part.split()) >= 2:
            return person_part
        return None

    # Extract credentials
    creds = _CREDENTIAL_RE.findall(clean)
    name_without_creds = _CREDENTIAL_RE.sub("", clean).strip(" ,;-–—")

    # Clean up multiple spaces and trailing punctuation
    name_without_creds = re.sub(r"\s+", " ", name_without_creds).strip(" ,;-–—")

    if not name_without_creds or len(name_without_creds.split()) < 2:
        # Single word, not a real name
        if creds:
            return clean  # Return as-is if it had credentials
        return None

    if creds:
        primary_cred = creds[0].upper().replace(".", "")
        return f"{name_without_creds}, {primary_cred}"

    return name_without_creds


# ── Address normalisation ────────────────────────────────────────────────────

_SUITE_RE = re.compile(
    r"\b(?:ste|suite|unit|apt|#)\s*\.?\s*(\w+)",
    re.IGNORECASE,
)


def _normalise_address(addr: str) -> str:
    """Collapse whitespace, lowercase, normalise suite/ste/#."""
    a = addr.strip().lower()
    a = re.sub(r"\s+", " ", a)
    # Normalise "ste", "suite", "#" to a canonical form
    a = re.sub(r"\bste\.?\b", "ste", a)
    a = re.sub(r"\bsuite\b", "ste", a)
    a = re.sub(r"#(\w)", r"ste \1", a)
    return a


# ── Core deduplication ───────────────────────────────────────────────────────


def deduplicate_clinics(clinics: list[dict]) -> list[dict]:
    """Merge same-address listings and pre-fill head_dentist.

    Returns a new list of clinic dicts; originals are not mutated.
    """
    if not clinics:
        return clinics

    # Group by normalised address
    addr_groups: dict[str, list[dict]] = defaultdict(list)
    for clinic in clinics:
        addr = clinic.get("address", "")
        if not addr:
            addr_groups["__no_address__"].append(clinic)
            continue
        key = _normalise_address(addr)
        addr_groups[key].append(clinic)

    result: list[dict] = []

    for addr_key, group in addr_groups.items():
        if addr_key == "__no_address__" or len(group) == 1:
            result.extend(group)
            continue

        merged = _merge_address_group(group)
        result.extend(merged)

    logger.info(
        "Dedup: %d clinics → %d after merging same-address listings",
        len(clinics),
        len(result),
    )
    return result


def _merge_address_group(group: list[dict]) -> list[dict]:
    """Merge listings that share an address."""

    # Classify each entry
    entries: list[dict] = []
    for clinic in group:
        name = clinic.get("name", "")
        is_person = _looks_like_person(name)
        doctor_name = _extract_doctor_from_name(name) if is_person else None

        # Also try extracting a doctor name from business names that contain
        # doctor references (e.g. "Dr. Rebecca Bork Family Dentistry")
        biz_doctor = None
        if not is_person and (_DR_PREFIX_RE.match(name) or _CREDENTIAL_RE.search(name)):
            biz_doctor = _extract_doctor_from_name(name)

        entries.append({
            "clinic": dict(clinic),  # shallow copy
            "is_person": is_person,
            "doctor_name": doctor_name,
            "biz_doctor": biz_doctor,
            "phone": (clinic.get("phone") or "").strip(),
        })

    # Sub-cluster by phone
    phone_clusters: dict[str, list[dict]] = defaultdict(list)
    no_phone: list[dict] = []
    for entry in entries:
        ph = entry["phone"]
        if ph:
            phone_clusters[ph].append(entry)
        else:
            no_phone.append(entry)

    # Merge within each phone cluster
    merged_clusters: list[dict] = []
    for phone, cluster in phone_clusters.items():
        merged = _merge_phone_cluster(cluster)
        merged_clusters.append(merged)

    # Also add no-phone entries as their own clusters
    for entry in no_phone:
        merged_clusters.append(entry["clinic"])

    # Cross-cluster merge: count distinct businesses across all clusters
    business_clusters = []
    person_only_clusters = []
    for mc in merged_clusters:
        name = mc.get("name", "")
        if _looks_like_person(name):
            person_only_clusters.append(mc)
        else:
            business_clusters.append(mc)

    if not person_only_clusters:
        return business_clusters or merged_clusters

    if not business_clusters:
        return person_only_clusters

    # Fold person-only clusters into the best-matching business.
    # Person listings at a shared address are always a doctor AT one of the
    # businesses — validated across 23 real address groups via web search.
    for pc in person_only_clusters:
        target = _best_business_match(pc, business_clusters)
        doc = _extract_doctor_from_name(pc.get("name", ""))
        doctors = []
        if doc:
            doctors.append(doc)
        existing = pc.get("head_dentist", "")
        if existing:
            doctors.append(existing)
        _add_doctors_to_clinic(target, doctors)
        _merge_missing_fields(target, pc)

    return business_clusters


def _best_business_match(person_clinic: dict, businesses: list[dict]) -> dict:
    """Pick the business a person-named listing most likely belongs to.

    Heuristics in priority order:
    1. Shared phone number prefix (first 10 digits)
    2. Shared website domain
    3. Richest-data business (fallback)
    """
    p_phone = _digits(person_clinic.get("phone", ""))
    p_domain = _domain(person_clinic.get("website", ""))

    best = None
    best_score = -1
    for biz in businesses:
        score = 0
        b_phone = _digits(biz.get("phone", ""))
        if p_phone and b_phone and p_phone[:10] == b_phone[:10]:
            score += 10
        b_domain = _domain(biz.get("website", ""))
        if p_domain and b_domain and p_domain == b_domain:
            score += 5
        score += _data_richness(biz)
        if score > best_score:
            best_score = score
            best = biz

    return best or businesses[0]


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def _domain(url: str) -> str:
    if not url:
        return ""
    url = re.sub(r"^https?://", "", url.lower()).strip("/")
    return url.split("/")[0].replace("www.", "")


def _merge_phone_cluster(cluster: list[dict]) -> dict:
    """Merge entries that share the same phone number into a single clinic."""
    if len(cluster) == 1:
        clinic = cluster[0]["clinic"]
        # Even a single entry can get a doctor name from its own listing name
        if cluster[0]["is_person"] and cluster[0]["doctor_name"]:
            _add_doctors_to_clinic(clinic, [cluster[0]["doctor_name"]])
        elif cluster[0]["biz_doctor"]:
            _add_doctors_to_clinic(clinic, [cluster[0]["biz_doctor"]])
        return clinic

    # Separate person entries from business entries
    businesses = [e for e in cluster if not e["is_person"]]
    persons = [e for e in cluster if e["is_person"]]

    # Pick the primary clinic: prefer a business-named entry
    if businesses:
        # Pick the one with the most data (website, hours, etc.)
        primary_entry = max(businesses, key=lambda e: _data_richness(e["clinic"]))
    else:
        # All person names — pick the first one, use it as the clinic
        primary_entry = cluster[0]

    primary = primary_entry["clinic"]

    # Collect doctor names from all entries
    doctors: list[str] = []

    for entry in cluster:
        if entry is primary_entry:
            # Extract doctor from primary even if it's a business name
            if entry["biz_doctor"]:
                doctors.append(entry["biz_doctor"])
            continue

        if entry["doctor_name"]:
            doctors.append(entry["doctor_name"])
        elif entry["biz_doctor"]:
            doctors.append(entry["biz_doctor"])

        # Grab head_dentist from merged entries
        existing = entry["clinic"].get("head_dentist", "")
        if existing and existing not in doctors:
            doctors.append(existing)

        # Merge any data the primary is missing
        _merge_missing_fields(primary, entry["clinic"])

    _add_doctors_to_clinic(primary, doctors)
    return primary


def _data_richness(clinic: dict) -> int:
    """Score how much useful data a clinic record has."""
    score = 0
    if clinic.get("website"):
        score += 2
    if clinic.get("phone"):
        score += 1
    if clinic.get("email"):
        score += 2
    if clinic.get("head_dentist"):
        score += 1
    if clinic.get("hours_by_day"):
        score += len(clinic["hours_by_day"])
    return score


def _merge_missing_fields(primary: dict, donor: dict) -> None:
    """Copy fields from donor into primary where primary is missing them."""
    for field in ("website", "email", "email_source", "hours_by_day"):
        if not primary.get(field) and donor.get(field):
            primary[field] = donor[field]


def _add_doctors_to_clinic(clinic: dict, doctor_names: list[str]) -> None:
    """Add extracted doctor names to a clinic's head_dentist field."""
    if not doctor_names:
        return

    # Deduplicate while preserving order
    existing = clinic.get("head_dentist", "")
    existing_parts = [p.strip() for p in existing.split(";") if p.strip()] if existing else []

    def _norm(n: str) -> str:
        """Normalise for comparison: strip credentials, Dr. prefix, middle
        initials, and periods so 'Paul J. Ezzo, DDS' matches 'Paul Ezzo'."""
        s = re.sub(r"^dr\.?\s+", "", n, flags=re.IGNORECASE)
        s = re.sub(r",?\s*(?:DDS|DMD|MD|DO|PhD|MS|FAGD|FICD|FACD|DABP|FACS)\b", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\b[A-Z]\.", "", s)  # strip middle initials
        return re.sub(r"\s+", " ", s).strip().lower()

    seen = {_norm(p) for p in existing_parts}

    for doc in doctor_names:
        normed = _norm(doc)
        if normed and normed not in seen:
            existing_parts.append(doc)
            seen.add(normed)

    if existing_parts:
        clinic["head_dentist"] = "; ".join(existing_parts)
        # Only set source if we actually added new doctors
        if not existing or len(existing_parts) > len(
            [p for p in existing.split(";") if p.strip()]
        ):
            clinic["staff_source"] = "Dedup"
