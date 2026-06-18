from __future__ import annotations

import time
import requests
import logging

logger = logging.getLogger(__name__)

BASE_URL = "https://maps.googleapis.com/maps/api"


def geocode(location: str, api_key: str) -> tuple[float, float]:
    resp = requests.get(
        f"{BASE_URL}/geocode/json",
        params={"address": location, "key": api_key},
        timeout=10,
    )
    data = resp.json()
    if data.get("status") != "OK" or not data.get("results"):
        raise ValueError(f"Location not found: '{location}'. Try a different city name or ZIP code.")
    loc = data["results"][0]["geometry"]["location"]
    return loc["lat"], loc["lng"]


def search_clinics(lat: float, lng: float, radius_miles: int, max_results: int, api_key: str) -> list[dict]:
    radius_meters = int(radius_miles * 1609.34)
    results = []
    params = {
        "location": f"{lat},{lng}",
        "radius": radius_meters,
        "type": "dentist",
        "key": api_key,
    }
    page = 0
    next_page_token = None

    while page < 3 and len(results) < max_results:
        if next_page_token:
            params = {"pagetoken": next_page_token, "key": api_key}
            time.sleep(2)

        resp = requests.get(f"{BASE_URL}/place/nearbysearch/json", params=params, timeout=10)
        data = resp.json()

        for place in data.get("results", []):
            if place.get("business_status") != "OPERATIONAL":
                continue
            results.append({
                "place_id": place["place_id"],
                "name": place.get("name", ""),
                "vicinity": place.get("vicinity", ""),
            })
            if len(results) >= max_results:
                break

        next_page_token = data.get("next_page_token")
        if not next_page_token:
            break
        page += 1

    return results


def get_clinic_details(place_id: str, api_key: str) -> dict:
    try:
        resp = requests.get(
            f"{BASE_URL}/place/details/json",
            params={
                "place_id": place_id,
                "fields": "name,formatted_phone_number,website,formatted_address,opening_hours,reviews,rating,user_ratings_total,business_status,types",
                "key": api_key,
            },
            timeout=10,
        )
        time.sleep(0.3)
        data = resp.json()
        if data.get("status") != "OK":
            logger.warning(f"Place details failed for {place_id}: {data.get('status')}")
            return {}
        result = data.get("result", {})
        hours_summary = "Hours not available"
        opening_hours = result.get("opening_hours")
        if opening_hours and opening_hours.get("weekday_text"):
            hours_summary = "; ".join(opening_hours["weekday_text"])
        result["hours_summary"] = hours_summary
        return result
    except Exception as e:
        logger.warning(f"Error fetching details for {place_id}: {e}")
        return {}
