import os
import json
from datetime import date, timedelta
import requests
import streamlit as st
from langchain_openai import ChatOpenAI
import streamlit.components.v1 as components

# ================================
# Page Config + Theme
# ================================
st.set_page_config(page_title="MonTravels", page_icon="🧭", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #F5F7FA; font-family: 'Trebuchet MS', sans-serif; }
    h1 { color: #FFCC00; text-shadow: 2px 2px 0px #3B4CCA; }
    h2, h3 { color: #3B4CCA; }
    div.stButton > button {
        background-color: #FF1C1C; color: white;
        border-radius: 8px; border: 2px solid #3B4CCA; font-weight: bold;
    }
    div.stButton > button:hover {
        background-color: #FFCC00; color: #2C2C2C; border: 2px solid #FF1C1C;
    }
    section[data-testid="stSidebar"] { background-color: #3B4CCA; color: white; }
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] div[role="button"] {
        color: white !important;
    }
    section[data-testid="stSidebar"] input,
    section[data-testid="stSidebar"] textarea,
    section[data-testid="stSidebar"] select {
        color: #0f172a !important;
        background-color: #eef2ff !important;
        border-radius: 6px !important;
    }
    .agent-card {
        background-color: white; padding: 15px; margin: 10px 0;
        border-radius: 10px; box-shadow: 0px 2px 5px rgba(0,0,0,0.1);
    }
    .agent-card h4 { color: #3B4CCA; margin-bottom: 5px; }
    .agent-card p { margin: 2px 0; }
    </style>
""", unsafe_allow_html=True)

st.title("🧭 MonTravels – Travel with Wisdom")

# ================================
# API Keys
# ================================
SERPAPI_KEY = st.secrets.get("SERPAPI_KEY", "")
if not SERPAPI_KEY:
    st.warning("⚠️ Add SERPAPI_KEY to your .streamlit/secrets.toml for live results.")

# ================================
# Initialize Groq (via LangChain)
# ================================
llm = ChatOpenAI(
    model="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY"),
    openai_api_base="https://api.groq.com/openai/v1",
    temperature=0.4,
    max_tokens=2800,
)

# ================================
# Helper: Geocode city for map centering
# ================================
def geocode_city(city: str):
    """Get lat/lng of a city from OSM Nominatim."""
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": city, "format": "json", "limit": 1, "accept-language": "en"}
    r = requests.get(url, params=params, headers={"User-Agent": "montravels-app"})
    data = r.json()
    if not data:
        return 0, 0
    return float(data[0]["lat"]), float(data[0]["lon"])

# ================================
# SerpAPI Hotel Search
# ================================
def fetch_hotels_serpapi(city, type="hotel"):
    """Fetch hotels or other lodging from SerpAPI's Google Maps results."""
    if not SERPAPI_KEY:
        return []
    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_maps",
        "q": f"{type}s in {city}",
        "type": "search",
        "api_key": SERPAPI_KEY
    }
    r = requests.get(url, params=params, timeout=20)
    data = r.json()
    results = []
    for item in data.get("local_results", [])[:10]:
        coords = item.get("gps_coordinates", {})
        results.append({
            "name": item.get("title"),
            "address": item.get("address"),
            "rating": item.get("rating"),
            "lat": coords.get("latitude"),
            "lng": coords.get("longitude"),
            "link": item.get("website") or item.get("place_id")
        })
    return results

# ================================
# Map Renderer (OpenStreetMap + Leaflet)
# ================================
def render_map(center_lat, center_lng, places):
    map_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8" />
      <title>Hotels Map</title>
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css" />
      <script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
      <style>html, body, #map {{ height: 100%; margin:0; padding:0; }}</style>
    </head>
    <body>
    <div id="map"></div>
    <script>
      var map = L.map('map').setView([{center_lat}, {center_lng}], 13);
      L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
        attribution: '© OpenStreetMap contributors'
      }}).addTo(map);

      var places = {json.dumps(places)};
      places.forEach(function(p) {{
        if (p.lat && p.lng) {{
          var marker = L.marker([p.lat, p.lng]).addTo(map);
          marker.bindPopup("<b>" + (p.name || 'Unknown') + "</b><br/>" +
                           (p.address || '') + "<br/>⭐ " + (p.rating || 'N/A'));
        }}
      }});
    </script>
    </body>
    </html>
    """
    components.html(map_html, height=560, scrolling=False)

# ================================
# Function to generate itinerary
# ================================
def generate_itinerary(city, area, start, end, interests, budget, adults):
    days = max((end - start).days, 1)
    prompt = f"""
    You are an expert travel planner.

    Create a detailed {days}-day travel itinerary for {city}, {area or ''}.
    It MUST include exactly {days} full days, clearly labeled as:
    Day 1, Day 2, ..., Day {days}.
    
    For each day:
    - Morning, Afternoon, and Evening activities
    - Meals with budget-friendly suggestions
    - Practical tips
    - Daily notes

    Focus on interests: {', '.join(interests)}.
    Budget: ${budget} per day for {adults} adults.
    """
    resp = llm.invoke(prompt)
    return resp.content

# ================================
# Sidebar Inputs
# ================================
with st.sidebar:
    city = st.text_input("Destination*").strip()
    area = st.text_input("Area (optional)").strip()
    c1, c2 = st.columns(2)
    with c1: start_date = st.date_input("Start", date.today() + timedelta(days=7))
    with c2: end_date   = st.date_input("End",   date.today() + timedelta(days=10))
    adults  = st.number_input("Adults", 1, 10, 2)
    budget  = st.number_input("Budget ($/day)", 10, 1000, 100)
    interests = st.multiselect(
        "Interests",
        ["food","history","museums","nature","nightlife"],
        default=["food","history"]
    )
    lodging_choice = st.selectbox(
        "Lodging Type",
        ["All", "Hotels", "Residences", "Motels"]
    )
    go = st.button("✨ Build Plan")

# ================================
# Main Action
# ================================
if go:
    if not city:
        st.error("Please enter a destination.")
        st.stop()

    with st.spinner("Building your personalized itinerary..."):
        itinerary = generate_itinerary(city, area, start_date, end_date, interests, budget, adults)

    # Get base map center
    lat, lng = geocode_city(city)

    # Two-column layout
    col1, col2 = st.columns([2, 1])

    # --- LEFT: Itinerary ---
    with col1:
        st.subheader("🗓️ Your Itinerary")
        st.write(itinerary)

    # --- RIGHT: Lodging Options ---
    with col2:
        st.subheader("🏨 Lodging Suggestions")

        all_places = []

        if lodging_choice in ["All", "Hotels"]:
            st.markdown("### 🏨 Hotels")
            hotels = fetch_hotels_serpapi(city, "hotel")
            if not hotels:
                st.caption("No hotels found.")
            else:
                all_places.extend(hotels)
                for h in hotels:
                    st.markdown(f"""
