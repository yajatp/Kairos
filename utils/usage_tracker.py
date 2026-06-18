import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

MONTHLY_BUDGET = 450
TRACKER_FILE = "outscraper_usage.json"


def _current_year_month() -> str:
    return datetime.now().strftime("%Y-%m")


def _load_state() -> dict:
    current_ym = _current_year_month()
    try:
        with open(TRACKER_FILE, "r") as f:
            state = json.load(f)
        if state.get("year_month") != current_ym:
            state = {"year_month": current_ym, "reviews_used": 0}
        return state
    except FileNotFoundError:
        return {"year_month": current_ym, "reviews_used": 0}
    except Exception as e:
        logger.warning(f"Could not read usage tracker: {e} — starting fresh")
        return {"year_month": current_ym, "reviews_used": 0}


def get_remaining_budget() -> int:
    state = _load_state()
    remaining = MONTHLY_BUDGET - state.get("reviews_used", 0)
    return max(0, remaining)


def record_usage(reviews_pulled: int) -> None:
    state = _load_state()
    state["reviews_used"] = state.get("reviews_used", 0) + reviews_pulled
    try:
        with open(TRACKER_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logger.warning(f"Could not write usage tracker: {e}")
