# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — estimate the carbon footprint of travel journeys from an Excel spreadsheet.

The tool calculates estimated greenhouse gas emissions for individual journey segments using
geographic distances and transport-specific emission factors. It supports air, rail, car, taxi, and
intercity coach travel, with configurable column names and transport-mode labels.

Results are saved to a new Excel workbook, with an additional "carbon footprint" column expressed
in kg CO2e. Unresolved locations and invalid transport modes are reported separately in a CSV file.

Each spreadsheet row represents a single journey segment. Users are responsible for representing
return journeys, multiple passengers, and other travel arrangements in their input data.
Taxi journeys include an assumed empty vehicle return, with twice the car emissions per leg.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


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
DEFAULT_ALIASES = {
    "plane": ["plane", "flight"],
    "train": ["train", "rail"],
    "car": ["car"],
    "taxi": ["taxi"],
    "bus": ["bus", "coach", "intercity coach"],
}

COUNTRY_FRANCE = {"france", "fr", "fra"}

ERROR_COLUMNS = [
    "excel_row", "reason", "origin_city", "origin_country", "destination_city",
    "destination_country", "mode_value",
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


def build_mode_map(args: argparse.Namespace) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for canonical in ("plane", "train", "car", "taxi", "bus"):
        values = getattr(args, canonical + "_values")
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
# Geographic utilities
# ==================================================================================================

def check_coords(coords: object) -> bool:
    if not isinstance(coords, (list, tuple)) or len(coords) != 2:
        return False
    try:
        lat, lon = float(coords[0]), float(coords[1])
        return math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
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


def read_cache(path: Path) -> dict[str, list[float]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Geocode cache must be a JSON object: {path}")
    return {str(k): list(map(float, v)) for k, v in data.items() if check_coords(v)}


def save_cache(path: Path, cache: dict[str, list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(
            cache, ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def resolve_locations(
    places: dict[str, tuple[str, str]],
    cache: dict[str, list[float]],
    cache_path: Path,
    offline: bool,
    user_agent: str,
) -> dict[str, str]:
    """Resolve distinct locations once, preserving successful results even after an error."""
    failed_locations: dict[str, str] = {}
    last_request_time: float | None = None
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
        return category, distance_km + PLANE_EXTRA_KM, EMISSION_FACTORS_G_PER_KM[category]

    if mode == "train":
        if is_france(origin_country) and is_france(destination_country):
            category = "train_fr_short" if distance_km < TRAIN_FAST_LIMIT_KM else "train_fr_long"
        elif is_france(origin_country) or is_france(destination_country):
            category = "train_mixed"
        else:
            category = "train_foreign"
        return category, distance_km * 1.2, EMISSION_FACTORS_G_PER_KM[category]

    if mode == "car":
        return "car", distance_km * 1.3, EMISSION_FACTORS_G_PER_KM["car"]
    if mode == "taxi":
        # Include an assumed empty return by the vehicle, not a passenger round trip.
        return "taxi", distance_km * 1.3 * TAXI_EMPTY_RETURN_MULTIPLIER, EMISSION_FACTORS_G_PER_KM["car"]
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
    _, adjusted_km, factor = get_factor(mode, distance_km, origin_country, destination_country)
    return adjusted_km * factor / 1000.0


# ==================================================================================================
# Excel input and output
# ==================================================================================================

def resolve_paths(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> tuple[Path, Path, Path, Path]:
    source = args.input.expanduser().resolve()
    if source.suffix.lower() != ".xlsx" or not source.is_file():
        parser.error("Input must be an existing .xlsx workbook")

    output = (
        args.output or source.with_name(source.stem + "_carbon.xlsx")
    ).expanduser().resolve()
    errors_path = (
        args.errors or source.with_name(source.stem + "_carbon_errors.csv")
    ).expanduser().resolve()
    cache_path = (
        args.cache or source.with_name(source.stem + "_geocode_cache.json")
    ).expanduser().resolve()
    if len({source, output, errors_path, cache_path}) != 4:
        parser.error("Input, output, error report and cache paths must all be different")
    return source, output, errors_path, cache_path


def load_sheet(source: Path, sheet_name: str | None, parser: argparse.ArgumentParser):
    """Select the first worksheet unless a specific sheet is provided."""
    workbook = load_workbook(source)
    if sheet_name is None:
        return workbook, workbook.worksheets[0]
    if sheet_name not in workbook.sheetnames:
        parser.error(f"Unknown worksheet {sheet_name!r}; available: {workbook.sheetnames}")
    return workbook, workbook[sheet_name]


def resolve_columns(ws, args: argparse.Namespace, parser: argparse.ArgumentParser) -> dict[str, int]:
    """Map five semantic input fields to their one-based Excel column indices."""
    header_lookup: dict[str, int] = {}
    for cell in ws[1]:
        if cell.value is None:
            continue
        value = str(cell.value).strip()
        if value in header_lookup:
            raise ValueError(f"Duplicate header: {value!r}")
        header_lookup[value] = cell.column

    requested = {
        "origin_city": args.origin_city_column,
        "origin_country": args.origin_country_column,
        "destination_city": args.destination_city_column,
        "destination_country": args.destination_country_column,
        "mode": args.mode_column,
    }
    missing = [name for name in requested.values() if name not in header_lookup]
    if missing:
        parser.error(f"Missing headers in sheet {ws.title!r}: {missing}")
    if normalize("carbon footprint") in {normalize(name) for name in header_lookup}:
        parser.error("A 'carbon footprint' column already exists; refusing to append a duplicate")
    return {field: header_lookup[column] for field, column in requested.items()}


def collect_legs(ws, indices: dict[str, int]) -> tuple[list[tuple[int, dict]], dict[str, tuple[str, str]]]:
    """Collect nonempty rows and unique geocoding requests."""
    legs: list[tuple[int, dict]] = []
    places: dict[str, tuple[str, str]] = {}
    for row in range(2, ws.max_row + 1):
        data = {name: ws.cell(row, index).value for name, index in indices.items()}
        if all(normalize(value) == "" for value in data.values()):
            continue
        legs.append((row, data))
        for prefix in ("origin", "destination"):
            city = str(data[prefix + "_city"] or "").strip()
            country = str(data[prefix + "_country"] or "").strip()
            if city and country:
                places[coord_key(city, country)] = (city, country)
    return legs, places


def append_footprint_header(ws) -> int:
    last_col = ws.max_column + 1
    cell = ws.cell(1, last_col, "carbon footprint")
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor="174A52")
    ws.column_dimensions[get_column_letter(last_col)].width = 19
    return last_col


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

    if missing_fields or mode is None or origin_key not in cache or destination_key not in cache:
        return None, problems

    footprint = estimate_footprint(
        mode, cache[origin_key], cache[destination_key], origin_country, destination_country
    )
    if footprint is None:
        problems.append("identical_or_zero_distance_locations")
    return footprint, problems


def process_legs(
    ws,
    legs: list[tuple[int, dict]],
    indices: dict[str, int],
    aliases: dict[str, str],
    cache: dict[str, list[float]],
    failed_locations: dict[str, str],
    footprint_column: int,
) -> tuple[int, list[dict[str, object]], dict[str, int]]:
    """Write calculated emissions and collect issues without changing source columns."""
    calculated = 0
    issues: list[dict[str, object]] = []
    reasons: dict[str, int] = defaultdict(int)

    for row, data in legs:
        footprint, problems = evaluate_leg(data, indices, aliases, cache, failed_locations)
        if footprint is not None:
            cell = ws.cell(row, footprint_column, round(footprint, 6))
            cell.number_format = "0.000"
            calculated += 1
        if problems:
            for reason in problems:
                reasons[reason.split(":", 1)[0]] += 1
            issues.append({
                "excel_row": row,
                "reason": "; ".join(problems),
                "origin_city": str(data["origin_city"] or "").strip(),
                "origin_country": str(data["origin_country"] or "").strip(),
                "destination_city": str(data["destination_city"] or "").strip(),
                "destination_country": str(data["destination_country"] or "").strip(),
                "mode_value": str(data["mode"] or ""),
            })
    return calculated, issues, reasons


def write_error_report(path: Path, issues: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=ERROR_COLUMNS)
        writer.writeheader()
        writer.writerows(issues)


def print_summary(
    sheet_name: str,
    row_count: int,
    calculated: int,
    issues: list[dict[str, object]],
    reasons: dict[str, int],
    output: Path,
    errors_path: Path,
    cache_path: Path,
) -> None:
    print(f"Worksheet: {sheet_name}")
    print(f"Data rows: {row_count}, calculated: {calculated}, errors: {len(issues)}")
    print(f"Workbook: {output}")
    print(f"Error CSV: {errors_path}")
    print(f"Geocode cache: {cache_path}")
    for reason, count in sorted(reasons.items()):
        print(f"  {reason}: {count}")


# ==================================================================================================
# Command-line interface
# ==================================================================================================

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Add a 'carbon footprint' (kg CO2e) column to one Excel worksheet, one one-way leg per row.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "input", type=Path,
        help="Source .xlsx file (never overwritten)"
    )
    parser.add_argument(
        "--sheet",
        help="Worksheet name (default: first worksheet)"
    )
    parser.add_argument(
        "--origin-city-column", required=True,
        help="Origin city header"
    )
    parser.add_argument(
        "--origin-country-column", required=True,
        help="Origin country header"
    )
    parser.add_argument(
        "--destination-city-column", required=True,
        help="Destination city header"
    )
    parser.add_argument(
        "--destination-country-column", required=True,
        help="Destination country header"
    )
    parser.add_argument(
        "--mode-column", required=True,
        help="Transport mode header"
    )
    for name in ("plane", "train", "car", "taxi", "bus"):
        parser.add_argument(
            f"--{name}-values", nargs="+", default=DEFAULT_ALIASES[name], metavar="ALIAS",
            help=f"Recognized source labels for {name}. Quote multi-word labels. Replaces default aliases.",
        )
    parser.add_argument(
        "--output", type=Path,
        help="Output workbook (default: INPUT_carbon.xlsx)"
    )
    parser.add_argument(
        "--errors", type=Path,
        help="CSV error report (default: INPUT_carbon_errors.csv)"
    )
    parser.add_argument(
        "--cache", type=Path,
        help="JSON geocoding cache (default: INPUT_geocode_cache.json)"
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="Use cached coordinates only; do not call Nominatim"
    )
    parser.add_argument(
        "--user-agent", default="CARIBOU-carbon-footprint-cli/1.0 (academic research)",
        help="Identifiable HTTP User-Agent for Nominatim; include your contact email for production use",
    )
    return parser


# ==================================================================================================
# Main entry point
# ==================================================================================================

def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    source, output, errors_path, cache_path = resolve_paths(args, parser)
    aliases = build_mode_map(args)
    workbook, worksheet = load_sheet(source, args.sheet, parser)
    indices = resolve_columns(worksheet, args, parser)
    legs, places = collect_legs(worksheet, indices)

    cache = read_cache(cache_path)
    failed_locations = resolve_locations(places, cache, cache_path, args.offline, args.user_agent)

    footprint_column = append_footprint_header(worksheet)
    calculated, issues, reasons = process_legs(
        worksheet, legs, indices, aliases, cache, failed_locations, footprint_column
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)
    write_error_report(errors_path, issues)
    print_summary(
        worksheet.title, len(legs), calculated, issues, reasons, output, errors_path, cache_path
    )
    return 2 if issues else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

