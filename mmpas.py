import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date, timedelta

import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from streamlit_autorefresh import st_autorefresh
from dateutil import parser
import re

# ----------------------------
# Config
# ----------------------------
st.set_page_config(page_title="Nearby Training & Schools + Events", page_icon="🗺️", layout="wide")
API_KEY = st.secrets.get("GOOGLE_MAPS_API_KEY", "")

if not API_KEY:
    st.error("Add GOOGLE_MAPS_API_KEY in .streamlit/secrets.toml to run this app.")
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
# Google scraping for events (fixed selectors + flexible)
# ----------------------------
def scrape_google_events(city: str, keyword: str, max_results: int = 12):
    query = f"{keyword} {city} training workshop certification site:.org OR site:.edu OR site:.pk"
    url = "https://www.google.com/search"
    params = {"q": query, "hl": "en"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/115.0 Safari/537.36"
    }
    r = requests.get(url, params=params, headers=headers, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")

    results = []
    today = datetime.today().date()

    for g in soup.select("div.g")[:max_results]:
        title_tag = g.select_one("h3")
        link_tag = g.select_one("a")

        # Google snippets may appear in different tags
        snippet_tag = g.select_one("span.aCOpRe") or g.select_one("div.VwiC3b")

        if not title_tag or not link_tag:
            continue

        title = title_tag.get_text(" ", strip=True)
        snippet = snippet_tag.get_text(" ", strip=True) if snippet_tag else ""
        link = link_tag["href"]

        event_date = None
        date_match = re.search(
            r"(\d{1,2}\s+\w+\s+\d{4}|\d{1,2}\s+\w+|\w+\s+\d{1,2},?\s*\d{4}?)",
            snippet, re.I
        )
        if date_match:
            try:
                parsed_date = parser.parse(date_match.group(0), fuzzy=True).date()
                if parsed_date >= today:
                    event_date = parsed_date
            except:
                pass

        results.append({
            "name": title,
            "description": snippet,
            "link": link,
            "date": event_date
        })

    # Keep all (future + unspecified)
    results.sort(key=lambda x: (x["date"] is None, x["date"] or datetime.max.date()))
    return results

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
    city = st.text_input("City", value="Islamabad")
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

radius_km = st.sidebar.slider("Radius (km)", 1, 15, 3)
radius_m = radius_km * 1000

st.sidebar.subheader("Categories")
selected = st.sidebar.multiselect(
    "Choose categories",
    options=["training_like"] + list(CATEGORIES.keys()),
    default=["training_like", "school", "university"]
)

st.sidebar.subheader("Search Focus")
search_type = st.sidebar.radio("What are you looking for?", ["Trainings", "Academic Programs"])

training_options = [
    "Communication Training", "Data Science Training", "Cyber Security Training",
    "App development Training", "IT Training", "Education training"
]

bsc_options = [
    "BSc Data Science", "BSc IT", "BSc Communication", "BSc Cyber Security",
    "BBA", "BSc Liberal Arts", "BSc Computer Science", "BSc Engineering"
]

msc_options = [
    "MSc Data Science", "MSc IT", "MSc Communication", "MSc Cyber Security",
    "MBA", "MA Business", "MSc Computer Science"
]

diploma_options = [
    "Diploma in Data Science", "Diploma in IT", "Diploma in Communication",
    "Diploma in Cyber Security", "Diploma in Business",
    "Diploma in HR", "Diploma in Health"
]

if search_type == "Trainings":
    selected_kw = st.sidebar.selectbox("Select Training Category", training_options)
else:
    program_type = st.sidebar.radio("Choose Program Type", ["BSc", "MSc", "Diploma"])
    if program_type == "BSc":
        selected_kw = st.sidebar.selectbox("Select BSc Program", bsc_options)
    elif program_type == "MSc":
        selected_kw = st.sidebar.selectbox("Select MSc Program", msc_options)
    else:
        selected_kw = st.sidebar.selectbox("Select Diploma", diploma_options)

extra_kw = selected_kw
max_pages = st.sidebar.select_slider("Pages per type", options=[1, 2], value=1)

st.sidebar.subheader("Filter by Event Date")
date_filter = st.sidebar.date_input("Choose a date (leave blank for all)", value=None)

# ----------------------------
# Fetch Places + Events
# ----------------------------
st.title("Nearby Training & Schools + Live Events")
st.caption("Google Places + Google Search events with auto-refresh and calendar filter.")

with st.spinner("Fetching nearby places…"):
    results = nearby_search(lat, lng, radius_m, selected, keyword=extra_kw.strip() or None, max_pages=max_pages)

results_sorted = sorted(results, key=lambda p: (-p.get("rating", 0), -p.get("user_ratings_total", 0)))

with st.spinner("Scraping live Google events…"):
    events = scrape_google_events(city, extra_kw)

# Debug: show raw events
st.write("Raw events fetched:", len(events))
st.json(events[:5])

st.subheader(f"Found {len(results_sorted)} places and {len(events)} upcoming events")

# ----------------------------
# Calendar-Style Event List
# ----------------------------
st.subheader("Live & Upcoming Events (Calendar View)")

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
