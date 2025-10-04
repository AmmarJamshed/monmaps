import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
from dateutil import parser

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------
st.set_page_config(page_title="Nearby Training & Schools + Events", page_icon="🗺️", layout="wide")

SERP_API_KEY = st.secrets.get("SERP_API_KEY", "")
TICKETMASTER_KEY = st.secrets.get("TICKETMASTER_API_KEY", "")

if not SERP_API_KEY or not TICKETMASTER_KEY:
    st.error("Add SERP_API_KEY and TICKETMASTER_API_KEY in .streamlit/secrets.toml to run this app.")
    st.stop()

refresh_interval = st.sidebar.slider("Auto-refresh interval (minutes)", 1, 30, 5)
st_autorefresh(interval=refresh_interval * 60 * 1000, key="auto_refresh")

# --------------------------------------------------
# UTILITIES
# --------------------------------------------------
try:
    from streamlit_geolocation import geolocation
    HAS_GEO = True
except Exception:
    HAS_GEO = False

TRAINING_KEYWORDS = [
    "training center", "academy", "bootcamp", "coaching center",
    "institute", "skill development", "IELTS", "Data Science", "Python"
]

# --------------------------------------------------
# SAFE OPENSTREETMAP GEOCODER
# --------------------------------------------------
def geocode_address(addr: str, country: Optional[str] = None) -> Optional[Tuple[float, float, str]]:
    """Safely geocode using OpenStreetMap (Nominatim)."""
    query = f"{addr}, {country}" if country else addr
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "json", "limit": 1}

    try:
        r = requests.get(url, params=params, timeout=15, headers={"User-Agent": "MonMapsApp"})
        r.raise_for_status()
        data = r.json()

        if not data or not isinstance(data, list):
            return None

        loc = data[0]
        lat = float(loc.get("lat"))
        lon = float(loc.get("lon"))
        display_name = loc.get("display_name", query)
        return lat, lon, display_name

    except requests.exceptions.RequestException as e:
        st.warning(f"⚠️ Could not fetch location from OpenStreetMap: {e}")
        return None
    except Exception:
        return None

# --------------------------------------------------
# SERPAPI SEARCH (OpenStreetMap-BASED)
# --------------------------------------------------
def fetch_nearby_places(lat: float, lng: float, query: str, radius_m: int = 2000, max_results: int = 10):
    url = "https://serpapi.com/search"
    params = {
        "engine": "google_maps",
        "q": query,
        "ll": f"@{lat},{lng},{radius_m}m",
        "type": "search",
        "api_key": SERP_API_KEY
    }
    try:
        resp = requests.get(url, params=params, timeout=20)
        data = resp.json()
    except Exception:
        return []

    results = []
    for place in data.get("local_results", [])[:max_results]:
        results.append({
            "name": place.get("title"),
            "address": place.get("address"),
            "gps": place.get("gps_coordinates", {}),
            "rating": place.get("rating"),
            "link": place.get("link")
        })
    return results

