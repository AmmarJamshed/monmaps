import json
import time
from datetime import date
from typing import Dict, List, Optional, Tuple

import requests
import pandas as pd
import streamlit as st

# Optional geolocation (graceful fallback if missing)
try:
    from streamlit_geolocation import geolocation
    HAS_GEO = True
except Exception:
    HAS_GEO = False

import streamlit.components.v1 as components

# ----------------------------
# Config
# ----------------------------
st.set_page_config(page_title="Nearby Training & Schools + Events", page_icon="🗺️", layout="wide")
API_KEY = st.secrets.get("GOOGLE_MAPS_API_KEY", "")

if not API_KEY:
    st.error("Add GOOGLE_MAPS_API_KEY in .streamlit/secrets.toml to run this app.")
    st.stop()

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
    r = requests.get(url, params=params, timeout=20)
    data = r.json()
    if data.get("status") != "OK" or not data.get("results"):
        return None
    res = data["results"][0]
    loc = res["geometry"]["location"]
    return (loc["lat"], loc["lng"], res.get("formatted_address", addr))

def nearby_search(lat: float, lng: float, radius_m: int, types: List[str], keyword: Optional[str] = None, max_pages: int = 2) -> List[Dict]:
    all_results: Dict[str, Dict] = {}
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
            payload = resp.json()
            if payload.get("status") not in ("OK", "ZERO_RESULTS"):
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
            time.sleep(2)

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

with st.sidebar.expander("🔎 Or search an address/city", expanded=not got_loc):
    addr = st.text_input("Type address/city", value="Islamabad, Pakistan")
    if st.button("Locate"):
        out = geocode_address(addr)
        if out:
            lat, lng, faddr = out
            st.success(f"Centered to: {faddr}")
            got_loc = True
        else:
            st.error("Could not find that address.")

if not got_loc:
    lat, lng = 33.6844, 73.0479  # Islamabad default

radius_km = st.sidebar.slider("Radius (km)", 1, 30, 5)
radius_m = radius_km * 1000

st.sidebar.subheader("Categories")
selected = st.sidebar.multiselect(
    "Choose categories",
    options=["training_like"] + list(CATEGORIES.keys()),
    default=["training_like", "school", "university"]
)

extra_kw = st.sidebar.text_input("Extra keyword (optional)", value="")
max_pages = st.sidebar.select_slider("Pages per type", options=[1,2,3], value=2)

# ----------------------------
# Load Events (TXT instead of CSV)
# ----------------------------
@st.cache_data
def load_events() -> pd.DataFrame:
    try:
        df = pd.read_csv("events.txt")  # 👈 using .txt
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df.dropna(subset=["lat", "lng", "date"])
    except Exception:
        return pd.DataFrame(columns=["name","lat","lng","date","type","description","link"])

events = load_events()
today = pd.to_datetime(date.today())
events = events[events["date"] >= today].sort_values("date")

# ----------------------------
# Fetch Google Places
# ----------------------------
st.title("Nearby Training & Schools + Upcoming Events")
st.caption("Live Google Places data + custom events overlay (from events.txt)")

with st.spinner("Searching Google Places…"):
    results = nearby_search(lat, lng, radius_m, selected, keyword=extra_kw.strip() or None, max_pages=max_pages)

def rating_key(p):
    return (-p.get("rating", 0), -p.get("user_ratings_total", 0))

results_sorted = sorted(results, key=rating_key)

st.subheader(f"Found {len(results_sorted)} places and {len(events)} upcoming events")

# ----------------------------
# Prepare markers
# ----------------------------
def to_marker(p: Dict) -> Dict:
    loc = p.get("geometry", {}).get("location", {})
    return {
        "lat": loc.get("lat"), "lng": loc.get("lng"),
        "name": p.get("name","Untitled"),
        "addr": p.get("vicinity") or p.get("formatted_address") or "",
        "rating": p.get("rating",""), "total": p.get("user_ratings_total",""),
        "open": fmt_opening_hours(p.get("opening_hours", {})),
        "link": gmaps_place_link(p.get("place_id",""))
    }

place_markers = [to_marker(p) for p in results_sorted if p.get("geometry",{}).get("location")]

event_markers = []
for _, e in events.iterrows():
    event_markers.append({
        "lat": e["lat"], "lng": e["lng"],
        "name": e["name"], "addr": e.get("description",""),
        "date": str(e["date"].date()), "link": e.get("link","")
    })

# ----------------------------
# Render map
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
    const places = {json.dumps(place_markers)};
    const events = {json.dumps(event_markers)};
    const map = new google.maps.Map(document.getElementById('map'), {{
      center: center, zoom: {14 if radius_km<=5 else 12}, mapTypeControl:false
    }});

    new google.maps.Marker({{
      position: center, map, title:"You are here",
      icon:{{path:google.maps.SymbolPath.CIRCLE,scale:6,fillColor:"#2ecc71",fillOpacity:1,strokeWeight:2,strokeColor:"#1e824c"}}
    }});

    const infow = new google.maps.InfoWindow();

    places.forEach(m => {{
      const mk = new google.maps.Marker({{position:{{lat:m.lat,lng:m.lng}},map,title:m.name}});
      const html = `<b>${{m.name}}</b><br/>${{m.addr}}<br/>⭐ ${{m.rating}} (${{m.total}})<br/>${{m.open}}<br/><a href="${{m.link}}" target="_blank">Open in Google Maps</a>`;
      mk.addListener('click',()=>{{infow.setContent(html);infow.open({{anchor:mk,map}});}});
    }});

    events.forEach(e => {{
      const mk = new google.maps.Marker({{
        position:{{lat:e.lat,lng:e.lng}}, map, title:e.name,
        icon: "http://maps.google.com/mapfiles/ms/icons/orange-dot.png"
      }});
      const html = `<b>${{e.name}}</b><br/>📅 ${{e.date}}<br/>${{e.addr}}<br/><a href="${{e.link}}" target="_blank">More info</a>`;
      mk.addListener('click',()=>{{infow.setContent(html);infow.open({{anchor:mk,map}});}});
    }});
  </script></body>
</html>
"""

components.html(MAP_HTML, height=560, scrolling=False)

# ----------------------------
# List view
# ----------------------------
st.subheader("Upcoming Events")
if events.empty:
    st.info("No upcoming events found in events.txt")
else:
    for _, e in events.iterrows():
        st.markdown(f"""
        **{e['name']}**  
        📅 {e['date'].date()}  
        {e['description']}  
        [More Info]({e['link']})
        """)
