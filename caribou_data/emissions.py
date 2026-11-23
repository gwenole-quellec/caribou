# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Estimate workbook emissions using the existing CARIBOU calculation engine."""

from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill

from caribou_data import carbon_footprint as engine


# ==================================================================================================
# Constants
# ==================================================================================================

FIELDS = (
    "origin_city",
    "origin_country",
    "destination_city",
    "destination_country",
    "mode",
)

MODE_ALIASES = {
    "plane": [
        "avion",
        "avions",
        "vol",
        "vols",
        "transport aérien",
        "déplacement aérien",
        "trajet aérien",
        "voyage aérien",
        "vol intérieur",
        "vol domestique",
        "vol national",
        "vol international",
        "vol européen",
        "vol court courrier",
        "vol moyen courrier",
        "vol long courrier",
        "court courrier",
        "moyen courrier",
        "long courrier",
        "plane",
        "airplane",
        "aeroplane",
        "aircraft",
        "flight",
        "flights",
        "air",
        "air travel",
        "air transport",
        "air transportation",
        "domestic flight",
        "international flight",
        "short haul flight",
        "medium haul flight",
        "long haul flight",
    ],
    "train": [
        "train",
        "trains",
        "rail",
        "transport ferroviaire",
        "trajet ferroviaire",
        "voyage en train",
        "chemin de fer",
        "TGV",
        "TGV INOUI",
        "INOUI",
        "OUIGO",
        "TER",
        "Intercités",
        "train régional",
        "train express régional",
        "train grande ligne",
        "train à grande vitesse",
        "train de nuit",
        "train couchette",
        "Eurostar",
        "Thalys",
        "Lyria",
        "TGV Lyria",
        "ICE",
        "AVE",
        "railway",
        "railroad",
        "rail travel",
        "rail transport",
        "rail transportation",
        "passenger train",
        "regional train",
        "intercity train",
        "high speed train",
        "high speed rail",
        "express train",
        "night train",
        "overnight train",
        "sleeper train",
    ],
    "car": [
        "voiture",
        "voitures",
        "auto",
        "automobile",
        "véhicule",
        "véhicule personnel",
        "véhicule particulier",
        "véhicule privé",
        "voiture personnelle",
        "voiture particulière",
        "voiture privée",
        "voiture de service",
        "véhicule de service",
        "voiture de fonction",
        "véhicule de fonction",
        "voiture de location",
        "véhicule de location",
        "location de voiture",
        "voiture de prêt",
        "covoiturage",
        "car",
        "cars",
        "motor car",
        "passenger car",
        "personal car",
        "private car",
        "private vehicle",
        "company car",
        "company vehicle",
        "staff car",
        "rental car",
        "rented car",
        "hire car",
        "car hire",
        "car rental",
        "pool car",
        "carpool",
        "carpooling",
        "car sharing",
    ],
    "taxi": [
        "taxi",
        "taxis",
        "taxi conventionné",
        "taxi collectif",
        "voiture avec chauffeur",
        "véhicule avec chauffeur",
        "voiture de transport avec chauffeur",
        "VTC",
        "chauffeur privé",
        "service de chauffeur",
        "taxi parisien",
        "radio taxi",
        "taxicab",
        "taxi cab",
        "cab",
        "cabs",
        "private hire vehicle",
        "private hire car",
        "minicab",
        "chauffeur driven car",
        "chauffeur service",
        "car service",
        "ride hailing",
        "ride hailing service",
        "ridesourcing",
        "Uber",
        "UberX",
        "Uber taxi",
        "Bolt",
        "Free Now",
        "FREENOW",
        "G7",
    ],
    "bus": [
        "bus",
        "autocar",
        "autocars",
        "car interurbain",
        "autocar interurbain",
        "autocar intercité",
        "autocar intercités",
        "autocar intercity",
        "autocar longue distance",
        "autocar de tourisme",
        "car de tourisme",
        "autocar de ligne",
        "autocar express",
        "autocar régional",
        "autocar départemental",
        "autocar interrégional",
        "autocar national",
        "autocar international",
        "autocar de nuit",
        "autocar trajets intercités",
        "autocar - trajets intercités",
        "transport par autocar",
        "voyage en autocar",
        "coach",
        "coaches",
        "motorcoach",
        "motor coach",
        "intercity bus",
        "intercity coach",
        "interurban bus",
        "interurban coach",
        "long distance bus",
        "long distance coach",
        "regional coach",
        "express coach",
        "express bus",
        "highway coach",
        "touring coach",
        "charter coach",
        "charter bus",
        "overnight bus",
        "night coach",
        "FlixBus",
        "BlaBlaCar Bus",
        "BlaBlaBus",
        "Ouibus",
        "Eurolines",
        "National Express",
        "Megabus",
        "Greyhound",
    ],
}

VERSION = "1.0"


# ==================================================================================================
# Data structures
# ==================================================================================================

@dataclass
class EmissionResult:
    """Downloadable artifacts and counts for a single calculation."""

    workbook: bytes
    errors: bytes
    cache: bytes
    calculated: int
    rows: int
    issues: list[dict]


# ==================================================================================================
# Utility functions
# ==================================================================================================

def parse_round_trip(value):
    """Parse explicit English/French yes/no labels; reject missing/unknown values."""
    label = engine.normalize(value)
    if label in {"yes", "oui", "true", "vrai", "1", "1.0"}:
        return True
    if label in {"no", "non", "false", "faux", "0", "0.0"}:
        return False
    raise ValueError("Round trip must be yes/no (oui/non), true/false or 1/0.")


