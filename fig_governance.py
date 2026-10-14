"""CARIBOU: compare governance families under pooled carbon budgets.

Four panels show the severity of travel restrictions at different carbon-reduction targets. Within
each panel, the five decision-rule families are compared at pooling fractions of 20%, 50%, and 100%.

Each point is the median share of active traveler-years in which at least half of the requested
missions are refused. All values are absolute levels, not differences relative to an individual
allocation (lambda = 0).

The sampled-rule distributions are sensitivity analyses, not representative probabilities of actual
governance practices. Differences between families are descriptive; several rule parameters can vary
at once.

Inputs:  budget_allocation_{5,10,15,20}pct.json (simulation schema 1.0)
Outputs: fig_governance.png and fig_governance.pdf (or this script's stem)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D


# ==================================================================================================
# Configuration
# ==================================================================================================

TARGETS = (5, 10, 15, 20)
POOLING_LEVELS = (0.20, 0.50, 1.0)
METRIC = "severely_affected_traveler_years_percent"
SCHEMA_VERSION = "1.0"

FAMILIES = (
    "sequential",
    "cost",
    "distributive",
    "longitudinal",
    "random",
)

FAMILY_LABELS = {
    "sequential": "First come, first served",
    "cost": "Lowest-carbon trips first",
    "distributive": "Shared fairly",
    "longitudinal": "Compensate past restrictions",
    "random": "Random allocation",
}

# Carbon-reduction colors match the other CARIBOU figures.
TARGET_COLORS = {
    5: "#2676B8",
    10: "#159FAD",
    15: "#DF8836",
    20: "#CB4D4D",
}

# Pooling fractions are encoded consistently across all four panels.
POOLING_COLORS = {
    0.20: "#219A92",  # Teal
    0.50: "#E0A441",  # Amber
    1.0: "#C95450",   # Red
}

# Small vertical offsets prevent identical values from hiding one another.
POINT_OFFSETS = (-0.14, 0.0, 0.14)

FIGURE_SIZE = (14.0, 8.9)
PNG_DPI = 300
POINT_SIZE = 65
CONNECTOR_COLOR = "#A4ABB1"
OUTPUT_STEM = Path(__file__).stem


# ==================================================================================================
# Load and validate simulation data
# ==================================================================================================

def pooling_key(value: float) -> str:
    """Match the string representation of lambda used in CARIBOU JSON."""
    return format(float(value), ".10g")


def load_report(results_dir: Path, target: int) -> dict:
    """Read a simulation report and verify its relevant metadata."""
    path = results_dir / f"budget_allocation_{target}pct.json"

    if not path.is_file():
        raise FileNotFoundError(f"Missing simulation result: {path}")

    with path.open(encoding="utf-8") as stream:
        report = json.load(stream)

    if report.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported CARIBOU JSON schema in {path}")
    if not report.get("draws"):
        raise ValueError(f"No sampled decision rules in {path}")

    recorded_target = report.get("target_reduction_percent")
    if recorded_target is not None and not np.isclose(
        float(recorded_target), target
    ):
        raise ValueError(f"Carbon target does not match filename: {path}")

    levels = np.asarray(report.get("pooling_fractions", []), dtype=float)
    if not np.all(np.isfinite(levels)):
        raise ValueError(f"Invalid pooling fractions in {path}")
    for level in POOLING_LEVELS:
        if np.count_nonzero(np.isclose(levels, level)) != 1:
            raise ValueError(f"Missing or duplicated λ={level:g} in {path}")

    return report


def summarize_families(report: dict) -> tuple[np.ndarray, dict]:
    """Compute medians by family and pooling fraction for one target."""
    observations = {
        family: {level: [] for level in POOLING_LEVELS}
        for family in FAMILIES
    }

    for draw in report["draws"]:
        family = draw["rule"]["family"]
        if family not in observations:
            raise ValueError(f"Unexpected decision-rule family: {family}")

        for level in POOLING_LEVELS:
            value = draw["by_lambda"][pooling_key(level)]["metrics"][METRIC]
            if value is None or not np.isfinite(float(value)):
                raise ValueError("Missing or invalid severe-restriction metric")
            if not 0 <= float(value) <= 100:
                raise ValueError("Restriction percentage outside [0, 100]")
            observations[family][level].append(float(value))

    values = np.empty((len(FAMILIES), len(POOLING_LEVELS)))
    counts = {}

    for i, family in enumerate(FAMILIES):
        counts[family] = len(observations[family][POOLING_LEVELS[0]])
        if counts[family] == 0:
            raise ValueError(f"No sampled rules for family '{family}'")
        for j, level in enumerate(POOLING_LEVELS):
            values[i, j] = np.median(observations[family][level])

    return values, counts


def load_governance(results_dir: Path) -> tuple[dict, int, float, dict]:
    """Read reports one by one to avoid keeping all draws in memory."""
    medians = {}
    rule_counts = set()
    severity_thresholds = set()
    family_counts = None

    for target in TARGETS:
        report = load_report(results_dir, target)
        values, counts = summarize_families(report)
        medians[target] = values

        rule_counts.add(len(report["draws"]))
        severity_thresholds.add(
            float(report["experiment"]["severity_threshold"])
        )
        if family_counts is None:
            family_counts = counts
        elif counts != family_counts:
            raise ValueError("Different family counts across carbon targets")

        del report

    if len(rule_counts) != 1:
        raise ValueError("Reports contain different numbers of sampled rules")
    if len(severity_thresholds) != 1:
        raise ValueError("Inconsistent severity thresholds across reports")

    return medians, rule_counts.pop(), severity_thresholds.pop(), family_counts


# ==================================================================================================
# Figure
# ==================================================================================================

def plot_governance(
    medians: dict,
    rule_count: int,
    threshold: float,
    family_counts: dict,
    output_dir: Path,
) -> None:
    """Draw four aligned dot-and-line comparisons for decision makers."""
    fig, axes = plt.subplots(2, 2, figsize=FIGURE_SIZE, sharex=True)
    fig.subplots_adjust(
        left=0.215, right=0.980, top=0.865, bottom=0.215,
        wspace=0.62, hspace=0.40,
    )

    # A common x-axis ensures that equal positions mean equal restriction rates.
    maximum = max(float(np.max(values)) for values in medians.values())
    upper = max(2.0, np.ceil(maximum / 2.0) * 2.0)
    ticks = np.arange(0, upper + 0.001, 2.0)
    rows = np.arange(len(FAMILIES))[::-1]

    for target, ax in zip(TARGETS, axes.flat):
        values = medians[target]
        color = TARGET_COLORS[target]

        for i, row in enumerate(rows):
            # The faint baseline separates families without a dense grid.
            ax.axhline(row, color="#E1E5E9", linewidth=0.9, zorder=0)

            y = row + np.asarray(POINT_OFFSETS)
            x = values[i]

            # The connector indicates the same rule family at three levels.
            ax.plot(
                x, y, color=CONNECTOR_COLOR, linewidth=1.8,
                solid_capstyle="round", zorder=2,
            )

            for j, level in enumerate(POOLING_LEVELS):
                ax.scatter(
                    x[j], y[j], s=POINT_SIZE,
                    facecolor=POOLING_COLORS[level], edgecolor="white",
                    linewidth=0.9, zorder=3,
                )

        ax.set_title(
            f"−{target}% CO₂", color=color,
            fontsize=14, fontweight="semibold", pad=10,
        )
        ax.set_yticks(rows)
        ax.set_yticklabels(
            [FAMILY_LABELS[family] for family in FAMILIES], fontsize=10,
        )
        ax.set_ylim(-0.55, len(FAMILIES) - 0.45)
        ax.set_xlim(-0.20, upper + 0.35)
        ax.set_xticks(ticks)

        ax.grid(axis="x", color="#DEE3E7", linewidth=0.9)
        ax.set_axisbelow(True)
        ax.tick_params(axis="y", length=0, pad=8)
        ax.tick_params(axis="x", labelsize=9)
        for spine in ("top", "right", "left"):
            ax.spines[spine].set_visible(False)
        ax.spines["bottom"].set_color("#C8CFD5")

    fig.suptitle(
        "Does governance make pooling fairer?",
        fontsize=17, y=0.968,
    )
    fig.text(
        0.5, 0.914,
        "Severe travel restrictions across carbon-reduction targets",
        ha="center", fontsize=11, color="#5E6670",
    )
    fig.text(
        0.935, 0.914, "Left is better",
        ha="right", fontsize=10, color="#5E6670",
    )
    fig.supxlabel(
        "Traveler-years losing at least "
        f"{threshold:.0%} of requested trips (per 100 active traveler-years)",
        x=0.58, y=0.147, fontsize=11,
    )

    handles = [
        Line2D(
            [0], [0], marker="o", linestyle="",
            markersize=9, markerfacecolor=POOLING_COLORS[level],
            markeredgecolor="white", label=f"{level:.0%} pooled",
        )
        for level in POOLING_LEVELS
    ]
    fig.legend(
        handles=handles, loc="lower center", ncol=3,
        bbox_to_anchor=(0.5, 0.093), frameon=False,
        fontsize=10, handletextpad=0.4, columnspacing=1.5,
    )

    family_sizes = set(family_counts.values())
    sampling_note = (
        f"{next(iter(family_sizes)):,} per family"
        if len(family_sizes) == 1 else "unequal family sample sizes"
    )
    # Reading note complements the pooling legend without singling out a
    # preferred governance rule: only severe restrictions are plotted here.
    fig.text(
        0.5, 0.068,
        "At higher CO₂ targets, fair sharing changes little with pooling; "
        "carbon-cost and random rules show larger increases.",
        ha="center", fontsize=9.2, color="#374151",
    )
    fig.text(
        0.5, 0.031,
        f"Medians within governance families · {rule_count:,} sampled rules "
        f"({sampling_note}) · Points are vertically offset for readability only.",
        ha="center", fontsize=9, color="#5E6670",
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
        "--results-dir", type=Path, default=Path("results"),
        help="Directory containing CARIBOU JSON simulation reports",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("figures"),
        help="Directory for the PNG and PDF figures (default: figures)",
    )
    args = parser.parse_args()

    medians, rule_count, threshold, family_counts = load_governance(args.results_dir)
    plot_governance(medians, rule_count, threshold, family_counts, args.output_dir)


if __name__ == "__main__":
    main()
