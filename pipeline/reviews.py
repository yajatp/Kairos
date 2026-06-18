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


def scan_reviews(reviews: list[dict]) -> dict:
    normalized = [_normalize_review(r) for r in reviews]

    pain_count = 0
    triggered_categories = set()
    worst_snippet = ""
    worst_rating = 99

    for review in normalized:
        rating = review["rating"]
        text = review["text"].lower()

        if rating > 3:
            continue

        matched_cats = []
        for cat, keywords in PAIN_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                matched_cats.append(cat)

        if matched_cats:
            pain_count += 1
            triggered_categories.update(matched_cats)
            if rating < worst_rating:
                worst_rating = rating
                worst_snippet = review["text"][:200]

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
    }
