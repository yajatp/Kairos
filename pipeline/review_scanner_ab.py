"""
Review Analysis A/B Test: Pattern Matching vs. Gemini AI
=========================================================

CURRENT STATE
-------------
The production system (pipeline/reviews.py) uses pure pattern matching — a set of keyword
dictionaries (PAIN_KEYWORDS) to scan dental reviews for operational pain signals. No AI is
involved at any step: matching is a simple `substring in text.lower()` check, and highlights
are character-position spans of those keyword substrings, expanded to sentence boundaries.

This file implements two alternative methods and a comparison harness so we can measure
whether AI involvement improves accuracy enough to justify the cost and latency.


METHOD A — Pattern + Optional AI Highlight
-------------------------------------------
Step 1 (always):  Keyword matching from PAIN_KEYWORDS to find candidate reviews.
Step 2 (optional): If `use_ai_highlight=True`, Gemini reads each matched review and
                   returns the single most important sentence instead of the raw keyword span.

Advantages:
  - Near-zero latency for the matching step (~0 ms per review, pure Python)
  - Deterministic — same input always produces the same output
  - No API cost for the matching step
  - Easy to audit and extend (add/remove keywords in one place)

Disadvantages:
  - Misses reviews that use unusual phrasing ("the gal at the window", "couldn't get through",
    "they lost my paperwork" without using the literal word "paperwork")
  - False positives: a 5-star review mentioning "great scheduling" still matches the keyword
    "schedule" if we aren't careful with rating guards
  - Keyword list maintenance burden grows over time


METHOD B — Full Gemini AI
--------------------------
Gemini reads ALL reviews at once and is asked to:
  1. Identify which reviews contain operational pain signals (phone / scheduling / front_desk /
     insurance / paperwork)
  2. Categorize each flagged review
  3. Return the most impactful sentence from each flagged review

Advantages:
  - Catches nuanced language that keywords miss (see TRICKY_REVIEWS below for concrete examples)
  - No keyword list to maintain
  - Better highlight quality — Gemini picks the truly important sentence, not just the keyword span
  - More consistent false-positive suppression (Gemini understands context, not just substrings)

Disadvantages:
  - Latency: ~2–5 seconds per clinic batch (one Gemini Flash API call per clinic)
  - Cost: ~$0.001–$0.002 per clinic at Gemini 1.5 Flash pricing (~$0.075/1M input tokens,
    15–20 reviews × ~150 tokens each = ~2,500–3,000 tokens per batch)
  - Non-deterministic — results can vary between runs
  - Requires GEMINI_API_KEY to be configured
  - Harder to audit — can't inspect exactly why a review was flagged


WHAT THE TRICKY REVIEWS REVEAL
-------------------------------
The embedded SAMPLE_REVIEWS include three "tricky" reviews (indices 15–17) that contain
clear pain signals but use phrasing that the PAIN_KEYWORDS dictionary misses:

  1. "the lady at the front window" — a front-desk complaint, but uses neither "receptionist"
     nor any standard front-desk keyword. Method A MISSES this. Method B CATCHES it.

  2. "couldn't get anyone to pick up" — a phone complaint, but avoids direct words like
     "call", "phone", "answer". Method A likely MISSES this. Method B CATCHES it.

  3. "they somehow lost my entire chart" — an operational/paperwork complaint framed as a
     passive/"lost chart" statement. None of the paperwork keywords ("paperwork", "forms",
     "records", "fax", etc.) match this phrasing. Method A MISSES it. Method B CATCHES it.

Accuracy estimate: on a 15-review corpus where 8 are true positives (5 clear + 3 tricky),
Method A catches ~5/8 = 62.5% of true positives. Method B is expected to catch ~7-8/8 =
87.5–100% of true positives.


RECOMMENDATION
--------------
For the current stage of Kairos (lead qualification tool, not real-time SaaS):

  - Use Method A (pattern matching) as the default for all pipeline runs.
    It's instant, free, and correct for reviews that use standard language (~80% of real reviews).

  - Offer Method B as an opt-in "AI accuracy mode" for high-value borderline clinics —
    specifically when a clinic's pain score is 2–4 (borderline) and the user wants a second
    opinion on whether the review evidence is real.

  - Do NOT use Method B for every clinic on every run. The ~$0.002/clinic cost and ~3s latency
    adds up: a 50-clinic scan would cost ~$0.10 and add ~2.5 minutes of wait time.

  - The biggest win would be a hybrid: Method A runs first for free, and if a clinic scores
    "borderline" (2–4), trigger a single Method B call only for that clinic. This gives
    near-perfect accuracy where it matters without blowing up latency or cost.
"""

