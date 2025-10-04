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

SERP_API_KEY = st.secrets.get("SERP_API_KEY", "")
TICKETMASTER_KEY = st.secrets.get("TICKETMASTER_API_KEY", "")

if not SERP_API_KEY or not TICKETMASTER_KEY:
    st.error("Add SERP_API_KEY and TICKETMASTER_API_KEY in .streamlit/secrets.toml to run this app.")
    st.stop()

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

TRAINING_KEYWORDS = [
    "training center", "academy", "bootcamp", "coaching center",
    "institute", "skill development", "IELTS", "Data Science", "Python"
]

# ----------------------------
# Safe OpenStreetMap geocoder
# ----------------------------
def geocode_address(addr: str, country: Optional[str] = None) -> Optional[Tuple[float, float, str]]:
    """Safely geocode using OpenStreetMap (Nominatim)"""
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": addr, "format": "json", "limit": 1}
    if country:
        params["country"] = country

    try:
        r = requests
