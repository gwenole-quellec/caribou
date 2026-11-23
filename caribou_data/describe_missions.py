# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Summarize eligible research-travel missions.

Reads the 'missions' worksheet from carbon_footprint.xlsx, using the same eligibility criteria as
explore_budget_allocation.py: missions without a team are always ignored, and specified mission types
are excluded. No mission type is excluded by default.

Outputs:
  artifacts/table_dataset.tex             LaTeX descriptive table
  artifacts/table_dataset.md              Markdown descriptive table
  artifacts/fig_emissions_histogram.pdf  Mission-emissions histogram
  artifacts/fig_emissions_histogram.png  Same histogram (300 dpi)

Reports annual and overall statistics; distinct travelers and teams are counted separately for each
period, so annual counts are not additive.

Usage:
  python -m caribou_data.describe_missions --input carbon_footprint.xlsx \
      --exclude-mission-types research_administration
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import MaxNLocator


# ==================================================================================================
# Configuration
# ==================================================================================================

REQUIRED_COLUMNS = (
    "mission_id", "year", "person_id", "team", "mission_type", "start_date",
    "emissions_kg_co2e",
)

TABLE_FILENAME = "table_dataset"
FIGURE_FILENAME = "fig_emissions_histogram"
PNG_DPI = 300
FIGURE_SIZE = (9.6, 5.4)
HISTOGRAM_COLOR = "#2676B8"  # consistent with other CARIBOU figures
MEDIAN_COLOR = "#CB4D4D"
P90_COLOR = "#555555"

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Latin Modern Roman", "DejaVu Serif"],
    "mathtext.fontset": "cm",
    "font.weight": "normal",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})


# ==================================================================================================
# Utility function
# ==================================================================================================

def load_eligible_missions(
    path: Path, excluded_mission_types: list[str]
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Use exactly the simulation's team and mission-type eligibility filtering.

    Filtering precedes validation. Count each excluded mission once, giving
    missing teams precedence when a row also matches an excluded mission type.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Input workbook not found: {path}")
    df = pd.read_excel(path, sheet_name="missions")

    missing = sorted(set(REQUIRED_COLUMNS) - set(df.columns))
    if missing:
        raise ValueError(f"Missing columns in 'missions': {missing}")

    original_count = len(df)
    team_names = df["team"].astype("string").fillna("").str.strip()
    missing_team_mask = team_names.eq("")

    excluded_types = {value.strip().casefold() for value in excluded_mission_types}
    excluded_types.discard("")
    df["mission_type"] = df["mission_type"].astype("string").fillna("").str.strip()
    types = df["mission_type"].str.casefold()
    excluded_type_mask = (~missing_team_mask) & types.isin(excluded_types)
    eligible_mask = ~(missing_team_mask | excluded_type_mask)

    exclusions = {
        "total": int((~eligible_mask).sum()),
        "no_team": int(missing_team_mask.sum()),
        "mission_type": int(excluded_type_mask.sum()),
    }
    df = df.loc[eligible_mask].copy()
    df["team"] = team_names.loc[eligible_mask]

    if df.empty:
        raise ValueError("No eligible missions after filtering empty teams and mission types")
    if df[list(REQUIRED_COLUMNS)].isna().any().any():
        raise ValueError("Missing mandatory mission fields among eligible missions")
    if df["mission_id"].duplicated().any():
        raise ValueError("Duplicated mission_id among eligible missions")

    df["year"] = pd.to_numeric(df["year"], errors="raise")
    if not np.isfinite(df["year"]).all() or (df["year"] % 1 != 0).any():
        raise ValueError("Mission years must be integers")
    df["year"] = df["year"].astype(int)
    df["start_date"] = pd.to_datetime(df["start_date"], errors="raise")
    if (df["start_date"].dt.year != df["year"]).any():
        raise ValueError("Mission year does not match start_date year")
    df["emissions_kg_co2e"] = pd.to_numeric(
        df["emissions_kg_co2e"], errors="raise"
    )
    costs = df["emissions_kg_co2e"].to_numpy(dtype=float)
    if not np.isfinite(costs).all() or (costs < 0).any():
        raise ValueError("Mission emissions must be finite and nonnegative")
    if costs.sum() <= 0:
        raise ValueError("No eligible missions with positive total emissions")

    assert exclusions["total"] + len(df) == original_count
    return df, exclusions


# ==================================================================================================
# Table
# ==================================================================================================

def calculate_summary(df: pd.DataFrame) -> tuple[list[dict], int]:
    """Return one row for each year and a final row for the full period."""
    result = []
    for year in sorted(df["year"].unique()):
        result.append(summarize(df[df["year"] == year], str(year)))
    result.append(summarize(df, "Total"))
    traveler_years = int(df[["person_id", "year"]].drop_duplicates().shape[0])
    return result, traveler_years


def summarize(df: pd.DataFrame, period: str) -> dict:
    costs = df["emissions_kg_co2e"].to_numpy(dtype=float)
    q25, q50, q75 = np.percentile(costs, [25, 50, 75])
    return {
        "period": period,
        "missions": int(len(df)),
        "travelers": int(df["person_id"].astype(str).nunique()),
        "teams": int(df["team"].astype("string").fillna("").str.strip().replace("", pd.NA).nunique()),
        "emissions_t": float(costs.sum() / 1000),
        "median_kg": float(q50),
        "q25_kg": float(q25),
        "q75_kg": float(q75),
    }


def latex_table(rows: list[dict], traveler_years: int, exclusions: dict[str, int]) -> str:
    """Standalone LaTeX table, usable via an input command."""
    years = [int(row["period"]) for row in rows if row["period"] != "Total"]
    years_str = (
        str(years[0]) if len(years) == 1 else f"{years[0]}--{years[-1]}"
    )
    caption = (
        r"\textbf{Characteristics of the observed research travel.} "
        rf"Eligible missions from {years_str}, excluding {exclusions['total']:,} "
        r"missions assigned to excluded accounting categories. "
        r"The total row counts distinct travelers and research teams across the full period "
        r"(not sums of annual counts). "
        rf"There were {traveler_years:,} active traveler-years. "
        r"Emissions refer to complete missions; the median is accompanied by its interquartile range "
        r"(IQR)."
    )
    out = [
        "% Auto-generated by describe_missions.py.",
        "% Requires \\usepackage{booktabs} in the document preamble.",
        r"\begin{table}[t]",
        r"\centering",
        rf"\caption{{{caption}}}",
        r"\label{tab:dataset}",
        r"\small",
        r"\setlength{\tabcolsep}{5pt}",
        r"\begin{tabular}{@{}lrrrrr@{}}",
        r"\toprule",
        r"Year & Missions & Travelers & Teams & "
        r"\shortstack{Total emissions\\(t~\co)} & "
        r"\shortstack{Mission emissions\\median (IQR), kg~\co} \\",
        r"\midrule",
    ]
    for row in rows:
        if row["period"] == "Total":
            out.append(r"\midrule")
        med_iqr = (
            f"{row['median_kg']:,.1f} "
            f"({row['q25_kg']:,.1f}--{row['q75_kg']:,.1f})"
        )
        out.append(
            f"{row['period']} & {row['missions']:,} & {row['travelers']:,} & "
            f"{row['teams']:,} & {row['emissions_t']:,.1f} & {med_iqr} " + r"\\"
        )
    out.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}", ""])
    return "\n".join(out)


