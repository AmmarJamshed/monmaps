import json
import requests
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime
from dateutil import parser
from streamlit_autorefresh import st_autorefresh

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------
st.set_page_config(page_title="MonMaps — Training & Events Near You", page_icon="🗺️", layout="wide")

AWS_API_KEY = st.secrets.get("AWS_LOCATION_API_KEY", "")
AWS_REGION = st.secrets.get("AWS_REGION", "ap-south-1")  # ✅ Mumbai
MAP_NAME = st.secrets.get("MAP_NAME", "MonMapsMap")
PLACE_INDEX = st.secrets.get("PLACE_INDEX", "MonMapsPlaces")
ROUTE_CALCULATOR = st.secrets.get("ROUTE_CALCULATOR", "MonMapsRoutes")
TICKETMASTER_KEY = st.secrets.get("TICKETMASTER_API_KEY", "")

if not AWS_API_KEY:
    st.error("Please set AWS_LOCATION_API_KEY and other variables in .streamlit/secrets.toml")
    st.stop()

refresh_interval = st.sidebar.slider("Auto-refresh interval (minutes)", 1, 30, 5)
st_autorefresh(interval=refresh_interval * 60 * 1000, key="auto_refresh")

# --------------------------------------------------
# CONSTANTS
# --------------------------------------------------
TRAINING_KEYWORDS = [
    "training center", "academy", "bootcamp", "coaching center",
    "institute", "skill development", "IELTS", "Data Science", "Python"
]

