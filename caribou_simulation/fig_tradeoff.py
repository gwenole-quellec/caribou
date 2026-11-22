# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Visualize the trade-off between mission preservation and severe
travel restrictions under budget pooling.

For each carbon-reduction target, this figure shows how pooling changes two
outcomes relative to strictly individual budgets (lambda=0):
- horizontal axis: additional missions preserved per 100 requested missions;
- vertical axis: additional severely affected traveler-years per
  100 active traveler-years.

Both quantities are paired differences, computed within each sampled decision
rule before taking medians across rules. Each combination of carbon-reduction
target and pooling fraction is calibrated separately to the same expected
carbon reduction.

The two coordinates are summarized independently. Consequently, plotted points
and connecting lines are descriptive summaries: they do not necessarily
correspond to a single feasible allocation and should not be interpreted as
Pareto frontiers. The distribution across sampled rules is a sensitivity
analysis, not a confidence interval or a probability distribution over
real-world governance practices.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator


# =============================================================================
# Configuration
# =============================================================================

TARGETS = (5, 10, 15, 20)
SCHEMA_VERSION = "1.0"

REFUSED_METRIC = "refused_missions_percent"
SEVERE_METRIC = "severely_affected_traveler_years_percent"

# Use the same carbon-target colors as the other CARIBOU figures.
TARGET_COLORS = {
    5: "#2676B8",      # Blue
    10: "#159FAD",     # Teal
    15: "#DF8836",     # Orange
    20: "#CB4D4D",     # Red
}

# Shapes identify the three non-reference pooling levels used elsewhere.
HIGHLIGHTED_POOLING = {
    0.20: "o",          # Circle
    0.50: "s",          # Square
    1.00: "D",          # Diamond
}

FIGURE_SIZE = (9.8, 7.7)
PNG_DPI = 300
LINE_WIDTH = 2.7
SMALL_POINT_SIZE = 19
MARKER_SIZE = 89
OUTPUT_STEM = Path(__file__).stem

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Latin Modern Roman", "DejaVu Serif"],
    "mathtext.fontset": "cm",
    "font.weight": "normal",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})


# =============================================================================
# Load and validate simulation data
# =============================================================================

def pooling_key(value: float) -> str:
    """Match the lambda string representation used in CARIBOU JSON."""
    return format(float(value), ".10g")


def load_report(results_dir: Path, target: int) -> dict:
    """Read one simulation report and validate essential metadata."""
    path = results_dir / f"budget_allocation_{target}pct.json"

    if not path.is_file():
        raise FileNotFoundError(f"Missing simulation result: {path}")

    with path.open(encoding="utf-8") as stream:
        report = json.load(stream)

    if report.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported CARIBOU schema in {path}")
    if not report.get("draws"):
        raise ValueError(f"No sampled decision rules in {path}")

    recorded_target = report.get("target_reduction_percent")
    if recorded_target is not None and not np.isclose(
        float(recorded_target), target
    ):
        raise ValueError(f"Carbon target does not match filename: {path}")

    return report


