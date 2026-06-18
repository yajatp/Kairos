# Kairos Health Lead Engine

A Streamlit web app that finds dental clinics in any US city, analyzes them for "pain signals" (indicators of front-desk workflow problems), scores them, and outputs a prioritized lead table you can download as CSV. Built for Kairos Health to identify potential customers who would benefit from dental AI front-desk automation.

---

## Setup

1. Clone this repo: `git clone <repo-url> && cd kairos-lead-engine`
2. Install dependencies: `pip install -r requirements.txt`
3. Copy the example env file: `cp .env.example .env`
4. Fill in your API keys in `.env` (see API Key Setup below)

---

## API Key Setup

| Key | Where to Register |
|-----|-------------------|
| `GOOGLE_PLACES_API_KEY` | https://console.cloud.google.com — enable "Places API" under your project |
| `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | https://developer.adzuna.com — register for a free developer account |
| `OUTSCRAPER_API_KEY` | https://outscraper.com — register for a free account (~500 review pulls/month) |

The app runs without Adzuna or Outscraper keys — those signals are simply skipped. The Google Places key is required.

---

## Running Locally

```bash
streamlit run app.py
```

The app opens at http://localhost:8501.

---

## Deploying to Streamlit Cloud

1. Push this repo to GitHub
2. Go to https://share.streamlit.io and connect your repo
3. Under **Advanced settings → Secrets**, add your environment variables in TOML format:

```toml
GOOGLE_PLACES_API_KEY = "your_key_here"
ADZUNA_APP_ID = "your_id_here"
ADZUNA_APP_KEY = "your_key_here"
OUTSCRAPER_API_KEY = "your_key_here"
```

---

## How Pain Scoring Works

Each clinic is scored on a 0–9 point scale based on signals of front-desk overload:

| Signal | Points | How Detected |
|--------|--------|--------------|
| Hiring for front-desk/admin | +4 | Adzuna job board cross-reference |
| Bad reviews mentioning admin pain | +2 | Google Places sample (5 reviews) or Outscraper deep scan (10 reviews) for borderline clinics |
| Multiple locations | +2 | Manual (default 1; override in sheet) |
| Extended hours (late/weekends) | +1 | Google Places opening hours |
| Online booking or digital tools | +1 | Website text scan |
| Active marketing (75+ reviews, 4★+) | +1 | Google Places rating data |

**Priority thresholds:**
- **6+** = High priority, call first
- **4–5** = Strong signal, include in first batch
- **2–3** = Moderate — eligible for deep review enrichment if Outscraper budget allows
- **0–1** = Low priority, deprioritize

### Two-Pass Scoring Architecture

The app uses a two-pass approach to stay within Outscraper's free tier:

1. **Pass 1 (always runs, free):** Every clinic is scored using Google Places data (5 reviews max), Adzuna hiring signal, and website scan.
2. **Pass 2 (conditional):** Clinics that land in the "borderline" band (score 2–3) — where deeper review evidence could plausibly change their priority tier — are sent to Outscraper for a 10-review deep scan (sorted by lowest rating). Their score is then recalculated with that richer data.

Clinics already scoring 4+ (strong signal) or 0–1 (no signal) skip the Outscraper call — spending budget on them doesn't change their bucket.

A local file (`outscraper_usage.json`) tracks monthly usage against a 450-review budget cap (safely below Outscraper's ~500 free-tier limit). The remaining budget is shown live in the sidebar.

---

## Compliance & Data Source Notes

**Adzuna (hiring signal):** Adzuna's Terms of Service permit unrestricted use only for publishing ad listings, publishing salary estimates, or personal research. Any other use by a commercial organization — which this is — is permitted for a 14-day evaluation trial only; continued use requires a license agreement with Adzuna. The default free access limits (25/min, 250/day, 1000/week, 2500/month) are real and confirmed, but the volume was never the constraint — the use-case classification is.

**Action required:** Before scaling this tool beyond initial testing, reach out to Adzuna to discuss a commercial license. This is a business decision — the app surfaces the issue here and in the sidebar rather than making the decision silently.

**Outscraper (deep review signal):** Outscraper's free tier provides roughly 500 review pulls per month. The app enforces a 450-review monthly cap via a local usage tracker and only calls Outscraper for borderline-scoring clinics. Once the monthly budget is exhausted, the app falls back gracefully to the Google Places 5-review sample and labels affected rows accordingly.

**Google Places reviews:** Google's Places API caps reviews at 5 per place (the 5 most "relevant" by their algorithm). This is an API design limitation that has been unaddressed since 2015. Outscraper exists to go deeper for clinics where it matters.

---

## Limitations

- **Google Places returns only 5 reviews per clinic** by default — the deep scan via Outscraper supplements this for borderline-scoring clinics only, not all clinics.
- **Hiring signal depends on Adzuna coverage** — Adzuna may not index all local job boards. The website hiring-banner scan is a free supplementary corroborating signal when present.
- **Adzuna commercial use** is currently under their 14-day evaluation-use terms — see Compliance section above.
- **Multi-location count defaults to 1** — the app cannot automatically detect all locations for a given practice. The "Number of Locations" column should be manually verified and updated in the downloaded CSV.
- **Website scans have a 4-second timeout** — slow or blocked websites will return no digital tool or booking data.
