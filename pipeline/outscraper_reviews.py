import logging
import requests

logger = logging.getLogger(__name__)

OUTSCRAPER_ENDPOINT = "https://api.app.outscraper.com/maps/reviews-v2"


def fetch_deep_reviews(place_id: str, api_key: str, reviews_limit: int = 10) -> list[dict]:
    try:
        resp = requests.get(
            OUTSCRAPER_ENDPOINT,
            params={
                "query": place_id,
                "reviewsLimit": reviews_limit,
                "sort": "lowest_rating",
                "language": "en",
                "async": "false",
            },
            headers={"X-API-KEY": api_key},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(f"Outscraper returned {resp.status_code} for place {place_id}")
            return []

        data = resp.json()
        if not data:
            return []

        reviews = []
        items = data if isinstance(data, list) else data.get("data", [])
        for item in items:
            raw_reviews = item.get("reviews_data") or item.get("reviews") or []
            for r in raw_reviews:
                text = r.get("review_text") or r.get("text") or ""
                rating = r.get("review_rating") or r.get("rating") or 0
                author = r.get("author_title") or r.get("author_name") or ""
                reviews.append({"text": text, "rating": rating, "author": author})

        return reviews
    except Exception as e:
        logger.warning(f"Outscraper error for place {place_id}: {e}")
        return []
