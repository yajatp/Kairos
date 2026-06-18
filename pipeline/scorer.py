from __future__ import annotations


def detect_extended_hours(opening_hours: dict | None) -> bool:
    if not opening_hours:
        return False
    for period in opening_hours.get("periods", []):
        close = period.get("close", {})
        open_day = period.get("open", {})
        if close.get("time", "0000") > "1900":
            return True
        if open_day.get("day") in [0, 6]:
            return True
    return False


def infer_specialty(name: str, types: list[str]) -> str:
    combined = (name + " " + " ".join(types)).lower()
    if "ortho" in combined:
        return "Orthodontic"
    if any(k in combined for k in ["pediatric", "pedo", "kids", "children"]):
        return "Pediatric"
    if "endo" in combined:
        return "Endodontic"
    if any(k in combined for k in ["oral surgery", "oral surgeon"]):
        return "Oral Surgery"
    if "perio" in combined:
        return "Periodontic"
    return "General"


def calculate_pain_score(clinic_data: dict) -> tuple[int, list[str]]:
    score = 0
    signals = []

    if clinic_data.get("has_hiring_signal"):
        score += 4
        signals.append("Hiring: front-desk/admin role")

    if clinic_data.get("pain_review_count", 0) >= 1:
        score += 2
        cats = ", ".join(clinic_data.get("pain_categories", []))
        source_note = " [deep scan]" if clinic_data.get("review_source") == "outscraper_deep" else ""
        signals.append(f"Reviews: admin complaints ({cats}){source_note}")

    num_locs = clinic_data.get("num_locations", 1)
    if num_locs > 1:
        score += 2
        signals.append(f"Multi-location ({num_locs} locations)")

    if clinic_data.get("extended_hours"):
        score += 1
        signals.append("Extended hours (late/weekends)")

    if clinic_data.get("uses_digital_tools") or clinic_data.get("has_online_booking"):
        score += 1
        tools = clinic_data.get("detected_tools", [])
        signals.append(f"Digital tools: {', '.join(tools[:3]) if tools else 'online booking detected'}")

    rating = clinic_data.get("rating", 0)
    total_reviews = clinic_data.get("user_ratings_total", 0)
    if total_reviews >= 75 and rating >= 4.0:
        score += 1
        signals.append(f"Active marketing ({total_reviews} reviews, {rating}★)")

    return score, signals


def is_borderline(score: int) -> bool:
    return 2 <= score <= 3


def generate_outreach_angle(signals: list[str], clinic_name: str, specialty: str = "General") -> str:
    spec_note = f"{specialty.lower()} " if specialty != "General" else ""

    if any("Hiring" in s for s in signals):
        return (
            f"{clinic_name} is actively hiring front-desk staff — a strong signal of admin overload. "
            f"Kairos can absorb that workload without the added headcount cost or training time."
        )
    elif any("Reviews" in s for s in signals):
        return (
            f"Patients are leaving reviews about phone and scheduling issues at {clinic_name}. "
            f"Kairos handles inbound calls, scheduling, and follow-up automatically — stopping those complaints before they hit Google."
        )
    elif any("Multi-location" in s for s in signals):
        return (
            f"{clinic_name} runs multiple locations, which means front-desk coordination overhead compounds quickly. "
            f"Kairos centralizes intake, scheduling, and insurance verification across all locations."
        )
    elif any("Extended hours" in s for s in signals):
        return (
            f"{clinic_name} is open late or on weekends — hours when front-desk staff aren't always available. "
            f"Kairos provides 24/7 inbound call coverage and after-hours booking."
        )
    elif any("Digital tools" in s for s in signals):
        return (
            f"{clinic_name} already uses digital tools, which means they're open to workflow automation. "
            f"Kairos integrates natively with 10+ PMS systems and can be live in 7 days."
        )
    else:
        return (
            f"{clinic_name} is a {spec_note}practice in a competitive market. "
            f"Kairos can help them capture more patients through 24/7 inbound call handling and automated follow-up."
        )