def paired_tradeoff(report: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return medians of within-rule effects for each pooling fraction.

    x = refusals(lambda=0) - refusals(lambda)
        > 0: more missions preserved than under individual budgets.

    y = severe(lambda) - severe(lambda=0)
        > 0: more severely affected traveler-years.
    """
    pooling = np.asarray(report["pooling_fractions"], dtype=float)

    if not np.all(np.isfinite(pooling)) or np.any(np.diff(pooling) <= 0):
        raise ValueError("Pooling fractions must be finite and increasing")
    if not np.any(np.isclose(pooling, 0.0)):
        raise ValueError("The lambda=0 reference is missing")

    for highlighted in HIGHLIGHTED_POOLING:
        if np.count_nonzero(np.isclose(pooling, highlighted)) != 1:
            raise ValueError(f"Pooling fraction {highlighted:g} is missing")

    differences = np.empty((len(report["draws"]), len(pooling), 2))

    for i, draw in enumerate(report["draws"]):
        baseline = draw["by_lambda"][pooling_key(0.0)]["metrics"]
        baseline_refused = float(baseline[REFUSED_METRIC])
        baseline_severe = float(baseline[SEVERE_METRIC])

        for j, level in enumerate(pooling):
            current = draw["by_lambda"][pooling_key(level)]["metrics"]
            current_refused = float(current[REFUSED_METRIC])
            current_severe = float(current[SEVERE_METRIC])

            differences[i, j, 0] = baseline_refused - current_refused
            differences[i, j, 1] = current_severe - baseline_severe

    if not np.all(np.isfinite(differences)):
        raise ValueError("Missing or invalid restriction metrics")

    # Coordinate-wise median of paired differences (percentage points).
    medians = np.median(differences, axis=0)
    return pooling, medians


def load_curves(results_dir: Path) -> tuple[dict, int, float]:
    """Load the four targets and check that their designs are comparable."""
    curves = {}
    counts = set()
    thresholds = set()
    common_pooling = None

    for target in TARGETS:
        report = load_report(results_dir, target)
        pooling, medians = paired_tradeoff(report)

        if common_pooling is None:
            common_pooling = pooling
        elif not np.array_equal(pooling, common_pooling):
            raise ValueError("Inconsistent pooling grid across carbon targets")

        curves[target] = (pooling, medians)
        counts.add(len(report["draws"]))
        thresholds.add(float(report["experiment"]["severity_threshold"]))
        del report

    if len(counts) != 1:
        raise ValueError("Reports contain different numbers of sampled rules")
    if len(thresholds) != 1:
        raise ValueError("Inconsistent severity thresholds across reports")

    return curves, counts.pop(), thresholds.pop()


# =============================================================================
# Figure
# =============================================================================

def plot_tradeoff(
    curves: dict,
    rule_count: int,
    threshold: float,
    output_dir: Path,
) -> None:
    """Plot four benefit-versus-restriction trajectories on shared axes."""
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    fig.subplots_adjust(left=0.135, right=0.965, top=0.785, bottom=0.265)

    ax.axhline(0, color="#929AA2", linewidth=1, linestyle="--", zorder=0)
    ax.axvline(0, color="#929AA2", linewidth=1, linestyle="--", zorder=0)

    for target in TARGETS:
        pooling, medians = curves[target]
        color = TARGET_COLORS[target]
        x, y = medians[:, 0], medians[:, 1]

        ax.plot(
            x, y, color=color, linewidth=LINE_WIDTH,
            solid_capstyle="round", zorder=2,
        )
        ax.scatter(
            x, y, s=SMALL_POINT_SIZE, color=color,
            edgecolors="white", linewidth=0.6, zorder=3,
        )

        for level, marker in HIGHLIGHTED_POOLING.items():
            index = int(np.flatnonzero(np.isclose(pooling, level))[0])
            ax.scatter(
                [x[index]], [y[index]], marker=marker,
                s=MARKER_SIZE, facecolor=color,
                edgecolor="white", linewidth=1.2, zorder=5,
            )

    # The lambda=0 reference is identical for all four target trajectories.
    ax.scatter(
        [0], [0], marker="o", s=91, facecolor="white",
        edgecolor="#303840", linewidth=1.6, zorder=6,
    )

    ax.grid(color="#DDE2E6", alpha=0.70, linewidth=0.9)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Ranges adapt automatically to 100, 1,000, or 10,000 rules.
    positions = np.concatenate([medians for _, medians in curves.values()])
    x_min, y_min = np.min(positions, axis=0)
    x_max, y_max = np.max(positions, axis=0)
    x_span = max(0.3, x_max - x_min)
    y_span = max(0.6, y_max - y_min)

    ax.set_xlim(min(0.0, x_min) - 0.07 * x_span, x_max + 0.16 * x_span)
    ax.set_ylim(min(0.0, y_min) - 0.10 * y_span, y_max + 0.12 * y_span)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6))

    ax.set_xlabel(
        "Additional missions preserved per 100 requested trips  →",
        fontsize=12, labelpad=10,
    )
    ax.set_ylabel(
        "Additional severely affected traveler-years\n"
        "per 100 active traveler-years  ↑",
        fontsize=12, labelpad=10,
    )

    fig.suptitle(
        "How much pooling is worth it?",
        fontsize=17, y=0.972,
    )
    fig.text(
        0.5, 0.915,
        f"Benefits versus severe restrictions, relative to no pooling ($\\lambda = 0$)",
        ha="center", fontsize=12, color="#5E6670",
    )
    fig.text(
        0.5, 0.870,
        "Right preserves more trips · Down imposes fewer severe restrictions · "
        f"Medians of paired differences across {rule_count:,} sampled rules · ",
        ha="center", fontsize=11, color="#5E6670",
    )

    # Color encodes the carbon target, as in figs 1–3.
    target_handles = [
        Line2D([0], [0], color=TARGET_COLORS[target], linewidth=2.8,
               label=f"$-{target}\\%\\,\\mathrm{{CO}}_2$")
        for target in TARGETS
    ]
    fig.legend(
        handles=target_handles, loc="upper center",
        bbox_to_anchor=(0.5, 0.845), ncol=4, frameon=False,
        fontsize=11.5, columnspacing=2, handlelength=2.2,
    )

    # Shape identifies the pooling fraction along each colored path.
    pooling_handles = [
        Line2D([0], [0], linestyle="", marker="o", markersize=8,
               markerfacecolor="white", markeredgecolor="#303840",
               markeredgewidth=1.4, label="0% (reference)"),
    ]
    pooling_handles.extend(
        Line2D([0], [0], linestyle="", marker=marker, markersize=8,
               markerfacecolor="#737D86", markeredgecolor="white",
               label=f"{level:.0%} pooled")
        for level, marker in HIGHLIGHTED_POOLING.items()
    )
    fig.legend(
        handles=pooling_handles, loc="lower center",
        bbox_to_anchor=(0.5, 0.120), ncol=4, frameon=False,
        fontsize=11, columnspacing=2, handletextpad=0.5,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = output_dir / OUTPUT_STEM
    fig.savefig(stem.with_suffix(".png"), dpi=PNG_DPI, bbox_inches="tight")
    fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)

    print(f"Saved {stem.with_suffix('.png')}")
    print(f"Saved {stem.with_suffix('.pdf')}")


# =============================================================================
# Command-line interface
# =============================================================================

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

    curves, rule_count, threshold = load_curves(args.results_dir)
    plot_tradeoff(curves, rule_count, threshold, args.output_dir)


if __name__ == "__main__":
    main()
