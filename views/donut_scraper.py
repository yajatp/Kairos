from __future__ import annotations

import os
import threading
import time
from datetime import date

import folium
import pandas as pd
import streamlit as st
from folium.plugins import Draw
from streamlit_folium import st_folium

from pipeline.donut_search import (
    CIRCLE_WARNING_THRESHOLD,
    estimate_circle_count,
    filter_by_polygon,
    run_grid_search,
    compute_polygon_area_sqmi,
    compute_polygon_centroid,
)
from pipeline.places import reverse_geocode
import math
from pipeline.donut_enrichment import enrich_clinic
from utils.donut_sheets import write_run_to_sheet


def _get_secret(key: str) -> str:
    val = os.getenv(key, "")
    if not val:
        try:
            val = st.secrets.get(key, "")
        except Exception:
            pass
    return val


def _init_pipeline_state() -> None:
    if "_donut_pipeline" not in st.session_state:
        st.session_state._donut_pipeline = {
            "running": False,
            "progress": 0,
            "message": "",
            "messages": [],
            "clinics": None,
            "error": None,
            "polygon_coords": None,
            "buffer_miles": 0.5,
            "area_name": "",
            "sheet_result": None,
            "last_calculated_polygon": None,
            "area_sqmi": 0.0,
            "city_state": "",
            "auto_buffer_miles": 0.5,
        }


def _run_pipeline(
    p: dict,
    polygon_coords: list[list[float]],
    buffer_miles: float,
    area_name: str,
    api_key: str,
    gemini_key: str,
) -> None:
    """Runs in a background thread; writes results back into session state."""

    def progress(msg: str, pct: int = 0) -> None:
        p["message"] = msg
        p["progress"] = pct
        if "messages" not in p or p["messages"] is None:
            p["messages"] = []
        if not p["messages"] or p["messages"][-1] != msg:
            p["messages"].append(msg)

    try:
        progress("Starting grid search...", 2)

        raw_clinics = run_grid_search(
            polygon_coords,
            api_key,
            progress_cb=progress,
        )

        progress(f"Filtering {len(raw_clinics)} clinics by polygon + buffer...", 90)
        clinics = filter_by_polygon(raw_clinics, polygon_coords, buffer_miles)

        progress(f"Enriching {len(clinics)} clinics (email + dentist extraction)...", 92)
        for i, clinic in enumerate(clinics):
            progress(
                f"Enriching clinic {i + 1} of {len(clinics)}: {clinic.get('name', '')}...",
                92 + int(7 * (i + 1) / max(len(clinics), 1)),
            )
            enrich_clinic(clinic, gemini_key=gemini_key)

        progress("Writing to Google Sheets...", 99)
        sheet_result = write_run_to_sheet(
            clinics,
            polygon_coords,
            area_name or None,
            buffer_miles,
            run_date=date.today().isoformat(),
        )
        p["sheet_result"] = sheet_result
        p["clinics"] = clinics
        p["error"] = None
        progress("Done.", 100)

    except Exception as e:
        p["error"] = str(e)
        p["clinics"] = None
        progress("Error.", 0)
    finally:
        p["running"] = False


def _build_results_df(clinics: list[dict]) -> pd.DataFrame:
    from utils.donut_sheets import _DAYS

    rows = []
    for c in clinics:
        hours = c.get("hours_by_day", {})
        row = {
            "Clinic Name": c.get("name", ""),
            "Classification": c.get("classification", ""),
            "Zone": c.get("inclusion_zone", "").capitalize(),
            "Phone": c.get("phone", ""),
            "Email": c.get("email", ""),
            "Head Dentist / Key Staff": c.get("head_dentist", ""),
            "Address": c.get("address", ""),
            "Website": c.get("website", ""),
        }
        for day in _DAYS:
            row[f"Hours ({day[:3]})"] = hours.get(day, "")
        row["Notes"] = c.get("notes", "")
        rows.append(row)
    return pd.DataFrame(rows)


_SIDEBAR_CSS = """
<style>
.ds-section-label {
    font-size: 10.5px; font-weight: 600; letter-spacing: 0.07em;
    text-transform: uppercase; color: #8a8f98; margin: 14px 0 4px;
}
.ds-stat-row { display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.ds-stat { flex: 1; min-width: 80px; background: #fff; border: 1px solid #ededed;
    border-radius: 8px; padding: 10px 12px; }
.ds-stat .sv { font-size: 19px; font-weight: 700; letter-spacing: -0.03em; color: #282a30; }
.ds-stat .sl { font-size: 10px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.06em; color: #6b6f76; margin-top: 2px; }
.zone-core { color: #183e34; font-weight: 600; }
.zone-buffer { color: #6b6f76; }
</style>
"""