**{h['name']}**  
📍 {h['address']}  
⭐ Rating: {h.get('rating', 'N/A')}
""")

        if lodging_choice in ["All", "Residences"]:
            st.markdown("### 🏡 Residences & Apartments")
            residences = fetch_hotels_serpapi(city, "residence")
            if not residences:
                st.caption("No residences found.")
            else:
                all_places.extend(residences)
                for r in residences:
                    st.markdown(f"""
**{r['name']}**  
📍 {r['address']}  
⭐ Rating: {r.get('rating', 'N/A')}
""")

        if lodging_choice in ["All", "Motels"]:
            st.markdown("### 🛏️ Motels")
            motels = fetch_hotels_serpapi(city, "motel")
            if not motels:
                st.caption("No motels found.")
            else:
                all_places.extend(motels)
                for m in motels:
                    st.markdown(f"""
**{m['name']}**  
📍 {m['address']}  
⭐ Rating: {m.get('rating', 'N/A')}
""")

        if all_places:
            render_map(lat, lng, all_places)

        # Travel Agents block
        st.subheader("✈️ Travel Agents")
        agents = [
            {"name": "GlobeTrek Tours", "desc": "Cultural & family packages", "email": "info@globetrek.com"},
            {"name": "SkyHigh Travels", "desc": "Custom itineraries & visa support", "email": "bookings@skyhigh.com"}
        ]
        for a in agents:
            st.markdown(f"""
            <div class="agent-card">
                <h4>{a['name']}</h4>
                <p>{a['desc']}</p>
                <p><a href="mailto:{a['email']}?subject=MonTravels {city} Trip">📧 Contact</a></p>
            </div>
            """, unsafe_allow_html=True)