# --------------------------------------------------
# FETCH NEARBY PLACES (AMAZON LOCATION)
# --------------------------------------------------
def fetch_nearby_places(lat: float, lng: float, query: str, max_results: int = 10):
    """Search for places using Amazon Location Service (Places API)."""
    url = f"https://places.geo.{AWS_REGION}.amazonaws.com/places/v0/indexes/{PLACE_INDEX}/search-text"
    headers = {
        "X-Amz-Api-Key": AWS_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "Text": query,
        "BiasPosition": [lng, lat],
        "MaxResults": max_results
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        data = resp.json()
    except Exception as e:
        st.warning(f"⚠️ Could not fetch places: {e}")
        return []

    results = []
    for p in data.get("Results", []):
        place = p.get("Place", {})
        coords = place.get("Geometry", {}).get("Point", [None, None])
        if coords and len(coords) == 2:
            results.append({
                "type": "institute",
                "name": place.get("Label", "Unknown"),
                "address": place.get("AddressNumber", "") + " " + place.get("Street", ""),
                "gps": {"latitude": coords[1], "longitude": coords[0]},
                "rating": "N/A",
                "link": f"https://www.google.com/maps?q={coords[1]},{coords[0]}"
            })
    return results

# --------------------------------------------------
# CALCULATE ROUTE DISTANCE / TIME (AMAZON LOCATION)
# --------------------------------------------------
def calculate_route(start: tuple, end: tuple):
    """Calculate distance and duration between two points."""
    url = f"https://routes.geo.{AWS_REGION}.amazonaws.com/routes/v0/calculators/{ROUTE_CALCULATOR}/calculate/route"
    headers = {
        "X-Amz-Api-Key": AWS_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "DeparturePositions": [[start[1], start[0]]],
        "DestinationPositions": [[end[1], end[0]]],
        "TravelMode": "Car"
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        data = resp.json()
        if "Routes" in data and len(data["Routes"]) > 0:
            summary = data["Routes"][0]["Summary"]
            return round(summary["Distance"], 2), round(summary["DurationSeconds"] / 60, 1)
    except Exception as e:
        st.warning(f"⚠️ Route error: {e}")
    return None, None

# --------------------------------------------------
# FETCH TICKETMASTER EVENTS
# --------------------------------------------------
def fetch_ticketmaster_events(city: str, max_results: int = 20):
    url = "https://app.ticketmaster.com/discovery/v2/events.json"
    params = {"apikey": TICKETMASTER_KEY, "city": city, "size": max_results, "sort": "date,asc"}
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
            "type": "event",
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
# SIDEBAR INPUTS
# --------------------------------------------------
if "location" not in st.session_state:
    st.session_state.location = {
        "lat": 19.0760, "lng": 72.8777,
        "city": "Mumbai", "faddr": "Mumbai, India"
    }

with st.sidebar.expander("🔎 Search by City / Area", expanded=True):
    city_input = st.text_input("City", value=st.session_state.location["city"])
    lat = st.number_input("Latitude", value=st.session_state.location["lat"], format="%.6f")
    lng = st.number_input("Longitude", value=st.session_state.location["lng"], format="%.6f")
    if st.button("Update Location"):
        st.session_state.location = {"lat": lat, "lng": lng, "city": city_input, "faddr": city_input}
        st.success(f"Location updated to {city_input}")

radius_km = st.sidebar.slider("Radius (km)", 1, 15, 5)
st.sidebar.subheader("Search Keywords")
selected_kw = st.sidebar.multiselect("Choose keywords", options=TRAINING_KEYWORDS, default=["Data Science", "Python"])
st.sidebar.subheader("Filter by Event Date")
date_filter = st.sidebar.date_input("Choose a date (optional)", value=None)

lat = st.session_state.location["lat"]
lng = st.session_state.location["lng"]
city = st.session_state.location["city"]

# --------------------------------------------------
# FETCH DATA
# --------------------------------------------------
st.title("🗺️ MonMaps — Nearby Training & Events (AWS + Ticketmaster)")
st.caption("Amazon Location Service for Maps & Routing + Ticketmaster API for Live Events")

with st.spinner("Fetching nearby institutes…"):
    results = []
    for kw in selected_kw:
        results.extend(fetch_nearby_places(lat, lng, kw))

with st.spinner("Fetching live events…"):
    events = fetch_ticketmaster_events(city)

st.subheader(f"Found {len(results)} institutes and {len(events)} events in {city}")

# --------------------------------------------------
# COMBINE ALL LOCATIONS FOR MAP
# --------------------------------------------------
all_points = []
for r in results:
    all_points.append({
        "type": "institute",
        "name": r["name"],
        "lat": r["gps"]["latitude"],
        "lng": r["gps"]["longitude"],
        "popup": f"<b>{r['name']}</b><br>{r['address']}<br><a href='{r['link']}' target='_blank'>Open</a>"
    })
for e in events:
    if e.get("lat") and e.get("lng"):
        dist, time = calculate_route((lat, lng), (e["lat"], e["lng"]))
        popup = f"<b>{e['name']}</b><br>📅 {e['date']}<br>🏛️ {e['venue']}<br>🚗 {dist} km ⏱️ {time} min<br><a href='{e['link']}' target='_blank'>Book</a>"
        all_points.append({
            "type": "event",
            "name": e["name"],
            "lat": e["lat"],
            "lng": e["lng"],
            "popup": popup
        })

# --------------------------------------------------
# MAP DISPLAY (AMAZON LOCATION + MAPLIBRE)
# --------------------------------------------------
MAP_HTML = f"""
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>MonMaps</title>
    <meta name="viewport" content="initial-scale=1,maximum-scale=1,user-scalable=no" />
    <script src="https://unpkg.com/maplibre-gl@2.4.0/dist/maplibre-gl.js"></script>
    <link href="https://unpkg.com/maplibre-gl@2.4.0/dist/maplibre-gl.css" rel="stylesheet" />
    <style>body,html,#map{{height:100%;margin:0;padding:0;}}</style>
  </head>
  <body>
    <div id="map"></div>
    <script>
      const map = new maplibregl.Map({{
        container: 'map',
        style: 'https://maps.geo.{AWS_REGION}.amazonaws.com/maps/v0/maps/{MAP_NAME}/style-descriptor',
        center: [{lng}, {lat}],
        zoom: 11,
        transformRequest: (url, resourceType) => {{
          if (url.includes('amazonaws.com')) {{
            return {{ url: url, headers: {{ 'X-Amz-Api-Key': '{AWS_API_KEY}' }} }};
          }}
          return {{ url }};
        }}
      }});

      const userMarker = new maplibregl.Marker({{color:'#007AFF'}})
        .setLngLat([{lng}, {lat}])
        .setPopup(new maplibregl.Popup().setText('You are here'))
        .addTo(map);

      const points = {json.dumps(all_points)};
      points.forEach(p => {{
        const color = p.type === 'event' ? '#E91E63' : '#4CAF50';
        const m = new maplibregl.Marker({{color}})
          .setLngLat([p.lng, p.lat])
          .setPopup(new maplibregl.Popup().setHTML(p.popup))
          .addTo(map);
      }});
    </script>
  </body>
</html>
"""
components.html(MAP_HTML, height=540, scrolling=False)