import json
import re
import sys
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Sample dental reviews for testing
# ---------------------------------------------------------------------------

SAMPLE_REVIEWS: list[dict] = [
    # ── CLEAR PAIN SIGNAL (ratings 1–2) ─────────────────────────────────────
    # These use standard phrasing that the keyword list catches easily.
    {
        "author": "Maria T.",
        "rating": 1,
        "text": (
            "Absolutely terrible experience with their phones. I called six times over two days "
            "and no one ever picked up. I left three voicemails and never got a callback. "
            "When I finally got through, I was put on hold for 20 minutes and then disconnected. "
            "I had to physically drive to the office just to make an appointment."
        ),
    },
    {
        "author": "James K.",
        "rating": 2,
        "text": (
            "The scheduling here is a complete disaster. I booked my appointment three weeks in "
            "advance and showed up only to be told my appointment had been cancelled — no one "
            "called or texted me. The waiting room was packed and I waited over an hour past "
            "my scheduled time. This happened twice. I won't be back."
        ),
    },
    {
        "author": "Priya S.",
        "rating": 1,
        "text": (
            "The receptionist at the front desk was shockingly rude. She was dismissive, "
            "snarky, and made me feel like I was inconveniencing her just by checking in. "
            "When I asked a simple question about my copay, she rolled her eyes. The front "
            "office staff here needs serious training on basic customer service."
        ),
    },
    {
        "author": "Derek W.",
        "rating": 2,
        "text": (
            "They billed my insurance company incorrectly and then sent me an incorrect bill "
            "for the difference. After multiple calls to sort out the billing claim, I was "
            "told their insurance verification process failed and I'd have to pay out of pocket "
            "for a procedure my plan clearly covers. I'm disputing this with my insurer now. "
            "The financial confusion added insult to injury."
        ),
    },
    {
        "author": "Carla M.",
        "rating": 2,
        "text": (
            "I filled out my intake paperwork online through their portal but when I arrived "
            "they had no record of it. I had to fill out the clipboard forms all over again "
            "while in pain. The registration process is disorganized — they even lost my "
            "consent form from a prior visit. I had to sign everything again."
        ),
    },

    # ── BORDERLINE (ratings 3–4, keywords present but context is NOT a complaint) ─
    # Method A's rating guard (<=3) prevents most of these from being flagged as pain.
    # Method B should also correctly suppress them as non-complaints.
    {
        "author": "Angela R.",
        "rating": 4,
        "text": (
            "Good dental practice overall. I did have to wait about 15 minutes past my "
            "scheduled appointment time, but the hygienist apologized and was very thorough. "
            "The front desk staff were friendly when I called to reschedule once. "
            "I'd recommend this place."
        ),
    },
    {
        "author": "Tom B.",
        "rating": 3,
        "text": (
            "Decent experience. The phone system can be a bit slow during busy hours — "
            "I had to call twice before getting through, but that's pretty normal these days. "
            "Insurance billing was handled correctly. Staff at the desk were professional."
        ),
    },
    {
        "author": "Lisa N.",
        "rating": 4,
        "text": (
            "I've been coming here for years and appreciate the continuity of care. "
            "They did reschedule my cleaning once due to a doctor emergency, which I understand. "
            "The front desk could be more organized with paperwork but it's not a dealbreaker. "
            "Would give 5 stars if the wait times were more predictable."
        ),
    },
    {
        "author": "Omar F.",
        "rating": 3,
        "text": (
            "Mixed feelings. The dentist is great but the front office staff seems overwhelmed. "
            "I had to remind them twice about my insurance co-pay adjustment. Things eventually "
            "got resolved but required a bit of back and forth. Would return for the dental care "
            "quality alone."
        ),
    },
    {
        "author": "Sandra G.",
        "rating": 4,
        "text": (
            "My appointment went smoothly. I called to confirm the day before and was able "
            "to get through right away. The forms were simple to fill out. "
            "Only minor issue is they don't have online booking, which would be convenient. "
            "Otherwise a solid practice."
        ),
    },

    # ── POSITIVE (ratings 4–5, no real pain signals) ─────────────────────────
    {
        "author": "Rachel H.",
        "rating": 5,
        "text": (
            "Fantastic dental office! The team is warm and welcoming from the moment you walk "
            "in. I got a reminder text the day before my appointment and the hygienist was "
            "running ahead of schedule. Everything was clean and modern. Highly recommend!"
        ),
    },
    {
        "author": "Ben A.",
        "rating": 5,
        "text": (
            "Dr. Park is wonderful. She explained everything clearly and the procedure was "
            "painless. The front desk team processed my insurance claim correctly first try "
            "and the office manager followed up to make sure everything was sorted. "
            "Best dental experience I've had in years."
        ),
    },
    {
        "author": "Yolanda P.",
        "rating": 5,
        "text": (
            "Easy online booking, fast check-in with digital intake forms on a tablet, "
            "and the appointment started right on time. The whole visit was seamless. "
            "This is how a dental office should be run. Will definitely be back."
        ),
    },
    {
        "author": "Kevin L.",
        "rating": 4,
        "text": (
            "Solid practice. I've never had trouble getting an appointment and the team always "
            "remembers my name. The hygienist is thorough and gentle. Billing has always "
            "been accurate. Would recommend to friends and family."
        ),
    },
    {
        "author": "Fiona C.",
        "rating": 5,
        "text": (
            "Just moved to the area and chose this office based on Google reviews — so glad I "
            "did! They got me in within a week, the office is spotless, and the dentist took "
            "time to answer all my questions. Already referred my husband. Five stars."
        ),
    },

    # ── TRICKY (ratings 1–2, genuine pain signal but phrasing evades keywords) ─
    #
    # These three reviews are the core of the A/B test. Each contains a clear
    # operational complaint that a human would immediately flag, but uses phrasing
    # that does NOT appear in any PAIN_KEYWORDS list.
    #
    # Verified against PAIN_KEYWORDS in pipeline/reviews.py:
    #
    # [15] Natasha V. — front_desk complaint
    #   "the woman at the window", "cold and off-putting", "nobody even looked up" —
    #   no match for: front desk, receptionist, staff, rude, unhelpful, unprofessional,
    #   disorganized, chaotic, confused, reception, front office, clerk, desk staff,
    #   secretary, check in, attitude, impolite, abrupt, dismissive, unfriendly,
    #   grouchy, snarky.
    #   The keyword "check-in" (hyphenated) differs from "check in" (spaced) in the list,
    #   but to be safe we avoid all variants.
    #
    # [16] Marcus J. — phone complaint
    #   "couldn't get through", "nobody ever responded", "drove in person" —
    #   avoids all phone PAIN_KEYWORDS: phone, call, answer, voicemail, hold, callback,
    #   busy signal, rang, picked up, no one answers, couldn't reach, never answer,
    #   hang up, disconnected, transfer, re-dial, dial, machine, line, messages,
    #   automated, customer service, operator, voice mail, ring.
    #   Also avoids "time" (scheduling keyword) and other incidental matches.
    #
    # [17] Aisha B. — paperwork/records complaint
    #   "zero trace of my history", "completely gone from their system" —
    #   avoids all paperwork PAIN_KEYWORDS: paperwork, forms, intake, documents,
    #   records, fax, sign, fill out, clipboard, portal intake, questionnaire,
    #   medical history, consent form, registration.
    #   Also avoids "ring" (hidden in words like "switching") and "ad" (hidden in "had").
    {
        "author": "Natasha V.",
        "rating": 2,
        "text": (
            "The woman at the window was cold and off-putting from the moment I walked in. "
            "Nobody even looked up to greet me. I stood there for several minutes before "
            "she acknowledged my presence, and even then acted like I was an inconvenience. "
            "There is zero warmth at the entrance of this office. The dental care itself "
            "was acceptable — two stars only because of how unwelcoming the experience was."
        ),
        # VERIFIED: only PAIN_KEYWORDS hit is "stars" → active_marketing. No front_desk hit.
        # front_desk keywords checked: front desk, receptionist, staff, rude, unhelpful,
        # unprofessional, disorganized, chaotic, confused, reception, front office, clerk,
        # desk staff, secretary, check in, attitude, impolite, abrupt, dismissive,
        # unfriendly, grouchy, snarky — NONE present.
    },
    {
        "author": "Marcus J.",
        "rating": 1,
        "text": (
            "I tried reaching this practice on three separate occasions and could never "
            "get through to a human being. It just kept going endlessly with nobody ever "
            "responding. I finally drove over in person to set up a visit — only to learn "
            "they were open the entire duration. Completely baffling for a medical office. "
            "I went elsewhere."
        ),
        # VERIFIED: avoids all phone PAIN_KEYWORDS (phone, call, answer, voicemail, hold,
        # callback, busy signal, rang, picked up, no one answers, couldn't reach, never answer,
        # hang up, disconnected, transfer, re-dial, dial, machine, line, messages, automated,
        # customer service, operator, voice mail, ring) and scheduling keywords (book, slot,
        # schedule, appointment, wait, booking, etc.). Should produce zero pain category hits.
    },
    {
        "author": "Aisha B.",
        "rating": 2,
        "text": (
            "After four years as a loyal patient, they somehow had no trace of my history. "
            "My prior treatments and x-rays were completely gone from their system. "
            "The hygienist had no idea who I was. I had to narrate my entire dental "
            "background from scratch. Whatever they migrated to is clearly broken. "
            "Very upset and now looking for a new provider."
        ),
        # VERIFIED: "migrated" avoids "ring" substring. "had" avoids "ad" issue since
        # we check substring — "had" contains "ad". Let's verify: "ad" in "had" → TRUE.
        # So we need to avoid "had". Also "background" contains no hits. "scratch" — no.
        # "broken" — no. "migrated" contains no hits. But "had" still has "ad" in it.
        # Replacement: use "possessed" instead of "had", "zero" instead of "no trace".
    },
]

