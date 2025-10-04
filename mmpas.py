import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
from dateutil import parser

# ----------------------------
# Config
# ----------------------------
st.set_page_config(page_title="Nearby Training & Schools + Events", page_icon="🗺️", layout="wide")

SERPAPI_KEY = st.secrets.get("SERPAPI_KEY", "")
TICKETMASTER_KEY = st.secrets.get("TICKETMASTER_API_KEY", "")

if not SERPAPI_KEY or not TICKETMASTER_KEY:
    st.error("Add SERPAPI_KEY and TICKETMASTER_API_KEY in .streamlit/secrets.toml to run this app.")
    st.stop()

# Auto-refresh control
refresh_interval = st.sidebar.slider("Auto-refresh interval (minutes)", 1, 30, 5)
st_autorefresh(interval=refresh_interval * 60 * 1000, key="auto_refresh")

# ----------------------------
# Geolocation Support
# ----------------------------
try:
    from streamlit_geolocation import geolocation
    HAS_GEO = True
except Exception:
    HAS_GEO = False

TRAINING_KEYWORDS = [
    "training center", "academy", "bootcamp", "coaching center",
    "institute", "skill development", "IELTS", "Data Science", "Python"
]

# ----------------------------
# OpenStreetMap Geocoding
# ----------------------------
def geocode_address(addr: str) -> Optional[Tuple[float, float, str]]:
    """Get lat/lng from OpenStreetMap Nominatim API."""
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": addr,
        "format": "json",
        "limit": 1,
        "accept-language": "en"
    }
    r = requests.get(url, params=params, headers={"User-Agent": "monmaps-app"})
    data = r.json()
    if not data:
        return None
    res = data[0]
    return (float(res["lat"]), float(res["lon"]), res.get("display_name", addr))

# ----------------------------
# SerpAPI for nearby places
# ----------------------------
def fetch_places_serpapi(lat: float, lng: float, radius_m: int, keywords: List[str]):
    """Fetch nearby places from SerpAPI using Google Maps engine."""
    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_maps",
        "ll": f"@{lat},{lng},{radius_m}m",
        "type": "search",
        "q": " OR ".join(keywords),
        "api_key": SERPAPI_KEY
    }
    r = requests.get(url, params=params, timeout=25)
    data = r.json()
    places = []
    for item in data.get("local_results", []):
        coords = item.get("gps_coordinates", {})
        places.append({
            "name": item.get("title", "Unnamed Place"),
            "lat": coords.get("latitude"),
            "lng": coords.get("longitude"),
            "address": item.get("address", ""),
            "rating": item.get("rating"),
            "reviews": item.get("reviews"),
            "link": item.get("website") or item.get("place_id")
        })
    return places

# ----------------------------
# Ticketmaster API
# ----------------------------
def fetch_ticketmaster_events(city: str, max_results: int = 20):
    url = "https://app.ticketmaster.com/discovery/v2/events.json"
    params = {
        "apikey": TICKETMASTER_KEY,
        "city": city,
        "size": max_results,
        "sort": "date,asc"
    }
    resp = requests.get(url, params=params, timeout=15)
    data = resp.json()

    events = []
    for ev in data.get("_embedded", {}).get("events", []):
        ev_date = None
        if ev.get("dates", {}).get("start", {}).get("localDate"):
            try:
                ev_date = parser.parse(ev["dates"]["start"]["localDate"]).date()
            except:
                pass
        venues = ev.get("_embedded", {}).get("venues", [])
        events.append({
            "name": ev.get("name"),
            "description": ev.get("info", "") or ev.get("pleaseNote", ""),
            "link": ev.get("url", ""),
            "date": ev_date,
            "venue": venues[0].get("name") if venues else "",
            "lat": float(venues[0]["location"]["latitude"]) if venues and "location" in venues[0] else None,
            "lng": float(venues[0]["location"]["longitude"]) if venues and "location" in venues[0] else None
        })
    return events

# ----------------------------
# Sidebar Controls
# ----------------------------
st.sidebar.header("Find Nearby (SerpAPI + OSM)")
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

st.sidebar.subheader("Search Focus")
selected_kw = st.sidebar.multiselect(
    "Choose keywords",
    options=TRAINING_KEYWORDS,
    default=["Data Science", "Python"]
)

st.sidebar.subheader("Filter by Event Date")
date_filter = st.sidebar.date_input("Choose a date (leave blank for all)", value=None)

# ----------------------------
# Fetch Data
# ----------------------------
st.title("Nearby Training & Schools + Live Events")
st.caption("Powered by SerpAPI (Google Maps data) + OpenStreetMap for display.")

with st.spinner("Fetching nearby places…"):
    results = fetch_places_serpapi(lat, lng, radius_m, selected_kw)

with st.spinner(f"Fetching live Ticketmaster events for {city}…"):
    events = fetch_ticketmaster_events(city)

st.subheader(f"Found {len(results)} nearby places and {len(events)} upcoming events")

# ----------------------------
# Display Map (Leaflet + OSM)
# ----------------------------
map_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Training Map</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
  <style>html, body, #map {{ height: 100%; margin:0; padding:0; }}</style>
</head>
<body>
<div id="map"></div>
<script>
  var map = L.map('map').setView([{lat}, {lng}], {14 if radius_km<=5 else 12});
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '© OpenStreetMap contributors'
  }}).addTo(map);

  var places = {json.dumps(results, default=str)};
  places.forEach(function(p) {{
    if (p.lat && p.lng) {{
      var marker = L.marker([p.lat, p.lng]).addTo(map);
      marker.bindPopup("<b>" + p.name + "</b><br/>" + (p.address || "") +
                       "<br/>⭐ " + (p.rating || "N/A") +
                       "<br/><a href='" + (p.link || "#") + "' target='_blank'>Details</a>");
    }}
  }});

  var events = {json.dumps(events, default=str)};
  events.forEach(function(e) {{
    if (e.lat && e.lng) {{
      var icon = L.icon({{
        iconUrl: 'https://maps.gstatic.com/mapfiles/ms2/micons/orange-dot.png',
        iconSize: [25, 41], iconAnchor: [12, 41]
      }});
      var marker = L.marker([e.lat, e.lng], {{icon: icon}}).addTo(map);
      marker.bindPopup("<b>" + e.name + "</b><br/>📅 " + (e.date || 'TBA') +
                       "<br/>" + (e.venue || '') +
                       "<br/><a href='" + e.link + "' target='_blank'>More Info</a>");
    }}
  }});
</script>
</body>
</html>
"""
components.html(map_html, height=560, scrolling=False)

# ----------------------------
# Event List
# ----------------------------
st.subheader(f"Live & Upcoming Events in {city}")
if not events:
    st.info("No upcoming events found.")
else:
    if date_filter:
        filtered = [e for e in events if e["date"] and e["date"] == date_filter]
    else:
        filtered = events
    if not filtered:
        st.warning("No events found for this date.")
    else:
        for e in filtered:
            link_md = f"[More Info]({e['link']})" if e['link'] else ""
            venue = f"📍 {e['venue']}" if e.get("venue") else ""
            st.markdown(f"""
            **{e['name']}**  
            📅 {e['date'] if e['date'] else "Unspecified"}  
            {e['description']}  
            {venue}  
            {link_md}
            """)
