#!/usr/bin/env python
# coding: utf-8

# In[ ]:


import json
import time
from typing import Dict, List, Optional, Tuple

import requests
import streamlit as st

API_KEY = st.secrets["GOOGLE_MAPS_API_KEY"]

# Optional geolocation (graceful fallback)
try:
    from streamlit_geolocation import geolocation
    HAS_GEO = True
except Exception:
    HAS_GEO = False

# ----------------------------
# Config
# ----------------------------
st.set_page_config(page_title="Nearby Training & Schools (Google Maps)", page_icon="🗺️", layout="wide")
API_KEY = st.secrets.get("GOOGLE_MAPS_API_KEY", "")

if not API_KEY:
    st.error("Add GOOGLE_MAPS_API_KEY in .streamlit/secrets.toml to run this app.")
    st.stop()

CATEGORIES = {
    # Google Places 'type' -> human label
    "school": "Schools",
    "university": "Universities",
    "secondary_school": "Secondary Schools",
    "primary_school": "Primary Schools",
    "library": "Libraries",
    # not an official 'training_center' type; use keyword under a broad type:
    # We'll query 'establishment' type with keywords for training-related queries.
}

TRAINING_KEYWORDS = [
    "training center",
    "academy",
    "bootcamp",
    "coaching center",
    "institute",
    "skill development",
    "IELTS",
    "Data Science",
    "Python",
]

# ----------------------------
# Helpers
# ----------------------------
def geocode_address(addr: str) -> Optional[Tuple[float, float, str]]:
    """Use Google Geocoding API to turn address into (lat, lng, formatted_address)."""
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": addr, "key": API_KEY}
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "OK" or not data.get("results"):
        return None
    res = data["results"][0]
    loc = res["geometry"]["location"]
    return (loc["lat"], loc["lng"], res.get("formatted_address", addr))