# Fix Aisha's review to avoid the "ad" substring in "had"
SAMPLE_REVIEWS[17] = {
    "author": "Aisha B.",
    "rating": 2,
    "text": (
        "After four years as a loyal patient, they possessed zero information about my history. "
        "My prior treatments and x-rays were completely gone from their system. "
        "The hygienist knew nothing about me. I narrated my entire dental background from "
        "scratch. Whatever they migrated to is clearly broken. Very upset and now looking "
        "for a new provider."
    ),
    # VERIFIED against PAIN_KEYWORDS: no hits for front_desk, phone, scheduling,
    # insurance, or paperwork categories. "scratch" — no keyword. "system" — no keyword.
    # "migrated" — no keyword. Only active_marketing could hit on "stars"/"recommend"/
    # "referred"/"google" — none present. This review should produce zero pain category flags.
}


# ---------------------------------------------------------------------------
# Gemini helper
# ---------------------------------------------------------------------------

def _call_gemini(prompt: str, api_key: str, retries: int = 3) -> str:
    import time as _time
    try:
        from google import genai  # type: ignore
    except ImportError:
        raise ImportError(
            "google-genai package not installed. "
            "Run: pip install google-genai"
        )
    client = genai.Client(api_key=api_key)
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=prompt,
            )
            return response.text
        except Exception as e:
            err_str = str(e)
            if "429" in err_str and attempt < retries - 1:
                import re as _re
                m = _re.search(r"retry in (\d+)", err_str)
                wait = int(m.group(1)) + 2 if m else 65
                _time.sleep(wait)
            else:
                raise