def _render_sidebar_controls() -> tuple[float, str, bool, bool]:
    """Render sidebar controls. Returns (buffer_miles, area_name, run_clicked, estimate_clicked)."""
    if "buffer_slider" not in st.session_state:
        st.session_state.buffer_slider = 0.5

    st.markdown("<div class='ds-section-label'>Buffer Distance</div>", unsafe_allow_html=True)
    buffer_miles = st.number_input(
        "Miles outside drawn polygon to include",
        min_value=0.0,
        max_value=5.0,
        step=0.1,
        format="%.1f",
        key="buffer_slider",
        label_visibility="collapsed",
    )
    st.caption(f"{buffer_miles:.1f} mi buffer around drawn polygon")

    st.markdown("<div class='ds-section-label'>Area Label (optional)</div>", unsafe_allow_html=True)
    area_name = st.text_input(
        "Short name for this area",
        placeholder="e.g. Prosper test zone",
        label_visibility="collapsed",
    )

    st.markdown("<hr style='margin: 12px 0;'>", unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    estimate_clicked = col1.button(
        ":material/calculate: Estimate",
        use_container_width=True,
        help="Estimate API call count before running",
    )
    run_clicked = col2.button(
        ":material/play_arrow: Run",
        type="primary",
        use_container_width=True,
    )

    return buffer_miles, area_name, run_clicked, estimate_clicked


_TILE_LAYERS = {
    "Street (OSM)": {
        "tiles": "OpenStreetMap",
        "attr": None,
    },
    "Satellite": {
        "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attr": "Esri World Imagery",
    },
    "Light Streets": {
        "tiles": "CartoDB positron",
        "attr": None,
    },
}



def _render_draw_map() -> list[list[float]] | None:
    """Render the Folium draw map. Returns polygon coords [[lng, lat], ...] or None."""
    p = st.session_state._donut_pipeline

    center_lat = 32.7767
    center_lng = -96.7970
    zoom = 11

    if p.get("polygon_coords"):
        coords = p["polygon_coords"]
        lats = [c[1] for c in coords]
        lngs = [c[0] for c in coords]
        center_lat = sum(lats) / len(lats)
        center_lng = sum(lngs) / len(lngs)

    # Street (OSM) is the default base layer (show=True)
    m = folium.Map(location=[center_lat, center_lng], zoom_start=zoom, tiles=None)

    first = True
    for name, cfg in _TILE_LAYERS.items():
        if cfg["attr"]:
            folium.TileLayer(
                tiles=cfg["tiles"], attr=cfg["attr"], name=name, control=True, show=first,
            ).add_to(m)
        else:
            folium.TileLayer(cfg["tiles"], name=name, control=True, show=first).add_to(m)
        first = False

    folium.LayerControl(position="bottomright", collapsed=True).add_to(m)

    # Auto satellite labels – no toggle, injected via Leaflet JS after map initialization
    _auto_labels_js = """
    <script>
    (function() {
        var checkCount = 0;
        function initAutoLabels() {
            var map = window['MAP_VAR_NAME'];
            if (!map) {
                checkCount++;
                if (checkCount < 100) {
                    setTimeout(initAutoLabels, 100);
                }
                return;
            }
            var labelsLayer = L.tileLayer(
                'https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png',
                {
                    attribution: '&copy; CartoDB',
                    pane: 'overlayPane',
                    zIndex: 650
                }
            );
            map.on('baselayerchange', function(e) {
                if (e.name === 'Satellite') {
                    map.addLayer(labelsLayer);
                } else {
                    map.removeLayer(labelsLayer);
                }
            });

            // Add custom scale control
            var scaleControl = L.control.scale({metric: false, imperial: true});
            scaleControl.addTo(map);
            
            try {
                var scaleContainer = scaleControl.getContainer();
                
                // Move container out of the control corner so it doesn't get clipped or restricted
                map.getContainer().appendChild(scaleContainer);
                scaleContainer.style.position = 'absolute';
                scaleContainer.style.bottom = '30px';
                scaleContainer.style.left = '10px';
                scaleContainer.style.zIndex = '1000';
                scaleContainer.style.cursor = 'grab';
                scaleContainer.style.pointerEvents = 'auto';
                scaleContainer.style.background = 'rgba(255,255,255,0.9)';
                scaleContainer.style.padding = '4px 30px 4px 8px';
                scaleContainer.style.borderRadius = '4px';
                scaleContainer.style.boxShadow = '0 1px 5px rgba(0,0,0,0.4)';
                scaleContainer.title = 'Drag to measure distances';
                
                var resetBtn = document.createElement('div');
                resetBtn.innerHTML = '↺';
                resetBtn.title = 'Reset Scale Position';
                resetBtn.style.cssText = 'position:absolute; right:8px; top:50%; transform:translateY(-50%); cursor:pointer; font-size:18px; color:#183e34; font-weight:bold;';
                resetBtn.onclick = function(e) {
                    e.stopPropagation();
                    scaleContainer.style.transform = ''; // Reset L.Draggable translation
                };
                scaleContainer.appendChild(resetBtn);
                
                // Use Leaflet's Draggable but stop click propagation so the map doesn't drag
                var draggable = new L.Draggable(scaleContainer);
                draggable.enable();
                L.DomEvent.disableClickPropagation(scaleContainer);
                draggable.on('dragstart', function() { scaleContainer.style.cursor = 'grabbing'; });
                draggable.on('dragend', function() { scaleContainer.style.cursor = 'grab'; });
            } catch (err) {
                console.error("Failed to initialize draggable scale, falling back to static scale.", err);
            }
        }
        function waitLeaflet() {
            if (typeof L !== 'undefined') {
                initAutoLabels();
            } else {
                setTimeout(waitLeaflet, 100);
            }
        }
        waitLeaflet();
    })();
    </script>
    """
    _auto_labels_js = _auto_labels_js.replace("MAP_VAR_NAME", m.get_name())
    m.get_root().html.add_child(folium.Element(_auto_labels_js))

    Draw(
        export=False,
        position="topleft",
        draw_options={
            "polygon": {
                "allowIntersection": False,
                "shapeOptions": {"color": "#183e34", "weight": 2, "fillOpacity": 0.08},
            },
            "polyline": False,
            "rectangle": False,
            "circle": False,
            "marker": False,
            "circlemarker": False,
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(m)

    if p.get("polygon_coords"):
        coords = p["polygon_coords"]
        folium.Polygon(
            locations=[[c[1], c[0]] for c in coords],
            color="#183e34",
            weight=2,
            fill=True,
            fill_color="#183e34",
            fill_opacity=0.08,
        ).add_to(m)

    result = st_folium(m, width="100%", height=440, key="donut_draw_map", returned_objects=["last_active_drawing"])

    polygon_coords = None
    if result and result.get("last_active_drawing"):
        drawing = result["last_active_drawing"]
        geo = drawing.get("geometry", {})
        if geo.get("type") == "Polygon":
            coords = geo.get("coordinates", [[]])[0]
            if len(coords) >= 3:
                polygon_coords = coords

    return polygon_coords


def _render_results(clinics: list[dict], sheet_result: dict | None) -> None:
    core = [c for c in clinics if c.get("inclusion_zone") == "core"]
    buf = [c for c in clinics if c.get("inclusion_zone") == "buffer"]
    with_phone = [c for c in clinics if c.get("phone")]
    with_email = [c for c in clinics if c.get("email")]
    with_dentist = [c for c in clinics if c.get("head_dentist")]

    st.markdown(
        f"""
        <div class='ds-stat-row'>
          <div class='ds-stat'><div class='sv'>{len(clinics)}</div><div class='sl'>Total Clinics</div></div>
          <div class='ds-stat'><div class='sv'>{len(core)}</div><div class='sl'>Core Zone</div></div>
          <div class='ds-stat'><div class='sv'>{len(buf)}</div><div class='sl'>Buffer Zone</div></div>
          <div class='ds-stat'><div class='sv'>{len(with_phone)}</div><div class='sl'>With Phone</div></div>
          <div class='ds-stat'><div class='sv'>{len(with_email)}</div><div class='sl'>With Email</div></div>
          <div class='ds-stat'><div class='sv'>{len(with_dentist)}</div><div class='sl'>Dentist Found</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if sheet_result and not sheet_result.get("error"):
        st.success(
            f":material/check_circle: Saved to **{sheet_result['tab']}** tab "
            f"({sheet_result['rows_written']} rows) — "
            f"[Open Sheet]({sheet_result['sheet_url']})"
        )
    elif sheet_result and sheet_result.get("error"):
        st.warning(f":material/warning: Sheet write failed: {sheet_result['error']}")

    df = _build_results_df(clinics)

    col_export1, col_export2, _ = st.columns([1, 1, 4])
    with col_export1:
        csv = df.to_csv(index=False).encode()
        st.download_button(
            ":material/download: CSV",
            data=csv,
            file_name=f"donut_scraper_{date.today().isoformat()}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with col_export2:
        phones_emails = df[["Clinic Name", "Phone", "Email", "Head Dentist / Key Staff"]].copy()
        pe_csv = phones_emails.to_csv(index=False).encode()
        st.download_button(
            ":material/contacts: Contacts",
            data=pe_csv,
            file_name=f"donut_contacts_{date.today().isoformat()}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    zone_filter = st.pills(
        "Inclusion Zone",
        ["All", "Core only", "Buffer only"],
        default="All",
        label_visibility="collapsed",
    )

    display_df = df.copy()
    if zone_filter == "Core only":
        display_df = display_df[display_df["Zone"] == "Core"]
    elif zone_filter == "Buffer only":
        display_df = display_df[display_df["Zone"] == "Buffer"]

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Website": st.column_config.LinkColumn("Website", display_text="Visit"),
            "Zone": st.column_config.TextColumn(
                "Zone",
                help="Core = inside drawn polygon; Buffer = within buffer distance",
                width="small",
            ),
        },
    )


def _render_empty_state() -> None:
    st.markdown(
        """
        <div class='empty-state'>
          <span class='empty-state-icon'>:material/draw:</span>
          <div class='empty-state-title'>Draw an area to get started</div>
          <div class='empty-state-body'>
            Use the polygon tool on the map to outline the neighborhood you want to canvas.
            Then set a buffer distance and click Run.
          </div>
          <div class='how-it-works'>
            <div class='hw-title'>How it works</div>
            <div class='hw-step'><div class='hw-num'>1</div>Draw a polygon on the map</div>
            <div class='hw-step'><div class='hw-num'>2</div>Set buffer distance (default 0.5 mi)</div>
            <div class='hw-step'><div class='hw-num'>3</div>Click Run — takes 30–90 seconds</div>
            <div class='hw-step'><div class='hw-num'>4</div>Results land in the Donut Scraper Sheet automatically</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Page entry point ─────────────────────────────────────────────────────────

st.markdown(_SIDEBAR_CSS, unsafe_allow_html=True)
_init_pipeline_state()

p = st.session_state._donut_pipeline

# Page header
st.markdown(
    "<div class='page-header-linear'>"
    "<span class='bc-parent'>Kairos</span>"
    "<span class='bc-sep'>/</span>"
    "<span class='bc-current'>Donut Scraper</span>"
    "</div>",
    unsafe_allow_html=True,
)

# Sidebar controls
with st.sidebar:
    st.markdown("<div class='ds-section-label'>Run Controls</div>", unsafe_allow_html=True)
    buffer_miles, area_name, run_clicked, estimate_clicked = _render_sidebar_controls()

    gemini_key = _get_secret("GEMINI_API_KEY")
    if gemini_key:
        st.caption(":material/psychology: Gemini enabled — AI extraction active")
    else:
        st.caption(":material/psychology_alt: No GEMINI_API_KEY — regex-only extraction")

if p["running"]:
    st.info("Map is locked while the scraper is running.")
else:
    st.markdown("**Draw your target area** — polygon only, one shape at a time")
    new_polygon_coords = _render_draw_map()
    if new_polygon_coords:
        p["polygon_coords"] = new_polygon_coords
        
        # Auto-calculate stats if it's a newly drawn polygon
        if new_polygon_coords != p.get("last_calculated_polygon"):
            area = compute_polygon_area_sqmi(new_polygon_coords)
            lat, lng = compute_polygon_centroid(new_polygon_coords)
            api_key = _get_secret("GOOGLE_PLACES_API_KEY")
            city_state = reverse_geocode(lat, lng, api_key) if api_key else "Unknown Location"
            
            calc_buf = max(0.1, min(5.0, math.sqrt(area) * 0.2))
            auto_buf = round(calc_buf, 1)
            
            p["area_sqmi"] = area
            p["city_state"] = city_state
            p["auto_buffer_miles"] = auto_buf
            p["last_calculated_polygon"] = new_polygon_coords
            st.session_state.buffer_slider = auto_buf
            st.rerun()

polygon_coords = p.get("polygon_coords")

# Feedback Card
if polygon_coords and not p["running"]:
    area = p.get("area_sqmi", 0.0)
    city = p.get("city_state", "Unknown Location")
    buf = p.get("auto_buffer_miles", 0.5)
    
    st.markdown(
        f"""
        <div style='background:#f7f7f8; border:1px solid #ededed; border-radius:8px; padding:16px; margin-top:16px; display:flex; gap:16px; flex-wrap:wrap;'>
            <div style='flex:1; min-width:120px;'>
                <div style='font-size:11px; font-weight:600; color:#6b6f76; text-transform:uppercase; letter-spacing:0.05em;'>Encompassed Area</div>
                <div style='font-size:16px; font-weight:600; color:#183e34; margin-top:4px;'>{area:.1f} sq miles</div>
            </div>
            <div style='flex:1; min-width:120px;'>
                <div style='font-size:11px; font-weight:600; color:#6b6f76; text-transform:uppercase; letter-spacing:0.05em;'>Primary Location</div>
                <div style='font-size:16px; font-weight:600; color:#183e34; margin-top:4px;'>{city}</div>
            </div>
            <div style='flex:1; min-width:120px;'>
                <div style='font-size:11px; font-weight:600; color:#6b6f76; text-transform:uppercase; letter-spacing:0.05em;'>Auto-Buffer Picked</div>
                <div style='font-size:16px; font-weight:600; color:#183e34; margin-top:4px;'>{buf:.1f} miles</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    st.caption("You can override this suggested buffer distance using the sidebar before clicking Run.")

# Estimate button
if estimate_clicked:
    if not polygon_coords:
        st.warning("Draw a polygon first.")
    else:
        n = estimate_circle_count(polygon_coords)
        if n > CIRCLE_WARNING_THRESHOLD:
            st.warning(
                f"This area requires **{n} grid queries** — larger than the recommended limit "
                f"({CIRCLE_WARNING_THRESHOLD}). Consider drawing a smaller area."
            )
        else:
            st.info(f"Estimated **{n} grid queries** — looks reasonable.")

# Run button
if run_clicked:
    api_key = _get_secret("GOOGLE_PLACES_API_KEY")

    if not polygon_coords:
        st.error("Draw a polygon on the map before running.")
    elif not api_key:
        st.error("GOOGLE_PLACES_API_KEY not configured.")
    elif p["running"]:
        st.warning("A run is already in progress.")
    else:
        n = estimate_circle_count(polygon_coords)
        if n > CIRCLE_WARNING_THRESHOLD:
            st.warning(
                f"This area needs **{n} grid queries**. "
                f"Consider drawing a smaller area, or confirm you want to proceed."
            )
            if st.button("Confirm — run anyway", type="primary"):
                p.update({
                    "running": True, "error": None, "clinics": None,
                    "sheet_result": None, "buffer_miles": buffer_miles,
                    "area_name": area_name, "progress": 0, "message": "",
                    "messages": [],
                })
                t = threading.Thread(
                    target=_run_pipeline,
                    args=(p, polygon_coords, buffer_miles, area_name, api_key, gemini_key),
                    daemon=True,
                )
                t.start()
                st.rerun()
        else:
            p.update({
                "running": True, "error": None, "clinics": None,
                "sheet_result": None, "buffer_miles": buffer_miles,
                "area_name": area_name, "progress": 0, "message": "",
                "messages": [],
            })
            t = threading.Thread(
                target=_run_pipeline,
                args=(p, polygon_coords, buffer_miles, area_name, api_key, gemini_key),
                daemon=True,
            )
            t.start()
            st.rerun()

# Progress display
if p["running"]:
    st.markdown("<div style='padding:16px 0 8px'>", unsafe_allow_html=True)
    prog_pct = p.get("progress", 0)
    prog_msg = p.get("message", "Running...")
    st.progress(prog_pct / 100, text=f"Scraping dentist area… {prog_pct}%")

    recent = p.get("messages", [])[-6:]
    if recent:
        lines = "".join(
            f"<div style='padding:2px 0;border-bottom:1px solid #ededed;font-size:11.5px;color:#6b6f76'>{m}</div>"
            for m in recent
        )
        st.markdown(
            f"<div style='font-family:ui-monospace,monospace;padding:10px 12px;"
            f"background:#f7f7f8;border-radius:7px;"
            f"border:1px solid #ededed;margin-top:8px'>{lines}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)
    st.caption("This takes 30–90 seconds depending on area size. Do not navigate away.")
    time.sleep(0.5)
    st.rerun()

# Error display
if p.get("error"):
    st.error(f":material/error: Run failed: {p['error']}")

# Results display
if p.get("clinics") is not None and not p["running"]:
    clinics = p["clinics"]
    if clinics:
        st.markdown("---")
        _render_results(clinics, p.get("sheet_result"))
    else:
        st.info(
            "No dental clinics found. Possible causes: polygon is too small, "
            "no dental offices in that area, or the Places API key returned no results. "
            "Try expanding the polygon or check the terminal for API error details."
        )
elif not p["running"] and not p.get("clinics") and not p.get("error"):
    _render_empty_state()
