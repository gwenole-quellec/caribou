# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Workbook mapping, mission aggregation and validation, independent of Streamlit."""

from io import BytesIO
import numpy as np
import pandas as pd


# ==================================================================================================
# Constants
# ==================================================================================================

COLUMNS = [
    "mission_id",
    "year",
    "person_id",
    "team",
    "mission_type",
    "start_date",
    "emissions_kg_co2e",
]
OPTIONAL_COLUMNS = ["personnel_category"]


# ==================================================================================================
# Utility functions
# ==================================================================================================

def combine_mission_types(values):
    """Join distinct nonempty comma-separated purposes in source order."""
    purposes = {}
    for value in values:
        for part in str(value).split(","):
            label = part.strip()
            if label:
                purposes.setdefault(label.casefold(), label)
    return ", ".join(purposes.values())


# ==================================================================================================
# Data preparation and export
# ==================================================================================================

def prepare(
    source,
    mapping,
    aggregate=False,
    tonnes=False,
    dayfirst=True,
    *,
    keep_empty_teams=False,
):
    """Return eligible missions and errors; record excluded rows in DataFrame attrs."""
    errors = []
    required = [c for c in COLUMNS if c not in {"year", "mission_type"}]
    if any(not mapping.get(c) for c in required):
        return pd.DataFrame(columns=COLUMNS), ["Map all required columns."]
    selected = [v for v in mapping.values() if v is not None]
    if len(selected) != len(set(selected)):
        return pd.DataFrame(columns=COLUMNS), [
            "A source column cannot be mapped to multiple fields."
        ]
    optional = [c for c in OPTIONAL_COLUMNS if mapping.get(c)]
    df = pd.DataFrame({c: source[mapping[c]].copy() for c in COLUMNS + optional if mapping.get(c)})
    for c in optional:
        df[c] = df[c].astype("string").fillna("").str.strip()
    if "mission_type" not in df:
        df["mission_type"] = ""
    for c in ["mission_id", "person_id", "team", "mission_type"]:
        df[c] = df[c].astype("string").str.strip().replace("", pd.NA)
    df["mission_type"] = df["mission_type"].fillna("")

    # Match the simulator: exclude rows without a team before validation.
    missing_team = df["team"].isna()
    ignored_rows = int(missing_team.sum())
    if keep_empty_teams:
        df["team"] = df["team"].fillna("")
        ignored_rows = 0
    else:
        df = df.loc[~missing_team].copy()

    # Numeric Excel serials must not be interpreted as nanoseconds since 1970.
    raw_dates = df["start_date"]
    if pd.api.types.is_numeric_dtype(raw_dates):
        df["start_date"] = pd.to_datetime(
            raw_dates, unit="D", origin="1899-12-30", errors="coerce"
        )
    else:
        df["start_date"] = pd.to_datetime(
            raw_dates, errors="coerce", dayfirst=dayfirst, format="mixed"
        )
    df["year"] = (
        pd.to_numeric(df["year"], errors="coerce")
        if "year" in df
        else df.start_date.dt.year
    )
    values = df.emissions_kg_co2e
    if not pd.api.types.is_numeric_dtype(values):
        values = (
            values.astype("string")
            .str.replace("\u202f", "", regex=False)
            .str.replace(" ", "", regex=False)
            .str.replace(",", ".", regex=False)
        )
    df["emissions_kg_co2e"] = pd.to_numeric(values, errors="coerce") * (
        1000 if tonnes else 1
    )
    if df.empty:
        errors.append("No missions remain to prepare.")
    for c in COLUMNS:
        count = int(df[c].isna().sum())
        if count:
            errors.append(f"{c} : {count} missing or invalid value(s).")
    if (df.year.notna() & (df.year != df.start_date.dt.year)).any():
        errors.append("The year must match the departure date.")
    invalid = ~np.isfinite(df.emissions_kg_co2e.astype(float)) | (
        df.emissions_kg_co2e < 0
    )
    if invalid.any():
        errors.append("Emissions must be finite and nonnegative.")
    if df.emissions_kg_co2e.sum() <= 0:
        errors.append("Total emissions must be strictly positive.")
    if aggregate:
        for c in ["year", "person_id", "team"]:
            if (df.groupby("mission_id")[c].nunique(dropna=False) > 1).any():
                errors.append(
                    f"Inconsistent segments: multiple values of {c} for the same mission."
                )
        for c in optional:
            values_by_mission = df.groupby("mission_id")[c].agg(
                lambda values: list(dict.fromkeys(value for value in values if value))
            )
            for mission_id, values in values_by_mission.items():
                if len(values) > 1:
                    errors.append(
                        f"Inconsistent segments: mission_id={mission_id!r} has "
                        f"multiple values of {c}: {', '.join(repr(value) for value in values)}."
                    )
        if not errors:
            optional_values = {
                c: df.groupby("mission_id")[c].agg(
                    lambda values: next((value for value in values if value), "")
                )
                for c in optional
            }
            df = df.groupby("mission_id", as_index=False).agg(
                year=("year", "first"),
                person_id=("person_id", "first"),
                team=("team", "first"),
                mission_type=("mission_type", combine_mission_types),
                start_date=("start_date", "min"),
                emissions_kg_co2e=("emissions_kg_co2e", "sum"),
            )
            for c, values in optional_values.items():
                df[c] = df["mission_id"].map(values)
    elif df.mission_id.duplicated().any():
        errors.append(
            "Duplicate mission identifiers: enable segment grouping if appropriate."
        )
    if not errors:
        df["year"] = df.year.astype(int)
    result = df[COLUMNS + optional].copy()
    result.attrs["ignored_no_team_rows"] = ignored_rows
    result.attrs["kept_no_team_rows"] = (
        int(missing_team.sum()) if keep_empty_teams else 0
    )
    return result, errors


def export_workbook(df):
    output = BytesIO()
    # Prevent spreadsheet applications from interpreting source text as formulas.
    safe = df.copy()
    for c in ["mission_id", "person_id", "team", "mission_type",
              *[name for name in OPTIONAL_COLUMNS if name in safe]]:
        safe[c] = safe[c].map(
            lambda v: (
                "'" + v
                if isinstance(v, str) and v.startswith(("=", "+", "-", "@"))
                else v
            )
        )
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        safe.to_excel(writer, sheet_name="missions", index=False)
        sheet = writer.sheets["missions"]
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 24
    return output.getvalue()
