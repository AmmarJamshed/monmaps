# app.py
import json
import time
from datetime import date
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
import pandas as pd
import streamlit as st

# Optional geolocation (graceful fallback if missing)
try:
    from streamlit_geolocation import geolocation
    HAS_GEO = True
except Exception:
    HAS_GEO = False

from bs4 import BeautifulSoup
import streamlit.components.v1 as components

# ----------------------------
# Config
# ----------------------------
st.set_page_config(page_title="Nearby Training & Schools + Events (auto-linker)", page_icon="🗺️", layout="wide")
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

# Keywords used to detect event pages on a domain/homepage
EVENT_KEYWORDS = [
    "event", "events", "workshop", "workshops", "admission", "apply", "register",
    "course", "courses", "program", "programme", "bootcamp", "training", "seminar"
]

# HTTP headers for polite scraping
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NearbyEventsBot/1.0; +https://example.com/contact)"
}

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

def place_details(place_id: str) -> Dict:
    """
    Calls Place Details to get website (and other useful fields).
    Cached to avoid repeated calls.
    """
    if not place_id:
        return {}
    return _cached_place_details(place_id)

@st.cache_data(show_spinner=False, ttl=60*60*24)
def _cached_place_details(place_id: str) -> Dict:
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {"place_id": place_id, "fields": "name,website,url", "key": API_KEY}
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data.get("status") == "OK":
            return data.get("result", {})
    except Exception:
        pass
    return {}

def fmt_opening_hours(ph: Dict) -> str:
    if not ph:
        return ""
    return "Open now" if ph.get("open_now") else "Closed now"

def gmaps_place_link(place_id: str) -> str:
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"

# ----------------------------
# Site scraping helpers
# ----------------------------
@st.cache_data(show_spinner=False, ttl=60*60*24)
def find_event_links_on_site(base_url: str, max_links: int = 5) -> List[str]:
    """
    Fetch base_url (homepage) and scan anchors for event-like keywords.
    Returns a list of absolute URLs (deduped).
    """
    links = []
    try:
        # Normalize url (ensure scheme)
        if not urlparse(base_url).scheme:
            base_url = "http://" + base_url
        resp = requests.get(base_url, headers=REQUEST_HEADERS, timeout=8)
        html = resp.text
        soup = BeautifulSoup(html, "lxml")
        anchors = soup.find_all("a", href=True)
        for a in anchors:
            href = a["href"].strip()
            text = (a.get_text(" ", strip=True) or "").lower()
            href_l = href.lower()
            # Skip mailto / javascript
            if href_l.startswith("mailto:") or href_l.startswith("javascript:"):
                continue
            # Build absolute URL
            abs_url = urljoin(resp.url, href)
            # quick keyword check in href or anchor text
            if any(k in href_l for k in EVENT_KEYWORDS) or any(k in text for k in EVENT_KEYWORDS):
                if abs_url not in links:
                    links.append(abs_url)
            if len(links) >= max_links:
                break
        # If none found, try searching for common paths (heuristic)
        if not links:
            heuristics = ["/events", "/events/", "/workshop", "/workshops", "/admissions", "/admission", "/apply", "/training"]
            for h in heuristics:
                candidate = urljoin(resp.url, h)
                try:
                    r2 = requests.head(candidate, headers=REQUEST_HEADERS, timeout=5, allow_redirects=True)
                    if r2.status_code == 200:
                        links.append(candidate)
                        break
                except Exception:
                    continue
    except Exception:
        return []
    return links

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

# NEW: toggle to auto-search event links
auto_search_links = st.sidebar.checkbox("Auto-search event links on place websites", value=True)
st.sidebar.caption("If enabled, the app will call Place Details and attempt to scrape each place's website for event/admission links. This increases API usage and network calls but may find direct event pages.")

# ----------------------------
# Load Events (TXT instead of CSV) - still supported as fallback
# ----------------------------
@st.cache_data
def load_events() -> pd.DataFrame:
    try:
        df = pd.read_csv("events.txt")
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
st.title("Nearby Training & Schools + Upcoming Events (auto-linker)")
st.caption("Live Google Places data + automatic attempt to find event/admission links on each place's website (best-effort).")

with st.spinner("Searching Google Places…"):
    results = nearby_search(lat, lng, radius_m, selected, keyword=extra_kw.strip() or None, max_pages=max_pages)

def rating_key(p):
    return (-p.get("rating", 0), -p.get("user_ratings_total", 0))

results_sorted = sorted(results, key=rating_key)

