# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Visualize how prioritization behaviors modify the burden of pooling.

This figure summarizes how budget pooling changes the share of severely affected traveler-years
relative to no pooling (lambda=0), separately for each family of sampled prioritization behaviors.

Three heatmaps are shown side by side, corresponding to pooling fractions lambda = 0.20, 0.50, and
1.00.
- Rows: prioritization families.
- Columns: carbon-reduction targets (5%, 10%, 15%, 20%).

Each cell reports the median paired difference across sampled rules in the corresponding family:
    severe restriction rate at the displayed lambda
    minus
    severe restriction rate at lambda = 0
for the same sampled rule.

Negative values indicate fewer severely affected traveler-years under pooling.
Positive values indicate more severely affected traveler-years under pooling.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


# ==================================================================================================
# Configuration
# ==================================================================================================

TARGETS = (5, 10, 15, 20)
POOLING_LEVELS = (0.20, 0.50, 1.00)

METRIC = "severely_affected_traveler_years_percent"
SCHEMA_VERSION = "1.0"

# Use the same carbon-target colors as the other CARIBOU figures.
TARGET_COLORS = {
    5: "#2676B8",      # Blue
    10: "#159FAD",     # Teal
    15: "#DF8836",     # Orange
    20: "#CB4D4D",     # Red
}

FAMILIES = (
    "sequential",
    "cost",
    "distributive",
    "longitudinal",
    "categorical",
)

FAMILY_LABELS = {
    "sequential": "Decide as\n requests arrive",
    "cost": "Prioritize\n by emissions",
    "distributive": "Spread travel\n opportunities",
    "longitudinal": "Compensate\n past restrictions",
    "categorical": "Prioritize by\n staff and purpose",
}

POOLING_LABELS = {
    0.20: "20% pooled",
    0.50: "50% pooled",
    1.00: "100% pooled",
}

FIGURE_SIZE = (12.8, 6.8)
PNG_DPI = 300
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
# Utility functions
# ==================================================================================================

def pooling_key(value: float) -> str:
    """Match the string representation of lambda used in CARIBOU JSON."""
    return format(float(value), ".10g")


def pretty_target(target: int) -> str:
    """Format a carbon-reduction target label."""
    return f"$-{target}\\%$\n$\\mathrm{{CO}}_2$"


def rounded_limit(values: np.ndarray) -> float:
    """Return a readable symmetric color limit covering all values."""
    maximum = float(np.max(np.abs(values)))

    if maximum <= 1.0:
        step = 0.25
    elif maximum <= 2.0:
        step = 0.5
    else:
        step = 1.0

    return max(step, np.ceil(maximum / step) * step)


# ==================================================================================================
# Load and validate simulation data
# ==================================================================================================

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

    available_levels = np.asarray(report.get("pooling_fractions", []), dtype=float)
    if not np.all(np.isfinite(available_levels)):
        raise ValueError(f"Invalid pooling fractions in {path}")

    expected_levels = (0.0,) + POOLING_LEVELS
    for level in expected_levels:
        if np.count_nonzero(np.isclose(available_levels, level)) != 1:
            raise ValueError(f"Missing or duplicated λ={level:g} in {path}")

    return report


def paired_differences_by_family(report: dict) -> tuple[dict, dict]:
    """
    Compute paired differences by decision-rule family.

    For each draw and each displayed pooling level, compute:
        severe_restrictions(lambda) - severe_restrictions(lambda=0)

    Returns
    -------
    differences:
        Nested dict differences[family][level] -> list of paired differences.
    counts:
        Number of sampled rules per family.
    """
    differences = {
        family: {level: [] for level in POOLING_LEVELS}
        for family in FAMILIES
    }

    for draw in report["draws"]:
        family = draw["rule"]["family"]
        if family not in differences:
            raise ValueError(f"Unexpected decision-rule family: {family}")

        baseline = draw["by_lambda"][pooling_key(0.0)]["metrics"][METRIC]
        if baseline is None or not np.isfinite(float(baseline)):
            raise ValueError("Missing or invalid baseline metric at λ=0")

        baseline = float(baseline)

        for level in POOLING_LEVELS:
            value = draw["by_lambda"][pooling_key(level)]["metrics"][METRIC]
            if value is None or not np.isfinite(float(value)):
                raise ValueError(f"Missing or invalid metric at λ={level:g}")

            difference = float(value) - baseline
            differences[family][level].append(difference)

    counts = {
        family: len(differences[family][POOLING_LEVELS[0]])
        for family in FAMILIES
    }

    for family, count in counts.items():
        if count == 0:
            raise ValueError(f"No sampled rules for family '{family}'")

    return differences, counts


def load_governance(results_dir: Path) -> tuple[dict, int, float, dict]:
    """
    Load paired differences for all targets.

    Returns
    -------
    medians:
        medians[level] is a 2D array of shape (n_families, n_targets).
    rule_count:
        Number of sampled decision rules per target.
    threshold:
        Severe-restriction threshold used in the simulations.
    family_counts:
        Counts per family.
    """
    medians = {
        level: np.empty((len(FAMILIES), len(TARGETS)))
        for level in POOLING_LEVELS
    }

    rule_counts = set()
    severity_thresholds = set()
    family_counts = None

    for target_index, target in enumerate(TARGETS):
        report = load_report(results_dir, target)
        differences, counts = paired_differences_by_family(report)

        for family_index, family in enumerate(FAMILIES):
            for level in POOLING_LEVELS:
                medians[level][family_index, target_index] = np.median(
                    differences[family][level]
                )

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
        raise ValueError("Inconsistent severity thresholds across targets")

    return medians, rule_counts.pop(), severity_thresholds.pop(), family_counts