def parse_cache(raw):
    """Validate an optional uploaded coordinate cache without discarding errors."""
    data = json.loads(raw) if raw else {}
    if not isinstance(data, dict) or any(
        not engine.check_coords(value) for value in data.values()
    ):
        raise ValueError(
            "The cache must be a JSON object of location keys and [latitude, longitude] pairs."
        )
    return {key: list(map(float, value)) for key, value in data.items()}


# ==================================================================================================
# Emission calculation
# ==================================================================================================

def calculate(
    raw,
    sheet_name,
    mapping,
    aliases=None,
    *,
    header=1,
    ignored_rows=(),
    round_trip_column=None,
    always_round_trip=False,
    cache_bytes=None,
    offline=False,
    user_agent=f"CARIBOU-carbon-footprint-ui/{VERSION} (academic research)",
    progress=None,
):
    """Enrich the selected worksheet, preserving source rows and other worksheets.

    A selected round-trip column overrides the global default. Invalid rows keep an empty footprint
    and appear in the error report. Only city/country pairs are passed to the engine's geocoder;
    temporary cache files are removed.
    Optional progress(stage, completed, total) reports location, row and write stages.
    """
    if header < 1:
        raise ValueError("The header row must be positive.")
    mode_map = engine.build_mode_map(aliases or MODE_ALIASES)
    cache = parse_cache(cache_bytes)
    workbook = load_workbook(BytesIO(raw))

    try:
        ws = workbook[sheet_name]
        columns = {}
        for cell in ws[header]:
            if cell.value is None:
                continue
            label = str(cell.value).strip()
            if label in columns:
                raise ValueError(f"Duplicate header: {label!r}")
            columns[label] = cell.column

        if any(engine.normalize(label) == "carbon footprint" for label in columns):
            raise ValueError(
                "A 'carbon footprint' column already exists. Remove it before recalculating."
            )
        if set(mapping) != set(FIELDS) or any(
            value not in columns for value in mapping.values()
        ):
            raise ValueError("Map all five travel columns.")
        if len(set(mapping.values())) != len(FIELDS):
            raise ValueError("Each travel field must use a different source column.")
        if round_trip_column is not None and round_trip_column not in columns:
            raise ValueError("The selected round-trip column does not exist.")
        if round_trip_column in mapping.values():
            raise ValueError(
                "The round-trip column must be separate from travel fields."
            )

        indices = {field: columns[label] for field, label in mapping.items()}
        ignored_rows = set(ignored_rows)
        rows = []
        places = {}
        for row in range(header + 1, ws.max_row + 1):
            if row in ignored_rows:
                continue
            if all(cell.value is None for cell in ws[row]):
                continue
            data = {
                field: ws.cell(row, index).value for field, index in indices.items()
            }
            problems = []
            round_trip = always_round_trip
            if round_trip_column is not None:
                try:
                    round_trip = parse_round_trip(
                        ws.cell(row, columns[round_trip_column]).value
                    )
                except ValueError as exc:
                    problems.append(str(exc))
            rows.append((row, data, round_trip, problems))
            if not problems:
                for prefix in ("origin", "destination"):
                    city = str(data[prefix + "_city"] or "").strip()
                    country = str(data[prefix + "_country"] or "").strip()
                    if city and country:
                        places[engine.coord_key(city, country)] = (city, country)

        if not rows:
            raise ValueError("The worksheet contains no travel rows.")
        with TemporaryDirectory(prefix="caribou-geocode-") as temporary:
            failed = engine.resolve_locations(
                places, cache, Path(temporary) / "cache.json", offline, user_agent,
                progress=(lambda done, total: progress("geocoding", done, total)) if progress else None,
            )

        footprint_column = ws.max_column + 1
        cell = ws.cell(header, footprint_column, "carbon footprint")
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="174A52")
        calculated = 0
        issues = []
        if progress:
            progress("emissions", 0, len(rows))
        for completed, (row, data, round_trip, flag_errors) in enumerate(rows, start=1):
            footprint = None
            problems = list(flag_errors)
            if not problems:
                footprint, problems = engine.evaluate_leg(
                    data, indices, mode_map, cache, failed
                )
            if footprint is not None and not problems:
                # Taxi empty-return emissions are already included by the engine.
                ws.cell(
                    row,
                    footprint_column,
                    round(footprint * (2 if round_trip else 1), 6),
                ).number_format = "0.000"
                calculated += 1
            else:
                issues.append(
                    {
                        "excel_row": row,
                        "reason": "; ".join(problems)
                        or "No emissions estimate available.",
                        **{
                            field: str(data[field] or "")
                            for field in FIELDS
                            if field != "mode"
                        },
                        "mode_value": str(data["mode"] or ""),
                    }
                )

            if progress:
                progress("emissions", completed, len(rows))

        if progress:
            progress("workbook", 0, 1)
        output = BytesIO()
        workbook.save(output)
        report = StringIO(newline="")
        writer = csv.DictWriter(report, fieldnames=engine.ERROR_COLUMNS)
        writer.writeheader()
        writer.writerows(issues)
        if progress:
            progress("workbook", 1, 1)
        return EmissionResult(
            workbook=output.getvalue(),
            errors=report.getvalue().encode("utf-8-sig"),
            cache=json.dumps(
                cache, ensure_ascii=False, indent=2, sort_keys=True
            ).encode("utf-8"),
            calculated=calculated,
            rows=len(rows),
            issues=issues,
        )
    finally:
        workbook.close()