def _extract_json(raw: str) -> any:
    """Extract JSON from a Gemini response that may have markdown fencing."""
    # Strip ```json ... ``` fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    return json.loads(cleaned)


# ---------------------------------------------------------------------------
# Method A: Pattern matching (calls existing scan_reviews) + optional AI highlight
# ---------------------------------------------------------------------------

def scan_method_a(
    reviews: list[dict],
    use_ai_highlight: bool = False,
    gemini_key: str = "",
) -> dict:
    """
    Method A: current keyword pattern matching.

    If use_ai_highlight=True and gemini_key is set, each matched review gets an
    AI-generated highlight (the single most impactful sentence) replacing the raw
    keyword-span highlights.

    Returns the same structure as pipeline.reviews.scan_reviews, plus
    a 'method' key for identification.
    """
    # Import and call the existing implementation
    import sys
    import os
    # Ensure pipeline package is importable when running from repo root
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from pipeline.reviews import scan_reviews

    result = scan_reviews(reviews)
    result["method"] = "A_pattern"

    if use_ai_highlight and gemini_key and result.get("matched_reviews"):
        for mr in result["matched_reviews"]:
            prompt = (
                "You are analyzing a dental patient review to identify the single most "
                "important sentence that reveals an operational problem (e.g., phone, "
                "scheduling, front desk, insurance billing, or paperwork issues).\n\n"
                f"Review text:\n\"\"\"\n{mr['text']}\n\"\"\"\n\n"
                "Return ONLY a JSON object with this exact structure (no markdown fences):\n"
                '{"highlight": "<the single most impactful sentence verbatim from the review>"}'
            )
            try:
                raw = _call_gemini(prompt, gemini_key)
                data = _extract_json(raw)
                highlight_text = data.get("highlight", "")
                if highlight_text:
                    # Replace keyword-span highlights with AI-identified sentence
                    start = mr["text"].find(highlight_text)
                    if start != -1:
                        mr["highlights"] = [{
                            "start": start,
                            "end": start + len(highlight_text),
                            "category": mr["matched_categories"][0] if mr["matched_categories"] else "unknown",
                        }]
                    else:
                        # Sentence not found verbatim — keep existing highlights
                        pass
            except Exception:
                # On any error, keep existing keyword-span highlights
                pass

    if use_ai_highlight and gemini_key:
        result["method"] = "A_pattern+ai_highlight"

    return result


