"""Simple great-circle distance helper — used to filter/sort hospitals and
doctors by travel distance from the user's location."""

from math import radians, sin, cos, sqrt, atan2


def haversine_km(lat1, lon1, lat2, lon2):
    """Distance in kilometers between two lat/lon points."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 6371.0  # Earth radius, km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return round(R * c, 1)
