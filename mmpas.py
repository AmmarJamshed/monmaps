import json
from datetime import datetime
from dateutil import parser
import requests
import boto3
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------
st.set_page_config(page_title="MonMaps — Training & Events (AWS + Ticketmaster)", page_icon="🗺️", layout="wide")

# Load secrets
AWS_REGION = st.secrets.get("AWS_REGION", "ap-south-1")
MAP_NAME = st.secrets.get("MAP_NAME", "")
PLACE_INDEX = st.secrets.get("PLACE_INDEX", "")
ROUTE_CALCULATOR = st.secrets.get("ROUTE_CALCULATOR", "")
TICKETMASTER_KEY = st.secrets.get("TICKETMASTER_API_KEY", "")

# Create boto3 client for Amazon Location
try:
    location_client = boto3.client("location", region_name=AWS_REGION)
except Exception as e:
    st.error(f"❌ Could not initialize AWS Location client. Error: {e}")
    st.stop()

refresh_interval = st.sidebar.slider("Auto-refresh interval (minutes)", 1, 30, 5)
st_autorefresh(interval=refresh_interval * 60 * 1000, key="auto_refresh")

# --------------------------------------------------
# UTILITIES
# --------------------------------------------------
TRAINING_KEYWORDS = [
    "training", "academy", "bootcamp", "coaching", "education",
    "institute", "skill development", "Data Science", "Python"
]

def fetch_aws_places(text, lat, lng, max_results=50):
    """Query AWS Location Place Index using boto3 (Signature V4)"""
    try:
        response = location_client.search_place_index_for_text(
            IndexName=PLACE_INDEX,
            Text=text,
            BiasPosition=[lng, lat],
            MaxResults=max_results
        )
        places = []
        for item in response.get("Results", []):
            place = item.get("Place", {})
            pos = place.get("Geometry", {}).get("Point", [])
            if len(pos) == 2:
                places.append({
                    "name": place.get("Label", "Unnamed"),
                    "address": place.get("AddressNumber", "") + " " + place.get("Street", ""),
                    "lat": pos[1],
                    "lng": pos[0]
                })
        return places
    except Exception as e:
        st.warning(f"⚠️ AWS Places error: {e}")
        return []

def fetch_ticketmaster_events(city, max_results=20):
    """Fetch events from Ticketmaster API"""
    if not TICKETMASTER_KEY:
        st.warning("⚠️ No Ticketmaster API key found.")
        return []
    url = "https://app.ticketmaster.com/discovery/v2/events.json"
    params = {"apikey": TICKETMASTER_KEY, "city": city, "size": max_results, "sort": "date,asc"}
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()

        if "_embedded" not in data:
            st.info(f"ℹ️ No Ticketmaster events found for {city}. Raw response:\n{data}")
            return []

        events = []
        for ev in data["_embedded"]["events"]:
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
    except Exception as e:
        st.warning(f"⚠️ Ticketmaster error: {e}")
        return []

def fetch_route(start_lat, start_lng, end_lat, end_lng):
    """Fetch driving route using AWS SDK (optional)"""
    try:
        response = location_client.calculate_route(
            CalculatorName=ROUTE_CALCULATOR,
            DeparturePosition=[start_lng, start_lat],
            DestinationPosition=[end_lng, end_lat],
            TravelMode="Car"
        )
        return response
    except Exception as e:
        st.warning(f"⚠️ Route fetch failed: {e}")
        return {}

# --------------------------------------------------
# SIDEBAR
# --------------------------------------------------
if "location" not in st.session_state:
    st.session_state.location = {"lat": 19.0760, "lng": 72.8777, "city": "Mumbai"}

with st.sidebar.expander("🔍 Search by City / Area", expanded=True):
    city_input = st.text_input("City", value=st.session_state.location["city"])
    lat_input = st.number_input("Latitude", value=st.session_state.location["lat"])
    lng_input = st.number_input("Longitude", value=st.session_state.location["lng"])
    if st.button("Update Location"):
        st.session_state.location = {"lat": lat_input, "lng": lng_input, "city": city_input}
        st.success(f"✅ Location updated to {city_input}")

radius_km = st.sidebar.slider("Radius (km)", 1, 15, 5)
selected_kw = st.sidebar.multiselect("Search Keywords", TRAINING_KEYWORDS, default=["Data Science", "Python"])
date_filter = st.sidebar.date_input("Filter by Event Date", value=None)

# --------------------------------------------------
# FETCH DATA
# --------------------------------------------------
lat = st.session_state.location["lat"]
lng = st.session_state.location["lng"]
city = st.session_state.location["city"]

st.title("🗺️ MonMaps — Nearby Training & Events (AWS + Ticketmaster)")
st.caption("Powered by Amazon Location Service (HERE) + Ticketmaster")

with st.spinner("🔎 Searching AWS Places..."):
    results = []
    for kw in selected_kw:
        results.extend(fetch_aws_places(kw, lat, lng))

with st.spinner("🎫 Fetching Ticketmaster events..."):
    events = fetch_ticketmaster_events(city)

st.subheader(f"📍 Found {len(results)} institutes and {len(events)} events in {city}")

# --------------------------------------------------
# MAP DISPLAY
# --------------------------------------------------
MAP_HTML = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>html,body,#map{{height:100%;margin:0;padding:0}}</style>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
</head>
<body>
<div id="map"></div>
<script>
var map = L.map('map').setView([{lat},{lng}], 13);
L.tileLayer('https://maps.geo.{AWS_REGION}.amazonaws.com/maps/v0/maps/{MAP_NAME}/tiles/{{z}}/{{x}}/{{y}}?key=YOUR_MAP_KEY', {{
    maxZoom: 18
}}).addTo(map);

L.marker([{lat},{lng}]).addTo(map).bindPopup("📍 You are here").openPopup();
var places = {json.dumps(results)};
places.forEach(p => {{
  var m = L.marker([p.lat, p.lng]).addTo(map);
  var html = `<b>${{p.name}}</b><br>${{p.address || ''}}<br>
  <a href='https://www.google.com/maps?q=${{p.lat}},${{p.lng}}' target='_blank'>Open in Google Maps</a>`;
  m.bindPopup(html);
}});
</script>
</body></html>
"""
components.html(MAP_HTML, height=520, scrolling=False)

# --------------------------------------------------
# EVENT LIST
# --------------------------------------------------
st.subheader(f"🎟️ Live & Upcoming Events in {city}")

if not events:
    st.info("ℹ️ No upcoming events found for this location. Try searching a larger city (e.g., New York, London).")
else:
    filtered_events = [e for e in events if not date_filter or (e["date"] and e["date"] == date_filter)]
    for e in filtered_events:
        gmap_url = f"https://www.google.com/maps/search/?api=1&query={e['lat']},{e['lng']}" if e.get("lat") else ""
        st.markdown(f"""
        <div style='background:#f9f9ff;padding:15px;border-radius:10px;margin-bottom:10px;border:1px solid #e0e0e0;'>
        <h4 style='color:#1a73e8;'>{e['name']}</h4>
        <p>📅 {e['date'] or 'Unspecified'} | 🏛️ {e.get('venue','')}</p>
        <p>{e.get('description','')}</p>
        <a href='{e['link']}' target='_blank'>🎫 View Event</a> |
        <a href='{gmap_url}' target='_blank'>📍 Map</a>
        </div>
        """, unsafe_allow_html=True)