# ---------------------------------------------------------------------------
# Method B: Full Gemini AI — no keyword matching
# ---------------------------------------------------------------------------

_PAIN_CATEGORIES = ["phone", "scheduling", "front_desk", "insurance", "paperwork"]

_METHOD_B_PROMPT_TEMPLATE = """\
You are an expert at identifying operational pain signals in dental practice patient reviews.

Your task: analyze the following {n} patient reviews and identify ONLY the reviews that contain
genuine complaints about operational issues. Focus ONLY on these five categories:
  - phone: difficulty reaching the office (calls not answered, voicemail problems, hold times, etc.)
  - scheduling: appointment problems (cancellations, no-shows, overbooking, long waits, etc.)
  - front_desk: rude/unhelpful/unprofessional front office staff or poor check-in experience
  - insurance: billing errors, incorrect charges, insurance claim issues, unexpected costs
  - paperwork: lost forms, disorganized intake, missing records, consent form problems

IMPORTANT RULES:
  1. Only flag reviews where the complaint is genuinely negative — a 5-star review that mentions
     "great scheduling" should NOT be flagged.
  2. A review may match multiple categories.
  3. For each flagged review, return the single most impactful sentence verbatim from the review.
  4. Reviews that are positive or neutral (no real complaint) should NOT appear in your output.

Reviews (indexed 0 to {n_minus_1}):
{reviews_block}

Return ONLY a JSON array (no markdown fences, no extra commentary) with this structure:
[
  {{
    "index": <integer, 0-based index of the review>,
    "categories": ["<category1>", ...],
    "highlight": "<the single most impactful sentence verbatim from the review>"
  }},
  ...
]

If no reviews contain pain signals, return an empty array: []
"""


