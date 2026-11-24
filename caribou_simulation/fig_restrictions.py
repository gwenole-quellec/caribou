# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Visualize the distribution of travel restrictions.

For four carbon-reduction targets (rows) and four pooling fractions (columns), each pictogram
represents 100 active traveler-year equivalents, divided into three categories:
- gray:  no refused missions;
- amber: some refusals, but fewer than half of requests lost;
- red:   at least half of requested missions refused.

Shares are derived from median restriction indicators across sampled prioritization rules. The
moderate share is calculated as the median affected share minus the median severely affected share.

Pictograms are rounded representations of aggregate expected outcomes, not individual observed
travelers. The sampled rules characterize sensitivity to hypothetical prioritization behaviors, not
probabilities of real-world decisions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Circle

from caribou_version import SIMULATION_SCHEMA_VERSION


# ==================================================================================================
# Configuration
# ==================================================================================================

TARGETS = (5, 10, 15, 20)
POOLING_LEVELS = (0.0, 0.20, 0.50, 1.0)

AFFECTED_METRIC = "affected_traveler_years_percent"
SEVERE_METRIC = "severely_affected_traveler_years_percent"

# Shared target colors with fig_mission_preservation.py.
TARGET_COLORS = {
    5: "#2676B8",
    10: "#159FAD",
    15: "#DF8836",
    20: "#CB4D4D",
}

# Same meaning in every village, irrespective of carbon target or pooling.
STATUS_COLORS = {
    "none": "#CCD0D4",
    "moderate": "#EDBF53",
    "severe": "#D65A57",
}

FIGURE_SIZE = (10, 12)
PNG_DPI = 300
GRID_SIZE = 10
FACE_RADIUS = 0.40
OUTPUT_STEM = Path(__file__).stem

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Latin Modern Roman", "DejaVu Serif"],
    "mathtext.fontset": "cm",
    "font.weight": "normal",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})


# ==================================================================================================
# Load and validate simulation data
# ==================================================================================================

def pooling_key(value: float) -> str:
    """Match the string representation of lambda used in CARIBOU JSON."""
    return format(float(value), ".10g")


def load_report(results_dir: Path, target: int) -> dict:
    """Read one carbon-target report and verify its basic structure."""
    path = results_dir / f"budget_allocation_{target}pct.json"

    if not path.is_file():
        raise FileNotFoundError(f"Missing simulation result: {path}")

    with path.open(encoding="utf-8") as stream:
        report = json.load(stream)

    if report.get("schema_version") != SIMULATION_SCHEMA_VERSION:
        raise ValueError(f"Unsupported CARIBOU JSON schema in {path}")
    if not report.get("draws"):
        raise ValueError(f"No sampled decision rules in {path}")

    recorded_target = report.get("target_reduction_percent")
    if recorded_target is not None and not np.isclose(
        float(recorded_target), target
    ):
        raise ValueError(f"Carbon target does not match filename: {path}")

    levels = np.asarray(report.get("pooling_fractions", []), dtype=float)
    if not np.isfinite(levels).all():
        raise ValueError(f"Invalid pooling fractions in {path}")

    for level in POOLING_LEVELS:
        if np.count_nonzero(np.isclose(levels, level)) != 1:
            raise ValueError(f"Missing or duplicated λ={level:g} in {path}")

    return report


def median_restrictions(report: dict, pooling: float) -> dict:
    """Summarize three exclusive restriction categories across rules.

    The two published CARIBOU metrics are the affected and severe shares.
    To ensure that the displayed categories sum to 100%, the moderate share is computed as
    median(affected) - median(severe). This is NOT necessarily the median of each rule's moderate
    share.
    """
    key = pooling_key(pooling)
    affected = []
    severe = []

    for draw in report["draws"]:
        metrics = draw["by_lambda"][key]["metrics"]
        affected_value = metrics[AFFECTED_METRIC]
        severe_value = metrics[SEVERE_METRIC]

        if affected_value is None or severe_value is None:
            raise ValueError("Missing restriction metric in a sampled rule")

        a = float(affected_value)
        s = float(severe_value)

        if (
            not np.isfinite(a) or not np.isfinite(s)
            or not 0 <= s <= a <= 100
        ):
            raise ValueError("Invalid affected/severe restriction shares")

        affected.append(a)
        severe.append(s)

    affected_median = float(np.median(affected))
    severe_median = float(np.median(severe))

    return {
        "none": 100.0 - affected_median,
        "moderate": affected_median - severe_median,
        "severe": severe_median,
    }


def load_distributions(results_dir: Path) -> tuple[dict, int, float]:
    """Load the 4 × 4 scenario table and its common experiment metadata."""
    distributions = {}
    counts = set()
    thresholds = set()

    for target in TARGETS:
        report = load_report(results_dir, target)
        counts.add(len(report["draws"]))
        thresholds.add(float(report["experiment"]["severity_threshold"]))

        distributions[target] = {
            level: median_restrictions(report, level)
            for level in POOLING_LEVELS
        }
        del report

    if len(counts) != 1:
        raise ValueError("Reports contain different numbers of sampled rules")
    if len(thresholds) != 1:
        raise ValueError("Inconsistent severity thresholds between reports")
    if thresholds != {0.5}:
        raise ValueError("The face legend assumes a 50% severity threshold")

    return distributions, counts.pop(), thresholds.pop()


# ==================================================================================================
# Draw one village of 100 traveler-year equivalents
# ==================================================================================================

