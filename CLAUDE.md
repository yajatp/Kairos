# Kairos — Developer Notes for Claude

## Hard rules

- **No emojis anywhere.** Never use emoji characters (📄 📊 📱 🎯 🔄 ✓ ✗ etc.) in any Python file, HTML string, button label, markdown string, or comment. Use Streamlit Material icons (`:material/download:`, `:material/table_chart:`, `:material/phone:`, `:material/refresh:`, etc.) or plain text instead.
- **No comments explaining what code does.** Only add a comment when the WHY is non-obvious.
- **No new files unless required.** Prefer editing existing files.

## ⚠ Making the user actually SEE your changes (READ THIS BEFORE CLAIMING A FIX WORKS)

This app runs on **Streamlit Community Cloud** (the "Manage app" pill bottom-right and "Deploy" button top-right in the UI are the tells). The user almost always views the **deployed cloud URL**, not localhost. Cloud builds from **GitHub `origin/main`** — so **uncommitted local edits never appear in what the user sees.** "Reboot app" on Cloud just redeploys the *existing* committed code; it does NOT pick up local changes.

This has repeatedly caused "I made the change but the user never sees it." To avoid it:

1. **If the user is looking at the deployed app, the only way they see your change is to commit AND push to `main`.** A local file edit, a `streamlit run` restart, or a Cloud reboot will NOT show it. Push, then Cloud auto-redeploys in ~1 min.
2. **When a pure-Python change (e.g. removing a layer, changing a constant) still doesn't show after the user restarts**, suspect this first: the change is uncommitted / unpushed and they're on the cloud deploy. Run `git status --short` to confirm there are `M` (modified-but-uncommitted) files.
3. **Local testing alternative:** `streamlit run app.py` and view the `localhost` URL (NOT the cloud URL). Note Streamlit reloads imported modules under `views/` on file change, but if it misses one, fully restart the server.
4. **Map-specific (st_folium):** the maps live in `views/donut_scraper.py` and `views/leads.py`. Custom Leaflet JS injected via `m.get_root().html.add_child(folium.Element("<script>..."))` is **unreliable inside the st_folium iframe** — it often silently doesn't run. Bake controls into the map's own init instead, via a `branca.element.MacroElement` whose `{% macro script %}` does `...addTo({{ this._parent.get_name() }})` and adding it with `m.add_child(...)` (see `_ImperialScale`). This is the same reliable mechanism folium's built-in `control_scale=True` uses.

## Stack

- Streamlit 1.50 multi-page app (`app.py` → `pages/`)
- Python 3.9, dotenv loaded in `app.py`
- Supabase (REST API via `requests`, not the Python SDK) for persistence
- Google Sheets via `gspread` + service account JSON in `GOOGLE_SERVICE_ACCOUNT_JSON` env var
- Folium + streamlit-folium for the sidebar map
- Outscraper API for deep review scans

## Audience

This is an **internal tool** used by the Kairos co-founders and early team. Everyone using it already knows what Kairos is and what the product does. Do NOT write copy that explains "what Kairos is" or treats the user like an outsider. Write for people who built the company.

## Color palette (from kairoshealthai.com)

- `#183e34` — dark forest green (primary brand, CTA buttons, accents)
- `#3abdaf` — teal mint (Streamlit primary, already in `.streamlit/config.toml`)
- `rgba(24, 62, 53, 0.05)` — subtle green tint for card backgrounds
- `rgba(24, 62, 53, 0.12)` — stronger green tint
- `#e5e7eb` — light gray border
- `#282a30` — primary text
- `#6b6f76` — secondary text
- `#ffffff` — white base

## Key session state keys

- `_pipeline` — dict tracking run state (running, progress, leads_df, etc.)
- `_donut_pipeline` — dict tracking Field Ops (Donut Scraper) run state
- `history_target_run` — run ID to auto-expand when switching to History page
- `history_target_lead_place_id` — place ID to scroll to in that run
- `_leads_{run_id}` — cached leads per run (lazy-loaded in history.py)
- `history_limit` — how many runs to load (default 50)

## Supabase schema notes

- `leads` table: `ALTER TABLE leads ADD COLUMN IF NOT EXISTS email TEXT;`
- `leads` table: `ALTER TABLE leads ADD COLUMN IF NOT EXISTS reviews_json TEXT;`
- Run these migrations before deploying email extraction.

