SIGNAL_LABELS = {
    "front_desk": "Front Desk",
    "phone": "Phone",
    "scheduling": "Scheduling",
    "insurance": "Insurance",
    "paperwork": "Paperwork",
}

PAIN_KEYWORDS = {
    "phone": [
        "phone", "call", "answer", "voicemail", "hold", "callback", "busy signal",
        "rang", "picked up", "no one answers", "couldn't reach", "never answer",
    ],
    "scheduling": [
        "schedule", "appointment", "wait", "booking", "rescheduled", "cancelled",
        "no show", "overbooked", "long wait", "waiting room",
    ],
    "front_desk": [
        "front desk", "receptionist", "staff", "rude", "unhelpful", "unprofessional",
        "disorganized", "chaotic", "confused",
    ],
    "insurance": [
        "insurance", "billing", "claim", "coverage", "verification", "denied",
        "charged", "incorrect bill", "overcharged",
    ],
    "paperwork": ["paperwork", "forms", "intake", "documents", "records", "fax"],
}


def _normalize_review(raw: dict) -> dict:
    if "review_text" in raw or "review_rating" in raw or "author_title" in raw:
        return {
            "text": raw.get("review_text") or "",
            "rating": raw.get("review_rating") or 0,
            "author": raw.get("author_title") or "",
        }
    return {
        "text": raw.get("text") or "",
        "rating": raw.get("rating") or 0,
        "author": raw.get("author_name") or "",
    }


def _find_highlights(text: str, cat: str) -> list[dict]:
    """Return non-overlapping highlight spans for all keywords of a category."""
    keywords = PAIN_KEYWORDS.get(cat, [])
    text_lower = text.lower()
    spans = []
    for kw in keywords:
        start = text_lower.find(kw)
        while start != -1:
            end = start + len(kw)
            # Skip if overlapping with an existing span
            if not any(s["start"] <= start < s["end"] or start <= s["start"] < end for s in spans):
                spans.append({"start": start, "end": end, "category": cat})
            start = text_lower.find(kw, start + 1)
    return spans


def scan_reviews(reviews: list[dict]) -> dict:
    normalized = [_normalize_review(r) for r in reviews]

    pain_count = 0
    triggered_categories = set()
    worst_snippet = ""
    worst_rating = 99
    matched_reviews = []

    for review in normalized:
        rating = review["rating"]
        full_text = review["text"]
        text_lower = full_text.lower()

        if rating > 3:
            continue

        matched_cats = []
        for cat, keywords in PAIN_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                matched_cats.append(cat)

        if matched_cats:
            pain_count += 1
            triggered_categories.update(matched_cats)
            if rating < worst_rating:
                worst_rating = rating
                worst_snippet = full_text[:200]

            # Build highlights across all matched categories
            all_highlights = []
            for cat in matched_cats:
                all_highlights.extend(_find_highlights(full_text, cat))

            matched_reviews.append({
                "text": full_text[:1000],
                "rating": rating,
                "matched_categories": matched_cats,
                "highlights": all_highlights,
            })

    cats = sorted(triggered_categories)
    evidence_parts = []
    if pain_count:
        evidence_parts.append(f"{pain_count} review(s) flagged: {', '.join(cats)}")
    if worst_snippet:
        evidence_parts.append(f'"{worst_snippet}"')

    return {
        "pain_review_count": pain_count,
        "pain_categories": cats,
        "worst_review_snippet": worst_snippet,
        "evidence_text": " | ".join(evidence_parts),
        "review_source": "places_sample",
        "matched_reviews": matched_reviews,
    }