# --------------------------------------------------
# TICKETMASTER EVENTS
# --------------------------------------------------
def fetch_ticketmaster_events(city: str, max_results: int = 20):
    url = "https://app.ticketmaster.com/discovery/v2/events.json"
    params = {
        "apikey": TICKETMASTER_KEY,
        "city": city,
        "size": max_results,
        "sort": "date,asc"
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
    except Exception:
        return []

    events = []
    for ev in data.get("_embedded", {}).get("events", []):
        ev_date = None
        if ev.get("dates", {}).get("start", {}).get("localDate"):
            try:
                ev_date = parser.parse(ev["dates"]["start"]["localDate"]).date()
            except:
                pass
        venues = ev.get("_embedded", {}).get("venues", [])
        lat, lng = None, None
        if venues and venues[0].get("location"):
            lat = float(venues[0]["location"]["latitude"])
            lng = float(venues[0]["location"]["longitude"])
        events.append({
            "name": ev.get("name"),
            "description": ev.get("info", "") or ev.get("pleaseNote", ""),
            "link": ev.get("url", ""),
            "date": ev_date,
            "venue": venues[0].get("name") if venues else "",
            "lat": lat,
            "lng": lng
        })
    return events

# --------------------------------------------------
# SIDEBAR WITH SESSION STATE
# --------------------------------------------------
if "location" not in st.session_state:
    st.session_state.location = {
        "lat": 33.6844, "lng": 73.0479,
        "city": "Islamabad", "faddr": "Islamabad, Pakistan"
    }

with st.sidebar.expander("🔎 Search by City / Area", expanded=True):
    city_input = st.text_input("City", value=st.session_state.location["city"])
    area_input = st.text_input("Area / Locality (optional)", value="")
    country_input = st.text_input("Country", value="Pakistan")
    if st.button("Locate"):
        query = f"{area_input}, {city_input}" if area_input else city_input
        out = geocode_address(query, country=country_input)
        if out:
            lat, lng, faddr = out
            st.session_state.location = {
                "lat": lat, "lng": lng,
                "city": city_input.title(),
                "faddr": faddr
            }
            st.success(f"Centered to: {faddr}")
        else:
            st.error("Could not find that location.")

lat = st.session_state.location["lat"]
lng = st.session_state.location["lng"]
city = st.session_state.location["city"]

radius_km = st.sidebar.slider("Radius (km)", 1, 15, 5)
radius_m = radius_km * 1000

st.sidebar.subheader("Search Focus")
selected_kw = st.sidebar.multiselect(
    "Choose keywords",
    options=TRAINING_KEYWORDS,
    default=["Data Science", "Python"]
)

st.sidebar.subheader("Filter by Event Date")
date_filter = st.sidebar.date_input("Choose a date (optional)", value=None)

# --------------------------------------------------
# FETCH DATA
# --------------------------------------------------
st.title("Nearby Training & Schools + Live Events")
st.caption("Free version powered by OpenStreetMap (for geocoding) + SerpAPI (for nearby search) + Ticketmaster (for events).")

with st.spinner("Fetching nearby places…"):
    results = fetch_nearby_places(lat, lng, "training center")

with st.spinner("Fetching live Ticketmaster events…"):
    events = fetch_ticketmaster_events(city)

st.subheader(f"Found {len(results)} nearby institutions and {len(events)} upcoming events")

# --------------------------------------------------
# MAP DISPLAY (OpenStreetMap + Leaflet)
# --------------------------------------------------
MAP_HTML = f"""
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>html, body, #map {{ height: 100%; margin: 0; padding: 0; }}</style>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  </head>
  <body>
    <div id="map"></div>
    <script>
      var map = L.map('map').setView([{lat}, {lng}], 13);
      L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
        maxZoom: 19,
        attribution: '© OpenStreetMap contributors'
      }}).addTo(map);

      var userMarker = L.marker([{lat}, {lng}]).addTo(map)
        .bindPopup('You are here').openPopup();

      var places = {json.dumps(results)};
      places.forEach(function(p) {{
        if (p.gps && p.gps.latitude && p.gps.longitude) {{
          var m = L.marker([p.gps.latitude, p.gps.longitude]).addTo(map);
          var html = `<b>${{p.name}}</b><br>${{p.address}}<br>⭐ ${{p.rating || 'N/A'}}<br><a href="${{p.link}}" target="_blank">Open in Maps</a>`;
          m.bindPopup(html);
        }}
      }});
    </script>
  </body>
</html>
"""
components.html(MAP_HTML, height=520, scrolling=False)

# --------------------------------------------------
# EVENT LIST (IMPROVED PRESENTATION)
# --------------------------------------------------
st.subheader(f"🎟️ Live & Upcoming Events in {city}")

if not events:
    st.info("No upcoming events found.")
else:
    filtered_events = events
    if date_filter:
        filtered_events = [e for e in events if e["date"] and e["date"] == date_filter]

    if not filtered_events:
        st.warning("No events found for this date.")
    else:
        for e in filtered_events:
            gmap_url = (
                f"https://www.google.com/maps/search/?api=1&query={e['lat']},{e['lng']}"
                if e.get("lat") and e.get("lng")
                else ""
            )
            book_link = f"[🎫 Book Event Here]({e['link']})" if e.get("link") else ""
            map_link = f"[📍 View on Google Maps]({gmap_url})" if gmap_url else ""

            st.markdown(f"""
<div style="background:#f9f9ff; padding:15px; border-radius:10px; margin-bottom:10px; border:1px solid #e0e0e0;">
  <h4 style="margin-bottom:5px; color:#1a73e8;">{e['name']}</h4>
  <p>📅 <b>{e['date'] if e['date'] else 'Unspecified'}</b></p>
  <p>🏛️ {e.get('venue','')}<br>🗺️ {city}</p>
  <p>{e.get('description','')}</p>
  {book_link}<br>{map_link}
</div>
""", unsafe_allow_html=True)