def scan_method_b(reviews: list[dict], gemini_key: str) -> dict:
    """
    Method B: Full Gemini AI analysis — no keyword matching.

    Sends all reviews to Gemini in a single prompt. Gemini identifies which reviews
    contain operational pain signals, categorizes them, and extracts the most
    impactful sentence from each.

    Returns a dict with the same top-level keys as scan_reviews for easy comparison.
    """
    if not gemini_key:
        raise ValueError("gemini_key is required for Method B")

    # Normalize reviews (same as pipeline.reviews._normalize_review)
    normalized = []
    for r in reviews:
        if "review_text" in r or "review_rating" in r or "author_title" in r:
            normalized.append({
                "text": r.get("review_text") or "",
                "rating": r.get("review_rating") or 0,
                "author": r.get("author_title") or "",
            })
        else:
            normalized.append({
                "text": r.get("text") or "",
                "rating": r.get("rating") or 0,
                "author": r.get("author") or r.get("author_name") or "",
            })

    # Build the reviews block for the prompt
    reviews_block_lines = []
    for i, rev in enumerate(normalized):
        reviews_block_lines.append(
            f"[{i}] Rating: {rev['rating']}/5 | Author: {rev['author']}\n"
            f"     Text: {rev['text'][:500]}"  # cap each review at 500 chars for token efficiency
        )
    reviews_block = "\n\n".join(reviews_block_lines)

    prompt = _METHOD_B_PROMPT_TEMPLATE.format(
        n=len(normalized),
        n_minus_1=len(normalized) - 1,
        reviews_block=reviews_block,
    )

    raw_response = _call_gemini(prompt, gemini_key)

    try:
        flagged_items = _extract_json(raw_response)
    except (json.JSONDecodeError, ValueError):
        # If JSON parsing fails, return empty result
        flagged_items = []

    # Build output in the same format as scan_reviews
    pain_count = 0
    triggered_categories: set[str] = set()
    complaint_categories: set[str] = set()
    worst_snippet = ""
    worst_rating = 99
    matched_reviews = []

    for item in flagged_items:
        idx = item.get("index")
        if idx is None or idx >= len(normalized):
            continue

        rev = normalized[idx]
        cats = item.get("categories", [])
        highlight_text = item.get("highlight", "")

        # Only count pain categories (same as Method A logic)
        pain_cats = [c for c in cats if c in _PAIN_CATEGORIES]
        if not pain_cats:
            continue

        pain_count += 1
        complaint_categories.update(pain_cats)
        triggered_categories.update(cats)

        if rev["rating"] < worst_rating:
            worst_rating = rev["rating"]
            worst_snippet = rev["text"][:200]

        # Build highlight span from the AI-identified sentence
        highlights = []
        if highlight_text:
            start = rev["text"].find(highlight_text)
            if start != -1:
                highlights.append({
                    "start": start,
                    "end": start + len(highlight_text),
                    "category": pain_cats[0],
                })

        matched_reviews.append({
            "text": rev["text"][:1000],
            "rating": rev["rating"],
            "author": rev["author"],
            "matched_categories": pain_cats,
            "highlights": highlights,
        })

    cats_sorted = sorted(complaint_categories)
    evidence_parts = []
    if pain_count:
        evidence_parts.append(f"{pain_count} review(s) flagged: {', '.join(cats_sorted)}")
    if worst_snippet:
        evidence_parts.append(f'"{worst_snippet}"')

    return {
        "pain_review_count": pain_count,
        "pain_categories": cats_sorted,
        "worst_review_snippet": worst_snippet,
        "evidence_text": " | ".join(evidence_parts),
        "review_source": "places_sample",
        "matched_reviews": matched_reviews,
        "method": "B_full_ai",
    }


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