def markdown_table(rows: list[dict], traveler_years: int, exclusions: dict[str, int]) -> str:
    lines = [
        "# CARIBOU — descriptive travel statistics", "",
        f"Eligible missions after excluding {exclusions['total']:,} mission(s).", "",
        "| Year | Missions | Travelers | Teams | Emissions (t CO₂e) | "
        "Median mission emissions (IQR), kg CO₂e |",
        "| :--- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        med_iqr = (
            f"{row['median_kg']:,.1f} "
            f"({row['q25_kg']:,.1f}–{row['q75_kg']:,.1f})"
        )
        lines.append(
            f"| {row['period']} | {row['missions']:,} | {row['travelers']:,} | "
            f"{row['teams']:,} | {row['emissions_t']:,.1f} | {med_iqr} |"
        )
    lines.extend([
        "", f"Active traveler-years: **{traveler_years:,}**.",
        "The total counts unique travelers and research teams across all years; "
        "annual traveler and team counts should not be summed.",
        "Teams are identified using `team`; emissions are complete-mission totals in "
        "`emissions_kg_co2e`.", "",
    ])
    return "\n".join(lines)


# ==================================================================================================
# Figure
# ==================================================================================================

def emission_axis_ticks(max_emissions: float) -> tuple[list[float], list[str]]:
    """Readable tick labels in actual kg CO2e on a log1p-transformed axis."""
    preferred = [0, 1, 3, 10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000]
    values = [v for v in preferred if v <= max_emissions * 1.05]
    if len(values) < 3:
        # Generic labels for very low-emission-only test datasets.
        values = list(np.linspace(0, max_emissions, 5))
    return [math.log10(1 + x) for x in values], [f"{x:g}" for x in values]


