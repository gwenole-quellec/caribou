# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""Estimate workbook emissions using the existing CARIBOU calculation engine."""

from argparse import Namespace
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill

import carbon_footprint as engine

FIELDS = (
    "origin_city",
    "origin_country",
    "destination_city",
    "destination_country",
    "mode",
)

MODE_ALIASES = {
    "plane": ["avion", "plane", "flight"],
    "train": ["train", "rail"],
    "car": ["voiture", "car"],
    "taxi": ["taxi"],
    "bus": ["bus", "autocar", "Autocar intercité", "coach"],
}


@dataclass
class EmissionResult:
    """Downloadable artifacts and counts for a single calculation."""

    workbook: bytes
    errors: bytes
    cache: bytes
    calculated: int
    rows: int
    issues: list[dict]


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
    user_agent="CARIBOU-carbon-footprint-ui/1.0 (academic research)",
):
    """Enrich the selected worksheet, preserving source rows and other worksheets.

    A selected round-trip column overrides the global default. Invalid rows keep
    an empty footprint and appear in the error report. Only city/country pairs
    are passed to the engine's geocoder; temporary cache files are removed.
    """
    if header < 1:
        raise ValueError("The header row must be positive.")
    mode_map = engine.build_mode_map(
        Namespace(
            **{
                f"{mode}_values": values
                for mode, values in (aliases or MODE_ALIASES).items()
            }
        )
    )
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
                places, cache, Path(temporary) / "cache.json", offline, user_agent
            )

        footprint_column = ws.max_column + 1
        cell = ws.cell(header, footprint_column, "carbon footprint")
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="174A52")
        calculated = 0
        issues = []
        for row, data, round_trip, flag_errors in rows:
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

        output = BytesIO()
        workbook.save(output)
        report = StringIO(newline="")
        writer = csv.DictWriter(report, fieldnames=engine.ERROR_COLUMNS)
        writer.writeheader()
        writer.writerows(issues)
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