# ==================================================================================================
# Figure
# ==================================================================================================

def draw_cell_annotations(ax: plt.Axes, values: np.ndarray, limit: float) -> None:
    """Annotate each heatmap cell with its median paired difference."""
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            value = values[i, j]

            # Use white text on the darkest cells for readability.
            text_color = "white" if abs(value) > 0.55 * limit else "#1F2933"

            ax.text(
                j,
                i,
                f"{value:+.1f}",
                ha="center",
                va="center",
                fontsize=12,
                color=text_color,
            )


def heatmap_center(axes: np.ndarray) -> float:
    """Horizontal center of the THREE actual heatmap axes, not the colorbar.

    Call this after adding the colorbar (which changes the axes positions).
    """
    left = min(ax.get_position().x0 for ax in axes)
    right = max(ax.get_position().x1 for ax in axes)
    return 0.5 * (left + right)


def plot_governance(
    medians: dict,
    rule_count: int,
    threshold: float,
    family_counts: dict,
    output_dir: Path,
) -> None:
    """Draw the decision-maker-friendly heatmap version of the governance figure."""
    stacked = np.stack([medians[level] for level in POOLING_LEVELS], axis=0)
    color_limit = rounded_limit(stacked)

    fig, axes = plt.subplots(
        1, len(POOLING_LEVELS),
        figsize=FIGURE_SIZE,
        sharey=True,
    )
    fig.subplots_adjust(
        left=0.245, right=0.92, top=0.82, bottom=0.19, wspace=0.10,
    )

    cmap = plt.get_cmap("RdBu_r")

    for ax, level in zip(axes, POOLING_LEVELS):
        values = medians[level]

        image = ax.imshow(
            values,
            vmin=-color_limit,
            vmax=color_limit,
            cmap=cmap,
            aspect="auto",
        )

        draw_cell_annotations(ax, values, color_limit)

        ax.set_title(
            POOLING_LABELS[level],
            fontsize=12,
            pad=12,
        )

        ax.set_xticks(range(len(TARGETS)))
        ax.set_xticklabels(
            [pretty_target(target) for target in TARGETS],
            fontsize=12,
        )
        for label, target in zip(ax.get_xticklabels(), TARGETS):
          label.set_color(TARGET_COLORS[target])
          label.set_fontweight("bold")

        ax.set_yticks(range(len(FAMILIES)))
        ax.set_yticklabels(
            [FAMILY_LABELS[family] for family in FAMILIES],
            fontsize=12,
        )

        # Cell borders.
        ax.set_xticks(np.arange(-0.5, len(TARGETS), 1), minor=True)
        ax.set_yticks(np.arange(-0.5, len(FAMILIES), 1), minor=True)
        ax.grid(which="minor", color="white", linewidth=1.4)
        ax.tick_params(which="minor", bottom=False, left=False)
        ax.tick_params(axis="both", length=0)

        for spine in ax.spines.values():
            spine.set_visible(False)

    colorbar = fig.colorbar(
        image,
        ax=axes,
        fraction=0.035,
        pad=0.02,
    )
    colorbar.set_label(
        "Additional severely affected traveler-years per 100 active\n"
        f"traveler-years (relative to no pooling, $\\lambda = 0$)",
        fontsize=12,
    )
    colorbar.ax.tick_params(labelsize=9)

    # Freeze layout before querying the axes positions. Use the actual span of
    # the three heatmaps, EXCLUDING their y-axis labels and the colorbar.
    fig.canvas.draw()
    x_center = heatmap_center(axes)

    fig.suptitle(
        "How does prioritization behavior affect pooling outcomes?",
        x=x_center, y=0.97, ha="center", fontsize=17,
    )
    fig.text(
        x_center, 0.913,
        "Median paired differences in severe travel restrictions",
        ha="center", va="center", fontsize=12, color="#5E6670",
    )

    family_sizes = set(family_counts.values())
    sampling_note = (
        f"{next(iter(family_sizes)):,} per family"
        if len(family_sizes) == 1 else "unequal family sample sizes"
    )

    fig.text(
        x_center, 0.075,
        "Blue = fewer severe restrictions · Red = more "
        "(relative to the same rule at $\\lambda=0$)",
        ha="center", fontsize=11, color="#5E6670",
    )

    fig.text(
        x_center, 0.048,
        f"Severe = at least {threshold:.0%} of trips refused per traveler-year · "
        f"Median paired differences across {rule_count:,} rules "
        f"({sampling_note})",
        ha="center", fontsize=11, color="#5E6670",
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
        "--results-dir",
        type=Path,
        default=Path("artifacts/results"),
        help="Directory containing CARIBOU JSON simulation reports",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts"),
        help="Directory for the PNG and PDF outputs (default: artifacts)",
    )
    args = parser.parse_args()

    medians, rule_count, threshold, family_counts = load_governance(
        args.results_dir
    )
    plot_governance(
        medians=medians,
        rule_count=rule_count,
        threshold=threshold,
        family_counts=family_counts,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
