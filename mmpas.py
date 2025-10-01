import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date, timedelta

import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
from dateutil import parser

# ----------------------------
# Config
# ----------------------------
st.set_page_config(page_title="Nearby Training & Schools + Events", page_icon="🗺️", layout="wide")
API_KEY = st.secrets.get("GOOGLE_MAPS_API_KEY", "")
EVENTBRITE_KEY = st.secrets.get("EVENTBRITE_API_KEY", "")

if not API_KEY or not EVENTBRITE_KEY:
    st.error("Add GOOGLE_MAPS_API_KEY and EVENTBRITE_API_KEY in .streamlit/secrets.toml to run this app.")
    st.stop()

# Auto-refresh control
refresh_interval = st.sidebar.slider("Auto-refresh interval (minutes)", 1, 30, 5)
st_autorefresh(interval=refresh_interval * 60 * 1000, key="auto_refresh")

# ----------------------------
# Geolocation support
# ----------------------------
try:
    from streamlit_geolocation import geolocation
    HAS_GEO = True
except Exception:
    HAS_GEO = False

CATEGORIES = {
    "school": "Schools",
    "university": "Universities",
    "secondary_school": "Secondary Schools",
    "primary_school": "Primary Schools",
    "library": "Libraries",
}

TRAINING_KEYWORDS = [
    "training center", "academy", "bootcamp", "coaching center",
    "institute", "skill development", "IELTS", "Data Science", "Python"
]

# ----------------------------
# Google API helpers
# ----------------------------
def geocode_address(addr: str) -> Optional[Tuple[float, float, str]]:
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": addr, "key": API_KEY}
    r = requests.get(url, params=params, timeout=15)
    data = r.json()
    if data.get("status") != "OK" or not data.get("results"):
        return None
    res = data["results"][0]
    loc = res["geometry"]["location"]
    return (loc["lat"], loc["lng"], res.get("formatted_address", addr))

def nearby_search(lat: float, lng: float, radius_m: int, types: List[str], keyword: Optional[str] = None, max_pages: int = 1) -> List[Dict]:
    all_results: Dict[str, Dict] = {}
    base = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

    def one_call(params: Dict) -> None:
        nonlocal all_results
        resp = requests.get(base, params=params, timeout=15)
        payload = resp.json()
        if payload.get("status") not in ("OK", "ZERO_RESULTS"):
            return
        for pl in payload.get("results", []):
            pid = pl.get("place_id")
            if pid and pid not in all_results:
                all_results[pid] = pl

    for t in types:
        params = {"key": API_KEY, "location": f"{lat},{lng}", "radius": radius_m, "type": t}
        if keyword:
            params["keyword"] = keyword
        one_call(params)

    if "training_like" in types:
        for kw in ([keyword] if keyword else TRAINING_KEYWORDS):
            if not kw:
                continue
            params = {"key": API_KEY, "location": f"{lat},{lng}", "radius": radius_m, "type": "establishment", "keyword": kw}
            one_call(params)

    return list(all_results.values())

def fmt_opening_hours(ph: Dict) -> str:
    if not ph:
        return ""
    return "Open now" if ph.get("open_now") else "Closed now"

def gmaps_place_link(place_id: str) -> str:
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"

# ----------------------------
# Eventbrite for events (with lat/lon)
# ----------------------------
def fetch_eventbrite_events(city: str, lat: float, lng: float, radius_km: int = 15, max_results: int = 20):
    url = "https://www.eventbriteapi.com/v3/events/search/"
    headers = {"Authorization": f"Bearer {EVENTBRITE_KEY}"}
    params = {
        "location.latitude": lat,
        "location.longitude": lng,
        "location.within": f"{radius_km}km",   # ✅ use radius around city center
        "sort_by": "date"
    }
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    data = resp.json()

    events = []
    today = datetime.today().date()
    for ev in data.get("events", [])[:max_results]:
        ev_date = None
        if ev.get("start"):
            try:
                ev_date = parser.parse(ev["start"]["local"]).date()
            except:
                pass
        events.append({
            "name": ev["name"]["text"],
            "description": ev["description"]["text"] if ev.get("description") else "",
            "link": ev["url"],
            "date": ev_date
        })
    return events

# ----------------------------
# Sidebar controls
# ----------------------------
st.sidebar.header("Find Nearby (Google)")
lat = lng = None
got_loc = False

if HAS_GEO:
    with st.sidebar.expander("📍 Use my device location", expanded=False):
        loc = geolocation()
        if loc and "latitude" in loc and "longitude" in loc:
            lat = float(loc["latitude"]); lng = float(loc["longitude"])
            got_loc = True
            st.success(f"Got device location: {lat:.5f}, {lng:.5f}")