## Local dev detection

`os.path.exists("/Users/yajatparmar")` is used throughout to gate local-only features (test run logging, etc.).

## Google Sheets

**Lead-gen sheet** (Find Leads tool)  
Spreadsheet ID: `1UlBdK2z7UsP-_IFYhxK5IImmHCOGFKKvaGHUDw_dXHs`  
Auto-sync runs on every pipeline completion. Use "Sync History" button in History page to backfill missed runs.

**Field Ops sheet** (Donut Scraper / Area Scraper)  
Sheet name: `Kairos Donut Scraper` — created automatically on first run by the service account.  
Env var: `DONUT_SPREADSHEET_ID` — optional; if set, the app opens the sheet by ID instead of searching by name. Set this after the first run to avoid a name-lookup round-trip.  
Includes a `_area_index` tab (internal bookkeeping for IoU-based same-area detection — do not manually edit this tab).  
Same `GOOGLE_SERVICE_ACCOUNT_JSON` service account as the lead-gen sheet — no new credentials needed.

## API cost constants — update these when pricing or accounts change

All pricing lives in `utils/usage_tracker.py`. When anything changes, update the constants there first — they flow through to History, Find Leads, and API Usage automatically.

| Constant | File | Current value | Notes |
|---|---|---|---|
| `OUTSCRAPER_REVIEW_COST` | `utils/usage_tracker.py` | `0.003` | $3/1,000 reviews — Yajat's personal account |
| `OUTSCRAPER_BILLING_OFFSET_USD` | `utils/usage_tracker.py` | `4.89` | Pre-tracking spend (calls made before Supabase was connected) — reset to `0.0` when switching to company APIs |
| `GOOGLE_GEOCODE_COST` | `utils/usage_tracker.py` | `0.005` | Published Maps Platform rate |
| `GOOGLE_SEARCH_COST` | `utils/usage_tracker.py` | `0.032` | Published Maps Platform rate |
| `GOOGLE_DETAIL_COST` | `utils/usage_tracker.py` | `0.017` | Published Maps Platform rate |
| `GOOGLE_MONTHLY_CREDIT_USD` | `utils/usage_tracker.py` | `200.0` | Free monthly credit |

## Outscraper cost tracking caveat

The app estimates Outscraper cost from reviews tracked in Supabase (reviews × $0.003). However, Outscraper calls made **before Supabase was connected** are not in the database. The actual billed amount is higher than what the app shows. As of Jun 24, 2026 the real Outscraper balance is **-$4.89** (billing period Jun 19 – Jul 19) vs. a lower estimated figure in the app. Always cross-check against `app.outscraper.cloud/billing/payments` for actuals.

## ⚠ Company API migration — checklist for when this happens

When Kairos switches from Yajat's personal API accounts to company accounts, do ALL of the following:

1. **Streamlit Cloud secrets** — replace `GOOGLE_PLACES_API_KEY`, `OUTSCRAPER_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `GEMINI_API_KEY` with company credentials. Also update `DONUT_SPREADSHEET_ID` if the Field Ops sheet is migrated to a company-owned Google Sheets file.
2. **Reset Outscraper usage tracking** — run `UPDATE runs SET outscraper_reviews = 0` or clear the local `api_usage.json` so the monthly counter starts fresh. The old balance belongs to the personal account.
3. **Update pricing constants** — if the company Outscraper plan has a different per-review rate, update `OUTSCRAPER_REVIEW_COST` in `utils/usage_tracker.py`. Same for Google if rates change.
4. **Reset `OUTSCRAPER_MONTHLY_LIMIT`** — update the cap in `utils/usage_tracker.py` to match the company plan.
5. **Update local dev guard** — if a different developer takes over local dev, update `os.path.exists("/Users/yajatparmar")` references in `pages/leads.py` and `pages/history.py`.
6. **Google Sheets** — the spreadsheet ID and service account may change; update in `CLAUDE.md` and re-test auto-sync.
7. **Verify Adzuna commercial license** — the current Adzuna key is under evaluation terms. Switch to a paid commercial key before production scale.

Yajat will say something like "switch to company APIs" or "reset the balance" — that's the trigger for this checklist.