def rounded_face_counts(shares: dict) -> dict:
    """Round three percentages to 100 symbols using largest remainders."""
    names = ("severe", "moderate", "none")
    values = np.asarray([shares[name] for name in names], dtype=float)

    counts = np.floor(values).astype(int)
    remaining = GRID_SIZE**2 - counts.sum()

    for index in np.argsort(-(values - counts))[:remaining]:
        counts[index] += 1

    return dict(zip(names, counts.tolist()))


def draw_face(ax, x: float, y: float, status: str) -> None:
    """Draw a tiny happy, neutral, or unhappy face."""
    ax.add_patch(
        Circle(
            (x, y), FACE_RADIUS,
            facecolor=STATUS_COLORS[status],
            edgecolor="white",
            linewidth=0.45,
        )
    )

    for offset in (-0.125, 0.125):
        ax.add_patch(Circle((x + offset, y + 0.095), 0.037, color="#303338"))

    if status == "moderate":
        ax.plot(
            (x - 0.16, x + 0.16), (y - 0.16, y - 0.16),
            color="#303338", linewidth=0.8,
        )
        return

    mouth_x = np.linspace(x - 0.17, x + 0.17, 13)
    parabola = 1 - ((mouth_x - x) / 0.17)**2

    if status == "none":
        mouth_y = y - 0.105 - 0.10 * parabola
    else:
        mouth_y = y - 0.245 + 0.10 * parabola

    ax.plot(mouth_x, mouth_y, color="#303338", linewidth=0.8)


def draw_village(ax, shares: dict) -> None:
    """Display rounded icons and precise median percentages below them."""
    counts = rounded_face_counts(shares)

    # Put affected travelers first so changes remain visible between panels.
    statuses = (
        ["severe"] * counts["severe"]
        + ["moderate"] * counts["moderate"]
        + ["none"] * counts["none"]
    )

    for index, status in enumerate(statuses):
        column = index % GRID_SIZE
        row = index // GRID_SIZE
        draw_face(ax, column + 0.5, 9.5 - row, status)

    # Exact medians, rather than values rounded to whole faces.
    ax.text(
        5, -0.32,
        f"No refusals: {shares['none']:.1f}%\n"
        f"Moderate: {shares['moderate']:.1f}%\n"
        f"Severe: {shares['severe']:.1f}%",
        ha="center", va="top", fontsize=10, linespacing=1.22,
        color="#374151",
    )

    ax.set_xlim(0, 10)
    ax.set_ylim(-2.05, 10)
    ax.set_aspect("equal")
    ax.axis("off")


# ==================================================================================================
# Figure
# ==================================================================================================

def plot_restrictions(
    distributions: dict,
    rule_count: int,
    severity_threshold: float,
    output_dir: Path,
) -> None:
    """Show the four carbon targets and four pooling fractions together."""
    fig, axes = plt.subplots(
        len(TARGETS), len(POOLING_LEVELS),
        figsize=FIGURE_SIZE,
    )

    # Manual margins reserve a real footer for the legend and explanation.
    fig.subplots_adjust(
        left=0.14, right=0.985, top=0.875, bottom=0.13,
        wspace=0.04, hspace=0.18,
    )

    for i, target in enumerate(TARGETS):
        for j, level in enumerate(POOLING_LEVELS):
            ax = axes[i, j]
            draw_village(ax, distributions[target][level])

            if i == 0:
                ax.set_title(
                    f"{level:.0%} pooled", pad=11, fontsize=11.5,
                    color="#374151", fontweight="bold",
                )

            if j == 0:
                ax.text(
                    -0.18, 0.56,
                    f"$-{target}\\%\\,\\mathrm{{CO}}_2$",
                    transform=ax.transAxes,
                    ha="right", va="center",
                    fontsize=11.5, fontweight="bold",
                    color=TARGET_COLORS[target],
                    clip_on=False,
                )

    left = axes[0, 0].get_position().x0
    right = axes[0, -1].get_position().x1
    x_center = 0.5 * (left + right)

    fig.suptitle(
        "Who bears the travel restrictions?",
        fontsize=17, x=x_center, y=0.97,
    )
    fig.text(
        x_center, 0.915,
        "Distribution per 100 active traveler-years · "
        f"Medians across {rule_count:,} sampled decision rules\n"
        "Faces rounded to whole traveler-year equivalents",
        ha="center", color="#5E6670", fontsize=11,
    )

    handles = [
        Line2D(
            [0], [0], linestyle="", marker="o", markersize=10,
            markerfacecolor=STATUS_COLORS[name], markeredgecolor="white",
        )
        for name in ("none", "moderate", "severe")
    ]
    labels = (
        "No refused missions",
        f"Some refusals ($< {100 * severity_threshold:.0f}\\%$)",
        f"Severe restrictions ($\\geq {100 * severity_threshold:.0f}\\%$)",
    )

    fig.legend(
        handles, labels,
        loc="lower center", bbox_to_anchor=(x_center, 0.068),
        ncol=3, frameon=False, fontsize=11,
        columnspacing=1.5, handletextpad=0.5,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = output_dir / OUTPUT_STEM

    fig.savefig(stem.with_suffix(".png"), dpi=PNG_DPI, bbox_inches="tight")
    fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)

    print(f"Saved {stem.with_suffix('.png')}")
    print(f"Saved {stem.with_suffix('.pdf')}")


# ==================================================================================================
# Command-line interface
# ==================================================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-dir", type=Path, default=Path("artifacts/results"),
        help="Directory containing CARIBOU JSON simulation reports",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts"),
        help="Directory for the PNG and PDF figures (default: artifacts)",
    )
    args = parser.parse_args()

    distributions, rule_count, threshold = load_distributions(args.results_dir)
    plot_restrictions(distributions, rule_count, threshold, args.output_dir)


if __name__ == "__main__":
    main()
