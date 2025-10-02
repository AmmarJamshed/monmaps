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
TICKETMASTER_KEY = st.secrets.get("TICKETMASTER_API_KEY", "")

if not TICKETMASTER_KEY:
    st.error("Add TICKETMASTER_API_KEY in .streamlit/secrets.toml to run this app.")
    st.stop()

# Auto-refresh
refresh_interval = st.sidebar.slider("Auto-refresh interval (minutes)", 1, 30, 5)
st_autorefresh(interval=refresh_interval * 60 * 1000, key="auto_refresh")

# ----------------------------
# Session State for persistence
# ----------------------------
if "lat" not in st.session_state:
    st.session_state.lat = 33.6844   # Default Islamabad
if "lng" not in st.session_state:
    st.session_state.lng = 73.0479
if "city" not in st.session_state:
    st.session_state.city = "Islamabad"

# ----------------------------
# Geolocation support (optional)
# ----------------------------
try:
    from streamlit_geolocation import geolocation
    HAS_GEO = True
except Exception:
    HAS_GEO = False

# ----------------------------
# OSM Geocoding (always English)
# ----------------------------
def geocode_address(addr: str) -> Optional[Tuple[float, float, str]]:
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": addr, "format": "json", "limit": 1, "accept-language": "en"}
    r = requests.get(url, params=params, headers={"User-Agent": "streamlit-app"})
    data = r.json()
    if not data:
        return None
    res = data[0]
    return (float(res["lat"]), float(res["lon"]), res.get("display_name", addr))

# ----------------------------
# OSM Places (Overpass API)
# ----------------------------
def osm_places(lat: float, lng: float, radius_m: int, keywords: List[str]):
    query = f"""
    [out:json];
    (
      node(around:{radius_m},{lat},{lng})[amenity];
      way(around:{radius_m},{lat},{lng})[amenity];
      relation(around:{radius_m},{lat},{lng})[amenity];
    );
    out center 20;
    """
    resp = requests.post("https://overpass-api.de/api/interpreter", data={"data": query}, timeout=25)
    data = resp.json()

    places = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name", "Unnamed")
        amenity = tags.get("amenity", "")
        lat_p = el.get("lat") or el.get("center", {}).get("lat")
        lon_p = el.get("lon") or el.get("center", {}).get("lon")

        if any(kw.lower() in name.lower() or kw.lower() in amenity.lower() for kw in keywords):
            places.append({
                "name": name,
                "amenity": amenity,
                "lat": lat_p,
                "lng": lon_p,
                "addr": tags.get("addr:full", tags.get("addr:street", "")),
            })
    return places

# ----------------------------
# Ticketmaster Events
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
            # Always serialize date as string
            "date": ev_date.isoformat() if ev_date else None,
            "venue": venues[0].get("name") if venues else "",
            "lat": float(venues[0]["location"]["latitude"]) if venues and "location" in venues[0] else None,
            "lng": float(venues[0]["location"]["longitude"]) if venues and "location" in venues[0] else None,
        })
    return events

# ----------------------------
# Sidebar
# ----------------------------
st.sidebar.header("Find Nearby (OpenStreetMap)")

if HAS_GEO:
    with st.sidebar.expander("📍 Use my device location", expanded=False):
        loc = geolocation()
        if loc and "latitude" in loc and "longitude" in loc:
            st.session_state.lat = float(loc["latitude"])
            st.session_state.lng = float(loc["longitude"])
            st.success(f"Got device location: {st.session_state.lat:.5f}, {st.session_state.lng:.5f}")

with st.sidebar.expander("🔎 Or search by city/area", expanded=False):
    city_input = st.text_input("City", value=st.session_state.city)
    area = st.text_input("Area / Locality (optional)", value="")
    if st.button("Locate"):
        query = f"{area}, {city_input}" if area else city_input
        out = geocode_address(query)
        if out:
            st.session_state.lat, st.session_state.lng, faddr = out
            st.session_state.city = city_input
            st.success(f"Centered to: {faddr}")
        else:
            st.error("Could not find that location.")

radius_km = st.sidebar.slider("Radius (km)", 1, 15, 5)
radius_m = radius_km * 1000

keywords = st.sidebar.multiselect(
    "Search for (amenities/keywords)",
    options=["school", "university", "college", "library", "training", "academy", "institute"],
    default=["school", "university", "academy"]
)

st.sidebar.subheader("Filter by Event Date")
date_filter = st.sidebar.date_input("Choose a date (leave blank for all)", value=None)

# ----------------------------
# Fetch Data
# ----------------------------
lat, lng, city = st.session_state.lat, st.session_state.lng, st.session_state.city

st.title("Nearby Training & Schools + Live Events (OpenStreetMap + Ticketmaster)")

with st.spinner("Fetching nearby places (OSM)…"):
    results = osm_places(lat, lng, radius_m, keywords)

with st.spinner("Fetching live Ticketmaster events…"):
    events = fetch_ticketmaster_events(city)

st.subheader(f"Found {len(results)} places and {len(events)} upcoming events")

# ----------------------------
# Map with Leaflet + OSM
# ----------------------------
map_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Map</title>
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
      marker.bindPopup("<b>" + p.name + "</b><br/>" + (p.addr || "") + "<br/>Amenity: " + (p.amenity || ""));
    }}
  }});

  var events = {json.dumps(events, default=str)};
  events.forEach(function(e) {{
    if (e.lat && e.lng) {{
      var marker = L.marker([e.lat, e.lng], {{icon: L.icon({{
        iconUrl: 'https://maps.gstatic.com/mapfiles/ms2/micons/orange-dot.png',
        iconSize: [25, 41], iconAnchor: [12, 41]
      }})}}).addTo(map);
      marker.bindPopup("<b>" + e.name + "</b><br/>📅 " + (e.date || 'Unspecified') + "<br/>" + (e.venue || "") + "<br/><a href='" + e.link + "' target='_blank'>More Info</a>");
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
st.subheader("Live & Upcoming Events")

if not events:
    st.info("No upcoming events found.")
else:
    if date_filter:
        filtered_events = [e for e in events if e["date"] and e["date"] == date_filter.isoformat()]
    else:
        filtered_events = events

    if not filtered_events:
        st.warning("No events found for this date.")
    else:
        for e in filtered_events:
            link_md = f"[More Info]({e['link']})" if e['link'] else ""
            venue = f"📍 {e['venue']}" if e.get("venue") else ""
            st.markdown(f"""
            **{e['name']}**  
            📅 {e['date'] if e['date'] else "Unspecified"}  
            {e['description']}  
            {venue}  
            {link_md}
            """)