def nearby_search(
    lat: float,
    lng: float,
    radius_m: int,
    types: List[str],
    keyword: Optional[str] = None,
    max_pages: int = 2,
) -> List[Dict]:
    """
    Calls Google Places Nearby Search.
    - We’ll run multiple calls: one per 'type', plus one for 'establishment' with training keywords.
    - Paginates with next_page_token (2 pages by default).
    """
    all_results: Dict[str, Dict] = {}  # use place_id to de-duplicate
    base = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

    def one_call(params: Dict) -> None:
        nonlocal all_results
        page = 0
        next_token = None
        while True:
            q = params.copy()
            if next_token:
                q["pagetoken"] = next_token
            resp = requests.get(base, params=q, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("status") not in ("OK", "ZERO_RESULTS"):
                # Some statuses require waiting before reusing next_page_token
                if payload.get("status") == "INVALID_REQUEST" and next_token:
                    time.sleep(2)
                    continue
                break
            for pl in payload.get("results", []):
                pid = pl.get("place_id")
                if pid and pid not in all_results:
                    all_results[pid] = pl
            next_token = payload.get("next_page_token")
            page += 1
            if not next_token or page >= max_pages:
                break
            # Google requires a short delay before using next_page_token
            time.sleep(2)

    # Query selected types
    for t in types:
        params = {
            "key": API_KEY,
            "location": f"{lat},{lng}",
            "radius": radius_m,
            "type": t
        }
        if keyword:
            params["keyword"] = keyword
        one_call(params)

    # If user selected "training-like", also search via keywords under 'establishment'
    if "training_like" in types:
        for kw in ( [keyword] if keyword else TRAINING_KEYWORDS ):
            if not kw:
                continue
            params = {
                "key": API_KEY,
                "location": f"{lat},{lng}",
                "radius": radius_m,
                "type": "establishment",
                "keyword": kw
            }
            one_call(params)

    return list(all_results.values())

def fmt_opening_hours(ph: Dict) -> str:
    if not ph:
        return ""
    open_now = ph.get("open_now")
    return "Open now" if open_now else "Closed now"

def gmaps_place_link(place_id: str) -> str:
    # Standard Maps link to a place by ID
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"

# ----------------------------
# Sidebar controls
# ----------------------------
st.sidebar.header("Find Nearby (Google)")
use_device = False
lat = lng = None
got_loc = False

if HAS_GEO:
    with st.sidebar.expander("📍 Use my device location", expanded=False):
        loc = geolocation()
        if loc and "latitude" in loc and "longitude" in loc:
            lat = float(loc["latitude"]); lng = float(loc["longitude"])
            use_device = True; got_loc = True
            st.success(f"Got device location: {lat:.5f}, {lng:.5f}")

with st.sidebar.expander("🔎 Or search an address/city", expanded=not got_loc):
    addr = st.text_input("Type address/city", value="Islamabad, Pakistan")
    if st.button("Locate"):
        with st.spinner("Geocoding…"):
            out = geocode_address(addr)
        if out:
            lat, lng, faddr = out
            st.success(f"Centered to: {faddr}")
            got_loc = True
        else:
            st.error("Could not find that address.")

if not got_loc:
    # Default (Islamabad)
    lat, lng = 33.6844, 73.0479

radius_km = st.sidebar.slider("Radius (km)", 1, 30, 5)
radius_m = radius_km * 1000

# Category selection
st.sidebar.subheader("Categories")
selected = st.sidebar.multiselect(
    "Choose one or more",
    options=["training_like"] + list(CATEGORIES.keys()),
    default=["training_like", "school", "university"]
)

# Optional extra keyword (e.g., “Python”)
extra_kw = st.sidebar.text_input("Add a keyword (optional)", value="")

# Max pages per type
max_pages = st.sidebar.select_slider("Depth per category (pages)", options=[1,2,3], value=2)
st.sidebar.caption("Google returns up to ~20 results per page; more pages = more results.")

# ----------------------------
# Fetch
# ----------------------------
st.title("Nearby Training & Schools — Google Maps")
st.caption("Live results from Google Places. No database — just your location and Google APIs.")
st.markdown(f"**Center:** {lat:.5f}, {lng:.5f} • **Radius:** ~{radius_km} km")

with st.spinner("Searching Google Places…"):
    results = nearby_search(
        lat=lat,
        lng=lng,
        radius_m=radius_m,
        types=selected,
        keyword=extra_kw.strip() or None,
        max_pages=max_pages
    )

# Sort by rating desc, then distance (approx via Google rank)
def rating_key(p):
    r = p.get("rating", 0)
    # Prefer more reviews at tie
    c = p.get("user_ratings_total", 0)
    return (-r, -c)

results_sorted = sorted(results, key=rating_key)

st.subheader(f"Found {len(results_sorted)} places")

# ----------------------------
# Build data for JS map
# ----------------------------
def to_marker(p: Dict) -> Dict:
    loc = p.get("geometry", {}).get("location", {})
    name = p.get("name", "Untitled")
    addr = p.get("vicinity") or p.get("formatted_address") or ""
    rating = p.get("rating", "")
    total = p.get("user_ratings_total", "")
    open_txt = fmt_opening_hours(p.get("opening_hours", {}))
    pid = p.get("place_id", "")
    link = gmaps_place_link(pid) if pid else ""
    return {
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
        "name": name,
        "addr": addr,
        "rating": rating,
        "total": total,
        "open": open_txt,
        "link": link
    }

markers = [to_marker(p) for p in results_sorted if p.get("geometry", {}).get("location")]
markers = [m for m in markers if m["lat"] is not None and m["lng"] is not None]

# ----------------------------
# Render Google Map via JS (components.html)
# ----------------------------
import streamlit.components.v1 as components

MAP_HTML = f"""
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Map</title>
    <meta name="viewport" content="initial-scale=1, width=device-width" />
    <style>
      html, body, #map {{ height: 100%; margin: 0; padding: 0; }}
      .infow {{ font-family: Arial, sans-serif; font-size: 13px; line-height: 1.4; }}
      .infow b {{ font-size: 14px; }}
    </style>
    <script src="https://maps.googleapis.com/maps/api/js?key={API_KEY}&libraries=places"></script>
  </head>
  <body>
    <div id="map"></div>
    <script>
      const center = {{lat: {lat}, lng: {lng}}};
      const markers = {json.dumps(markers)};

      const map = new google.maps.Map(document.getElementById('map'), {{
        center: center,
        zoom: {14 if radius_km <= 5 else 12 if radius_km <= 12 else 11},
        mapTypeControl: false,
        streetViewControl: false
      }});

      const userPin = new google.maps.Marker({{
        position: center,
        map,
        title: "You are here",
        icon: {{
          path: google.maps.SymbolPath.CIRCLE,
          scale: 6,
          fillColor: "#2ecc71",
          fillOpacity: 1,
          strokeWeight: 2,
          strokeColor: "#1e824c"
        }}
      }});

      const infow = new google.maps.InfoWindow();
      markers.forEach(m => {{
        const mk = new google.maps.Marker({{ position: {{lat: m.lat, lng: m.lng}}, map, title: m.name }});
        const html = `
          <div class="infow">
            <b>${{m.name}}</b><br/>
            ${{m.addr || ""}}<br/>
            ${'{'}m.rating ? `⭐ ${{m.rating}} (${ '{' }m.total || 0{ '}' })` : ""{'}'}<br/>
            ${'{'}m.open || ""{'}'}<br/>
            ${'{'}m.link ? `<a href="${'{'}m.link{'}'}" target="_blank">Open in Google Maps</a>` : ""{'}'}
          </div>`;
        mk.addListener('click', () => {{
          infow.setContent(html);
          infow.open({{ anchor: mk, map }});
        }});
      }});
    </script>
  </body>
</html>
"""

components.html(MAP_HTML, height=560, scrolling=False)

# ----------------------------
# List view
# ----------------------------
st.write("")

for p in results_sorted:
    pid = p.get("place_id", "")
    name = p.get("name", "Untitled")
    addr = p.get("vicinity") or p.get("formatted_address") or ""
    rating = p.get("rating", None)
    total = p.get("user_ratings_total", 0)
    open_txt = fmt_opening_hours(p.get("opening_hours", {}))
    link = gmaps_place_link(pid) if pid else ""
    cols = st.columns([3,2,1])
    with cols[0]:
        st.markdown(f"**{name}**")
        st.caption(addr)
        if open_txt:
            st.write(open_txt)
    with cols[1]:
        if rating is not None:
            st.write(f"⭐ {rating} ({total})")
    with cols[2]:
        if link:
            st.link_button("Open in Google Maps", url=link, use_container_width=True)