def plot_histogram(costs: np.ndarray, output_dir: Path, bins: int) -> None:
    """Bin evenly in log10(1+emissions), preserving zero-emission records."""
    if bins < 5:
        raise ValueError("--bins must be at least 5")
    transformed = np.log10(1 + costs)
    fig, ax = plt.subplots(figsize=FIGURE_SIZE, constrained_layout=True)
    max_x = float(np.max(transformed))
    edges = np.linspace(0, max(max_x, 1e-6), bins + 1)
    ax.hist(
        transformed, bins=edges, color=HISTOGRAM_COLOR,
        alpha=0.86, edgecolor="white", linewidth=0.65,
    )

    median = float(np.median(costs))
    percentile90 = float(np.percentile(costs, 90))
    ax.axvline(
        math.log10(1 + median), linewidth=2.0, color=MEDIAN_COLOR,
        linestyle="--", label=f"Median: {median:,.1f} kg $\\mathrm{{CO}}_2$e",
    )
    ax.axvline(
        math.log10(1 + percentile90), linewidth=1.9, color=P90_COLOR,
        linestyle=":", label=f"90th percentile: {percentile90:,.0f} kg $\\mathrm{{CO}}_2$e",
    )
    tick_positions, tick_labels = emission_axis_ticks(float(np.max(costs)))
    ax.set_xticks(tick_positions, tick_labels)
    ax.set_xlim(0, max_x * 1.025)
    ax.set_ylim(bottom=0)
    ax.set_xlabel(f"Emissions per mission (kg $\\mathrm{{CO}}_2$e; logarithmic spacing)",
                  fontsize=12)
    ax.set_ylabel("Number of missions", fontsize=12)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=7))
    ax.grid(axis="y", alpha=0.20, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(
        loc="upper right", frameon=True, facecolor="white",
        edgecolor="none", framealpha=0.93, fontsize=11,
    )

    # The figure is descriptive: equal-width bins in transformed space, not
    # densities per kg. The x-axis uses labels in ORIGINAL emission units.
    output_dir.mkdir(parents=True, exist_ok=True)
    root = output_dir / FIGURE_FILENAME
    fig.savefig(root.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(root.with_suffix(".png"), dpi=PNG_DPI, bbox_inches="tight")
    plt.close(fig)


# ==================================================================================================
# Command-line interface
# ==================================================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input", type=Path, default=Path("carbon_footprint.xlsx"),
        help="Input workbook with a 'missions' worksheet",
    )
    parser.add_argument(
        "--exclude-mission-types", nargs="+", default=[], metavar="TYPE",
        help="Complete mission-type labels to exclude (case-insensitive); combined labels must be specified in full; missions without a team are always excluded",
    )
    parser.add_argument(
        "--table-dir", type=Path, default=Path("artifacts"),
        help="Output directory for LaTeX and Markdown tables",
    )
    parser.add_argument(
        "--figure-dir", type=Path, default=Path("artifacts"),
        help="Output directory for the PDF and PNG histogram",
    )
    parser.add_argument(
        "--bins", type=int, default=30,
        help="Number of equal-width bins in log10(1 + mission emissions)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df, exclusions = load_eligible_missions(args.input, args.exclude_mission_types)
    rows, n_traveler_years = calculate_summary(df)

    args.table_dir.mkdir(parents=True, exist_ok=True)
    table_stem = args.table_dir / TABLE_FILENAME
    table_stem.with_suffix(".tex").write_text(
        latex_table(rows, n_traveler_years, exclusions), encoding="utf-8"
    )
    table_stem.with_suffix(".md").write_text(
        markdown_table(rows, n_traveler_years, exclusions), encoding="utf-8"
    )
    plot_histogram(
        df["emissions_kg_co2e"].to_numpy(dtype=float),
        args.figure_dir, args.bins,
    )

    total = rows[-1]
    print(
        f"Eligible missions: {total['missions']:,}; "
        f"travelers: {total['travelers']:,}; "
        f"teams: {total['teams']:,}; "
        f"traveler-years: {n_traveler_years:,}; "
        f"baseline: {total['emissions_t']:,.3f} t CO2e "
        f"(excluded {exclusions['total']:,}: "
        f"{exclusions['no_team']:,} without a team, "
        f"{exclusions['mission_type']:,} by mission type)."
    )
    for suffix in (".tex", ".md"):
        print(f"Created: {table_stem.with_suffix(suffix)}")
    for suffix in (".pdf", ".png"):
        print(f"Created: {(args.figure_dir / FIGURE_FILENAME).with_suffix(suffix)}")


if __name__ == "__main__":
    main()