st.subheader(f"Found {len(results_sorted)} places and {len(events)} upcoming events (from events.txt)")

# ----------------------------
# Prepare markers and attempt to auto-find event links
# ----------------------------
def to_marker(p: Dict, found_event_link: Optional[str] = None) -> Dict:
    loc = p.get("geometry", {}).get("location", {})
    return {
        "lat": loc.get("lat"), "lng": loc.get("lng"),
        "name": p.get("name","Untitled"),
        "addr": p.get("vicinity") or p.get("formatted_address") or "",
        "rating": p.get("rating",""), "total": p.get("user_ratings_total",""),
        "open": fmt_opening_hours(p.get("opening_hours", {})),
        "gmaps_link": gmaps_place_link(p.get("place_id","")),
        "event_link": found_event_link or ""  # auto-found event/admission link if any
    }

place_markers = []
# We'll rate-limit the place-details + site-scrape calls and cache via @st.cache_data above.
for p in results_sorted:
    place_id = p.get("place_id")
    found = ""
    if auto_search_links and place_id:
        # 1) Try Place Details -> website
        details = place_details(place_id)
        website = details.get("website") or details.get("url")  # url can be maps url, website preferred
        # If website exists, try scraping it
        if website:
            found_links = find_event_links_on_site(website, max_links=3)
            if found_links:
                found = found_links[0]  # pick first found link
        # small delay to be polite (and avoid huge burst)
        time.sleep(0.15)
    place_markers.append(to_marker(p, found_event_link=found))

# Also include events from events.txt as orange markers
event_markers = []
for _, e in events.iterrows():
    event_markers.append({
        "lat": float(e["lat"]), "lng": float(e["lng"]),
        "name": e["name"], "addr": e.get("description",""),
        "date": str(e["date"].date()), "link": e.get("link","")
    })

# ----------------------------
# Render map with both place markers and event markers (JS)
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

    // Places (blue default marker)
    places.forEach(m => {{
      const mk = new google.maps.Marker({{position:{{lat:m.lat,lng:m.lng}},map,title:m.name}});
      const htmlParts = [];
      htmlParts.push(`<b>${{m.name}}</b>`);
      if(m.addr) htmlParts.push(`${{m.addr}}`);
      if(m.rating) htmlParts.push(`⭐ ${{m.rating}} (${{m.total}})`);
      if(m.open) htmlParts.push(`${{m.open}}`);
      if(m.event_link) htmlParts.push(`<a href="${{m.event_link}}" target="_blank">Event / Admission page</a>`);
      if(m.gmaps_link) htmlParts.push(`<a href="${{m.gmaps_link}}" target="_blank">Open in Google Maps</a>`);
      const html = htmlParts.join("<br/>");
      mk.addListener('click',()=>{{infow.setContent(html);infow.open({{anchor:mk,map}});}});
    }});

    // Events from events.txt (orange markers)
    events.forEach(e => {{
      const mk = new google.maps.Marker({{
        position:{{lat:e.lat,lng:e.lng}}, map, title:e.name,
        icon: "http://maps.google.com/mapfiles/ms/icons/orange-dot.png"
      }});
      const html = `<b>${{e.name}}</b><br/>📅 ${{e.date}}<br/>${{e.addr}}` + (e.link ? `<br/><a href="${{e.link}}" target="_blank">More info</a>` : "");
      mk.addListener('click',()=>{{infow.setContent(html);infow.open({{anchor:mk,map}});}});
    }});
  </script></body>
</html>
"""

components.html(MAP_HTML, height=560, scrolling=False)

# ----------------------------
# List view: show places with found event links + events.txt list
# ----------------------------
st.subheader("Places (with any auto-found event/admission link)")
for p in place_markers:
    cols = st.columns([3,2])
    with cols[0]:
        st.markdown(f"**{p['name']}**  \n{p['addr']}")
    with cols[1]:
        if p.get("event_link"):
            st.markdown(f"[Event / Admission page]({p['event_link']})")
        else:
            st.markdown("No direct event link found")

st.write("---")
st.subheader("Upcoming Events (from events.txt)")
if events.empty:
    st.info("No upcoming events found in events.txt")
else:
    for _, e in events.iterrows():
        link_md = f"[More Info]({e['link']})" if pd.notna(e.get("link","")) and e.get("link","") else ""
        st.markdown(f"""
        **{e['name']}**  
        📅 {e['date'].date()}  
        {e['description']}  
        {link_md}
        """)