with st.sidebar.expander("🔎 Or search by city/area", expanded=not got_loc):
    city = st.text_input("City", value="New York")
    area = st.text_input("Area / Locality (optional)", value="")
    if st.button("Locate"):
        query = f"{area}, {city}" if area else city
        out = geocode_address(query)
        if out:
            lat, lng, faddr = out
            st.success(f"Centered to: {faddr}")
            got_loc = True
        else:
            st.error("Could not find that location.")

if not got_loc:
    lat, lng = 33.6844, 73.0479
    city = "Islamabad"

radius_km = st.sidebar.slider("Radius (km)", 1, 15, 5)
radius_m = radius_km * 1000

st.sidebar.subheader("Categories")
selected = st.sidebar.multiselect(
    "Choose categories",
    options=["training_like"] + list(CATEGORIES.keys()),
    default=["training_like", "school", "university"]
)

st.sidebar.subheader("Filter by Event Date")
date_filter = st.sidebar.date_input("Choose a date (leave blank for all)", value=None)

# ----------------------------
# Fetch Places + Events
# ----------------------------
st.title("Nearby Training & Schools + Live Events")
st.caption("Google Places for institutions + Eventbrite for live events in the selected area.")

with st.spinner("Fetching nearby places…"):
    results = nearby_search(lat, lng, radius_m, selected, keyword=None)

results_sorted = sorted(results, key=lambda p: (-p.get("rating", 0), -p.get("user_ratings_total", 0)))

with st.spinner("Fetching live Eventbrite events…"):
    events = fetch_eventbrite_events(city, lat, lng, radius_km)

st.subheader(f"Found {len(results_sorted)} places and {len(events)} upcoming events")

# ----------------------------
# Place Markers on Map
# ----------------------------
place_markers = [{
    "lat": p["geometry"]["location"]["lat"],
    "lng": p["geometry"]["location"]["lng"],
    "name": p.get("name", "Untitled"),
    "addr": p.get("vicinity") or p.get("formatted_address") or "",
    "rating": p.get("rating", ""),
    "total": p.get("user_ratings_total", ""),
    "open": fmt_opening_hours(p.get("opening_hours", {})),
    "link": gmaps_place_link(p.get("place_id", ""))
} for p in results_sorted if "geometry" in p]

MAP_HTML = f"""
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>html, body, #map {{ height: 100%; margin: 0; padding: 0; }}</style>
    <script src="https://maps.googleapis.com/maps/api/js?key={API_KEY}&libraries=places"></script>
  </head>
  <body><div id="map"></div>
  <script>
    const center = {{lat: {lat}, lng: {lng}}};
    const map = new google.maps.Map(document.getElementById('map'), {{
      center: center, zoom: {14 if radius_km<=5 else 12}, mapTypeControl:false
    }});

    new google.maps.Marker({{
      position: center, map, title:"You are here",
      icon:{{path:google.maps.SymbolPath.CIRCLE,scale:6,fillColor:"#2ecc71",fillOpacity:1,strokeWeight:2,strokeColor:"#1e824c"}}
    }});

    const infow = new google.maps.InfoWindow();

    const places = {json.dumps(place_markers)};
    places.forEach(m => {{
      const mk = new google.maps.Marker({{position:{{lat:m.lat,lng:m.lng}},map,title:m.name}});
      const html = `<b>${{m.name}}</b><br/>${{m.addr}}<br/>⭐ ${{m.rating}} (${{m.total}})<br/>${{m.open}}<br/><a href="${{m.link}}" target="_blank">Open in Google Maps</a>`;
      mk.addListener('click',()=>{{infow.setContent(html);infow.open({{anchor:mk,map}});}});
    }});
  </script></body>
</html>
"""
components.html(MAP_HTML, height=560, scrolling=False)

# ----------------------------
# Event List (Below Map)
# ----------------------------
st.subheader("Live & Upcoming Events in the City")

if not events:
    st.info("No upcoming events found.")
else:
    if date_filter:
        filtered_events = [e for e in events if e["date"] and e["date"] == date_filter]
    else:
        filtered_events = events

    if not filtered_events:
        st.warning("No events found for this date.")
    else:
        current_date = None
        for e in filtered_events:
            if e["date"] and e["date"] != current_date:
                st.markdown(f"### 📅 {e['date'].strftime('%A, %d %B %Y')}")
                current_date = e["date"]

            if not e["date"] and current_date != "Unspecified":
                st.markdown("### ❓ Unspecified Date")
                current_date = "Unspecified"

            link_md = f"[More Info]({e['link']})" if e['link'] else ""
            st.markdown(f"""
            **{e['name']}**  
            {e['description']}  
            {link_md}
            """)
