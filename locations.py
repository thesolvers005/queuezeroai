"""
Stand-in for a real geocoding API (Google Maps Geocoding, OpenCage, etc).
For the demo, we only need coordinates for cities that appear in the seed
data, plus a few nearby ones a user might mention.

Swap resolve_location()'s body for a real geocoding API call when this goes
past demo data — same function signature, no other code needs to change.
"""

KNOWN_CITY_COORDS = {
    "mangalagiri": (16.4307, 80.5525),
    "vijayawada": (16.5062, 80.6480),
    "guntur": (16.3067, 80.4365),
    "hyderabad": (17.3850, 78.4867),
    "secunderabad": (17.4399, 78.4983),
    "visakhapatnam": (17.6868, 83.2185),
    "vizag": (17.6868, 83.2185),
    "tirupati": (13.6288, 79.4192),
    "gachibowli": (17.4239, 78.3413),
    "chennai": (13.0827, 80.2707),
    "bangalore": (12.9716, 77.5946),
    "bengaluru": (12.9716, 77.5946),
}


def resolve_location(place_name):
    """Returns {"latitude": .., "longitude": ..} or None if unknown."""
    if not place_name:
        return None
    key = place_name.strip().lower()
    coords = KNOWN_CITY_COORDS.get(key)
    if not coords:
        return None
    return {"latitude": coords[0], "longitude": coords[1]}
