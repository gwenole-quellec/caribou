# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Travel distances, geocoding and emission factors for CARIBOU.

Pure calculation helpers and explicit geocoding/cache operations are shared by workbook preparation
and the UI. This module has no command-line interface. Taxi estimates include an empty vehicle
return, separate from passenger returns.
"""

from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# ==================================================================================================
# Constants
#
# Emission factors follow a methodology adapted from GES 1point5
# (Mariette et al., 2022; https://doi.org/10.1088/2634-4505/ac84a4).
#
# France-specific factors are retained for reproducibility. They reflect the low carbon intensity of
# French electricity, largely due to nuclear and renewable power generation.
# ==================================================================================================

EARTH_RADIUS_KM = 6371.0088
PLANE_EXTRA_KM = 95.0
PLANE_SHORT_LIMIT_KM = 1000.0
PLANE_LONG_LIMIT_KM = 3000.0
TRAIN_FAST_LIMIT_KM = 200.0
TAXI_EMPTY_RETURN_MULTIPLIER = 2.0

# g CO2e per passenger-km, except car/taxi: g CO2e per vehicle-km.
EMISSION_FACTORS_G_PER_KM = {
    "plane_short": 258.6,
    "plane_medium": 187.5,
    "plane_long": 152.0,
    "train_fr_short": 18.0,
    "train_fr_long": 3.3,
    "train_mixed": 16.0,
    "train_foreign": 37.0,
    "car": 215.6,
    "bus": 30.6,  # Intercity coach; not an urban-bus factor.
}
COUNTRY_FRANCE = {"france", "fr", "fra"}

ERROR_COLUMNS = [
    "excel_row",
    "reason",
    "origin_city",
    "origin_country",
    "destination_city",
    "destination_country",
    "mode_value",
]


# ==================================================================================================
# Utility functions
# ==================================================================================================

def normalize(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value).strip().casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[\u2010-\u2015_-]+", " ", text)
    return " ".join(text.split())


def coord_key(city: str, country: str) -> str:
    return f"{normalize(city)}|{normalize(country)}"


def is_france(country: str) -> bool:
    """Recognize common country labels used for the France-specific rail factors."""
    return normalize(country) in COUNTRY_FRANCE


def build_mode_map(aliases: dict[str, list[str]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for canonical in ("plane", "train", "car", "taxi", "bus"):
        values = aliases[canonical]
        for value in values:
            normalized = normalize(value)
            if not normalized:
                raise ValueError(f"Empty alias for {canonical}")
            if normalized in mapping and mapping[normalized] != canonical:
                raise ValueError(
                    f"Ambiguous mode alias {value!r}: {mapping[normalized]} versus {canonical}"
                )
            mapping[normalized] = canonical
    return mapping


# ==================================================================================================
# Geographic utility functions
# ==================================================================================================

def check_coords(coords: object) -> bool:
    if not isinstance(coords, (list, tuple)) or len(coords) != 2:
        return False
    try:
        lat, lon = float(coords[0]), float(coords[1])
        return (
            math.isfinite(lat)
            and math.isfinite(lon)
            and -90 <= lat <= 90
            and -180 <= lon <= 180
        )
    except (ValueError, TypeError):
        return False


def geocode(city: str, country: str, user_agent: str) -> list[float] | None:
    query = urlencode(
        {"city": city, "country": country, "format": "jsonv2", "limit": 1}
    )
    url = "https://nominatim.openstreetmap.org/search?" + query
    request = Request(
        url, headers={"User-Agent": user_agent, "Accept": "application/json"}
    )
    with urlopen(request, timeout=20) as response:
        payload = json.load(response)
    if not payload:
        return None
    result = [float(payload[0]["lat"]), float(payload[0]["lon"])]
    return result if check_coords(result) else None


def haversine_km(a: list[float], b: list[float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    x = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(x)))


def save_cache(path: Path, cache: dict[str, list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def resolve_locations(
    places: dict[str, tuple[str, str]],
    cache: dict[str, list[float]],
    cache_path: Path,
    offline: bool,
    user_agent: str,
    progress=None,
) -> dict[str, str]:
    """Resolve distinct locations once, preserving successful results even after an error."""
    failed_locations: dict[str, str] = {}
    last_request_time: float | None = None
    total_requests = sum(key not in cache for key in places) if not offline else 0
    completed_requests = 0
    if progress:
        progress(0, total_requests)
    try:
        for key, (city, country) in sorted(places.items()):
            if key in cache:
                continue
            if offline:
                failed_locations[key] = "not_in_cache_offline"
                continue
            if last_request_time is not None:
                time.sleep(max(0.0, 1.1 - (time.monotonic() - last_request_time)))
            last_request_time = time.monotonic()
            try:
                result = geocode(city, country, user_agent)
                if result is None:
                    failed_locations[key] = "location_not_found"
                else:
                    cache[key] = result
            except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
                failed_locations[key] = "geocoding_error: " + str(exc)[:150]
            completed_requests += 1
            if progress:
                progress(completed_requests, total_requests)
    finally:
        save_cache(cache_path, cache)
    return failed_locations


# ==================================================================================================
# Carbon footprint computation
# ==================================================================================================

def get_factor(
    mode: str, distance_km: float, origin_country: str, destination_country: str
) -> tuple[str, float, float]:
    """Return (factor category, adjusted distance km, emission factor g/km).

    Taxi uses the same vehicle-km factor as car but includes an assumed empty return.
    """
    if mode == "plane":
        if distance_km < PLANE_SHORT_LIMIT_KM:
            category = "plane_short"
        elif distance_km < PLANE_LONG_LIMIT_KM:
            category = "plane_medium"
        else:
            category = "plane_long"
        return (
            category,
            distance_km + PLANE_EXTRA_KM,
            EMISSION_FACTORS_G_PER_KM[category],
        )

    if mode == "train":
        if is_france(origin_country) and is_france(destination_country):
            category = (
                "train_fr_short"
                if distance_km < TRAIN_FAST_LIMIT_KM
                else "train_fr_long"
            )
        elif is_france(origin_country) or is_france(destination_country):
            category = "train_mixed"
        else:
            category = "train_foreign"
        return category, distance_km * 1.2, EMISSION_FACTORS_G_PER_KM[category]

    if mode == "car":
        return "car", distance_km * 1.3, EMISSION_FACTORS_G_PER_KM["car"]
    if mode == "taxi":
        # Include an assumed empty return by the vehicle, not a passenger round trip.
        return (
            "taxi",
            distance_km * 1.3 * TAXI_EMPTY_RETURN_MULTIPLIER,
            EMISSION_FACTORS_G_PER_KM["car"],
        )
    if mode == "bus":
        return "bus", distance_km * 1.5, EMISSION_FACTORS_G_PER_KM["bus"]
    raise ValueError(f"Unsupported canonical mode: {mode}")


def estimate_footprint(
    mode: str,
    origin_coords: list[float],
    destination_coords: list[float],
    origin_country: str,
    destination_country: str,
) -> float | None:
    """Compute kg CO2e for a single leg; return None for a zero-length journey."""
    distance_km = haversine_km(origin_coords, destination_coords)
    if distance_km < 0.001:
        return None
    _, adjusted_km, factor = get_factor(
        mode, distance_km, origin_country, destination_country
    )
    return adjusted_km * factor / 1000.0


def evaluate_leg(
    data: dict,
    indices: dict[str, int],
    aliases: dict[str, str],
    cache: dict[str, list[float]],
    failed_locations: dict[str, str],
) -> tuple[float | None, list[str]]:
    """Return (kg CO2e or None, validation errors) for one spreadsheet row."""
    missing_fields = [name for name in indices if normalize(data[name]) == ""]
    raw_mode = str(data["mode"] or "")
    origin_city = str(data["origin_city"] or "").strip()
    origin_country = str(data["origin_country"] or "").strip()
    destination_city = str(data["destination_city"] or "").strip()
    destination_country = str(data["destination_country"] or "").strip()
    origin_key = coord_key(origin_city, origin_country)
    destination_key = coord_key(destination_city, destination_country)

    problems: list[str] = []
    if missing_fields:
        problems.append("missing_fields: " + ", ".join(missing_fields))
    mode = aliases.get(normalize(raw_mode))
    if raw_mode.strip() and mode is None:
        problems.append("unknown_mode")
    for prefix, key in (("origin", origin_key), ("destination", destination_key)):
        if key in failed_locations:
            problems.append(prefix + "_" + failed_locations[key])

    if (
        missing_fields
        or mode is None
        or origin_key not in cache
        or destination_key not in cache
    ):
        return None, problems

    footprint = estimate_footprint(
        mode,
        cache[origin_key],
        cache[destination_key],
        origin_country,
        destination_country,
    )
    if footprint is None:
        problems.append("identical_or_zero_distance_locations")
    return footprint, problems
