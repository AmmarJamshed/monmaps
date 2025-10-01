import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

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

def fmt_opening_hours(ph: Dict) -> str:
    if not ph:
        return ""
    return "Open now" if ph.get("open_now") else "Closed now"

def gmaps_place_link(place_id: str) -> str:
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"

# ----------------------------
# Eventbrite API Events
# ----------------------------
def fetch_eventbrite_events(city: str, keyword: str = "training", max_results: int = 15):
    url = "https://www.eventbriteapi.com/v3/events/search/"
    headers = {"Authorization": f"Bearer {EVENTBRITE_KEY}"}
    params = {
        "q": keyword,
        "location.address": city,
        "sort_by": "date"
    }
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    data = resp.json()

    events = []
    for ev in data.get("events", [])[:max_results]:
        events.append({
            "name": ev["name"]["text"],
            "description": ev["description"]["text"] if ev.get("description") else "",
            "link": ev["url"],
            "date": ev["start"]["local"][:10] if ev.get("start") else "Unspecified"
        })
    return events

# ----------------------------
# Sidebar controls
# ----------------------------
st.sidebar.header("Find Nearby (Google + Eventbrite)")

city = st.sidebar.text_input("City", value="Islamabad")
keyword = st.sidebar.text_input("Search Keyword", value="training")
area = st.sidebar.text_input("Area / Locality (optional)", value="")

if st.sidebar.button("Locate"):
    query = f"{area}, {city}" if area else city
    out = geocode_address(query)
    if out:
        lat, lng, faddr = out
        st.success(f"Centered to: {faddr}")
    else:
        st.error("Could not find that location.")
else:
    lat, lng = 33.6844, 73.0479  # Default Islamabad

radius_km = st.sidebar.slider("Radius (km)", 1, 15, 3)

# Event date filter
st.sidebar.subheader("Filter by Event Date")
date_filter = st.sidebar.date_input("Choose a date (leave blank for all)", value=None)

# ----------------------------
# Fetch Events
# ----------------------------
st.title("Nearby Trainings, Workshops + Live Events")
st.caption("Using Eventbrite API for real upcoming events.")

with st.spinner("Fetching events from Eventbrite…"):
    events = fetch_eventbrite_events(city, keyword)

st.subheader(f"Found {len(events)} upcoming events")

# ----------------------------
# Event Markers
# ----------------------------
event_markers = []
geo = geocode_address(city)
if geo:
    lat_ev, lng_ev, _ = geo
    for e in events:
        icon = "http://maps.google.com/mapfiles/ms/icons/orange-dot.png"
        event_markers.append({
            "lat": lat_ev, "lng": lng_ev,
            "name": e["name"],
            "addr": e.get("description", ""),
            "date": e["date"],
            "link": e.get("link", ""),
            "icon": icon
        })

# ----------------------------
# Map Rendering
# ----------------------------
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
    const events = {json.dumps(event_markers)};
    events.forEach(e => {{
      const mk = new google.maps.Marker({{
        position:{{lat:e.lat,lng:e.lng}}, map, title:e.name,
        icon: e.icon
      }});
      const html = `<b>${{e.name}}</b><br/>📅 ${{e.date}}<br/>${{e.addr}}<br/>` 
                 + (e.link ? `<a href="${{e.link}}" target="_blank">More info</a>` : "");
      mk.addListener('click',()=>{{infow.setContent(html);infow.open({{anchor:mk,map}});}});  
    }});
  </script></body>
</html>
"""
components.html(MAP_HTML, height=560, scrolling=False)

# ----------------------------
# Calendar-Style Event List
# ----------------------------
st.subheader("Live & Upcoming Events (Calendar View)")

if not events:
    st.info("No upcoming events found.")
else:
    if date_filter:
        filtered_events = [e for e in events if e["date"].startswith(str(date_filter))]
    else:
        filtered_events = events

    if not filtered_events:
        st.warning("No events found for this date.")
    else:
        current_date = None
        for e in filtered_events:
            d = e["date"] if e["date"] != "Unspecified" else None
            if d and d != current_date:
                st.markdown(f"### 📅 {datetime.fromisoformat(d).strftime('%A, %d %B %Y')}")
                current_date = d
            elif not d and current_date != "Unspecified":
                st.markdown("### ❓ Unspecified Date")
                current_date = "Unspecified"

            link_md = f"[More Info]({e['link']})" if e['link'] else ""
            st.markdown(f"""
            **{e['name']}**  
            {e['description']}  
            {link_md}
            """)