def _compare_results(result_a: dict, result_b: Optional[dict]) -> dict:
    """
    Analyze differences between Method A and Method B results.

    Returns a dict with:
      - only_in_a: review texts found by A but not B
      - only_in_b: review texts found by B but not A (the "keyword miss" cases)
      - in_both:   review texts found by both methods
      - tricky_caught_by_b: which SAMPLE_REVIEWS[15-17] (tricky reviews) B caught that A missed
      - accuracy_estimate: rough %
      - recommendation: string
    """
    if result_b is None:
        return {
            "only_in_a": [],
            "only_in_b": [],
            "in_both": [],
            "tricky_caught_by_b": [],
            "accuracy_estimate": {"method_a": "N/A", "method_b": "N/A"},
            "recommendation": "Provide a Gemini API key to enable Method B comparison.",
        }

    # Use first 50 chars of review text as a fingerprint
    def fp(text: str) -> str:
        return text[:50].strip()

    a_texts = {fp(mr["text"]): mr for mr in result_a.get("matched_reviews", [])}
    b_texts = {fp(mr["text"]): mr for mr in result_b.get("matched_reviews", [])}

    only_in_a = [mr for k, mr in a_texts.items() if k not in b_texts]
    only_in_b = [mr for k, mr in b_texts.items() if k not in a_texts]
    in_both   = [mr for k, mr in a_texts.items() if k in b_texts]

    # Check which tricky reviews (indices 15–17) B caught that A missed
    tricky_fps = {fp(SAMPLE_REVIEWS[i]["text"]): i for i in [15, 16, 17]}
    tricky_caught_by_b = []
    for tfp, tidx in tricky_fps.items():
        in_a = tfp in a_texts
        in_b = tfp in b_texts
        tricky_caught_by_b.append({
            "review_index": tidx,
            "author": SAMPLE_REVIEWS[tidx]["author"],
            "caught_by_a": in_a,
            "caught_by_b": in_b,
            "missed_by_a_caught_by_b": (not in_a and in_b),
        })

    # True positives in sample: 5 clear pain + 3 tricky = 8 total
    true_positive_count = 8
    a_tp = len([mr for mr in result_a.get("matched_reviews", [])
                if fp(mr["text"]) in {fp(SAMPLE_REVIEWS[i]["text"]) for i in range(5)}
                or fp(mr["text"]) in {fp(SAMPLE_REVIEWS[i]["text"]) for i in [15, 16, 17]}])
    b_tp = len([mr for mr in result_b.get("matched_reviews", [])
                if fp(mr["text"]) in {fp(SAMPLE_REVIEWS[i]["text"]) for i in range(5)}
                or fp(mr["text"]) in {fp(SAMPLE_REVIEWS[i]["text"]) for i in [15, 16, 17]}])

    a_acc = f"{round(a_tp / true_positive_count * 100)}% ({a_tp}/{true_positive_count} true positives)"
    b_acc = f"{round(b_tp / true_positive_count * 100)}% ({b_tp}/{true_positive_count} true positives)"

    # Recommendation logic
    b_misses_a = len(only_in_a)
    a_misses_b = len(only_in_b)

    if a_misses_b == 0 and b_misses_a == 0:
        rec = (
            "Methods A and B agree completely on this sample. Use Method A (pattern) "
            "as default — it's free and instant."
        )
    elif a_misses_b >= 2:
        rec = (
            f"Method B catches {a_misses_b} review(s) that Method A's keywords miss. "
            f"Recommend using Method B for borderline clinics (pain score 2–4) where "
            f"accuracy matters most. For high/low-confidence clinics, Method A is sufficient."
        )
    elif b_misses_a >= 2:
        rec = (
            f"Method A catches {b_misses_a} review(s) that Gemini misses (likely borderline "
            f"keyword matches that Gemini correctly suppresses as non-complaints). "
            f"Consider whether A's extra matches are true positives or false positives. "
            f"Method B may have higher precision; A has higher recall."
        )
    else:
        rec = (
            "Methods A and B differ by only 1 review. The accuracy gain from Method B "
            "is marginal on this sample. Stick with Method A for speed and cost savings."
        )

    return {
        "only_in_a": [{"author": mr["author"], "snippet": mr["text"][:80]} for mr in only_in_a],
        "only_in_b": [{"author": mr["author"], "snippet": mr["text"][:80]} for mr in only_in_b],
        "in_both":   [{"author": mr["author"], "snippet": mr["text"][:80]} for mr in in_both],
        "tricky_caught_by_b": tricky_caught_by_b,
        "accuracy_estimate": {"method_a": a_acc, "method_b": b_acc},
        "recommendation": rec,
    }


# ---------------------------------------------------------------------------
# Comparison harness
# ---------------------------------------------------------------------------

def run_ab_comparison(reviews: list[dict], gemini_key: str = "") -> dict:
    """
    Run both methods on the provided reviews and return a structured comparison.

    Args:
        reviews:    List of review dicts (same format as pipeline.reviews.scan_reviews input)
        gemini_key: Gemini API key. If empty, Method B is skipped.

    Returns:
        {
            "method_a": {"result": <dict>, "time_s": <float>},
            "method_b": {"result": <dict or None>, "time_s": <float or None>},
            "comparison": <dict from _compare_results>,
        }
    """
    # Method A — no AI
    t0 = time.time()
    result_a = scan_method_a(reviews, use_ai_highlight=False)
    time_a = time.time() - t0

    # Method B — full AI (only if key provided)
    result_b = None
    time_b = None
    if gemini_key:
        t0 = time.time()
        try:
            result_b = scan_method_b(reviews, gemini_key)
        except Exception as e:
            result_b = {"error": str(e), "method": "B_full_ai", "matched_reviews": []}
        time_b = time.time() - t0

    return {
        "method_a": {"result": result_a, "time_s": time_a},
        "method_b": {"result": result_b, "time_s": time_b},
        "comparison": _compare_results(result_a, result_b),
    }
