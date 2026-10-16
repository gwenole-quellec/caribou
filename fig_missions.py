# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — visualize mission refusals under carbon-budget pooling.

For each carbon-reduction target, plot the median number of refused missions per 100 requests across
sampled prioritization rules, with 25th–75th percentile bands.

Each combination of sampled rule, pooling fraction, and reduction target is calibrated separately to
the prescribed expected carbon reduction.

Percentile bands characterize sensitivity to hypothetical prioritization behaviors, not confidence
intervals or probabilities of real-world decisions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import PercentFormatter


# ==================================================================================================
# Configuration
# ==================================================================================================

TARGETS = (5, 10, 15, 20)
METRIC = "refused_missions_percent"
SCHEMA_VERSION = "1.0"

# Shared carbon-target palette for the four CARIBOU figures.
TARGET_COLORS = {
    5: "#2676B8",      # Blue
    10: "#159FAD",     # Teal
    15: "#DF8836",     # Orange
    20: "#CB4D4D",     # Red
}

FIGURE_SIZE = (9.6, 6.1)
PNG_DPI = 300
LINE_WIDTH = 2.7
BAND_ALPHA = 0.13
POINT_SIZE = 39

# All four levels have the same dashed vertical guide.
# Interior levels (0.2 and 0.5) additionally receive markers on each curve.
GUIDE_POOLING = (0.0, 0.20, 0.50, 1.0)
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
    """Read one carbon-target report and check its basic structure."""
    path = results_dir / f"budget_allocation_{target}pct.json"

    if not path.is_file():
        raise FileNotFoundError(f"Missing simulation result: {path}")

    with path.open(encoding="utf-8") as stream:
        report = json.load(stream)

    if report.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported CARIBOU JSON schema in {path}")
    if not report.get("draws"):
        raise ValueError(f"No sampled decision rules in {path}")
    if not report.get("pooling_fractions"):
        raise ValueError(f"No pooling fractions in {path}")

    recorded_target = report.get("target_reduction_percent")
    if recorded_target is not None and not np.isclose(
        float(recorded_target), target
    ):
        raise ValueError(f"Carbon target does not match filename: {path}")

    return report


def summarize_report(report: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return pooling levels and the 25/50/75 percentiles across rules."""
    pooling = np.asarray(report["pooling_fractions"], dtype=float)
    if not np.all(np.isfinite(pooling)) or np.any(np.diff(pooling) <= 0):
        raise ValueError("Pooling fractions must be finite and increasing")

    values = np.empty((len(report["draws"]), len(pooling)), dtype=float)

    for i, draw in enumerate(report["draws"]):
        for j, level in enumerate(pooling):
            metric = draw["by_lambda"][pooling_key(level)]["metrics"][METRIC]
            if metric is None:
                raise ValueError("Missing metric in a sampled configuration")
            values[i, j] = float(metric)

    if not np.isfinite(values).all():
        raise ValueError("Invalid metric value in simulation results")

    percentiles = np.percentile(values, (25, 50, 75), axis=0)
    return pooling, percentiles


def load_curves(results_dir: Path) -> tuple[dict, int]:
    """Load four comparable reports and determine their common rule count."""
    curves = {}
    counts = set()
    common_pooling = None

    for target in TARGETS:
        report = load_report(results_dir, target)
        pooling, percentiles = summarize_report(report)

        if common_pooling is None:
            common_pooling = pooling
        elif not np.array_equal(pooling, common_pooling):
            raise ValueError("Inconsistent pooling grid across carbon targets")

        curves[target] = (pooling, percentiles)
        counts.add(len(report["draws"]))

    if len(counts) != 1:
        raise ValueError("Reports contain different numbers of sampled rules")

    return curves, counts.pop()


# ==================================================================================================
# Figure
# ==================================================================================================

def plot_missions(curves: dict, rule_count: int, output_dir: Path) -> None:
    """Plot all carbon targets on a single, decision-oriented axis."""
    fig, ax = plt.subplots(figsize=FIGURE_SIZE, constrained_layout=True)

    # Guide lines mark the pooling fractions reused in other CARIBOU figures.
    for level in GUIDE_POOLING:
        ax.axvline(
            level, color="#777777", linewidth=1.1,
            linestyle="--", alpha=0.50, zorder=0,
        )

    for target in TARGETS:
        pooling, (lower, median, upper) = curves[target]
        color = TARGET_COLORS[target]

        ax.fill_between(
            pooling, lower, upper,
            facecolor=color, alpha=BAND_ALPHA, linewidth=0,
            zorder=1,
        )
        ax.plot(
            pooling, median, color=color,
            linewidth=LINE_WIDTH, solid_capstyle="round",
            zorder=3,
        )

        # Emphasize both intermediate levels used in the other figures.
        # The endpoints (0 and 1) remain vertical guides only.
        for level in GUIDE_POOLING[1:-1]:
            matches = np.flatnonzero(np.isclose(pooling, level))
            if len(matches) != 1:
                raise ValueError(f"Pooling level {level:g} missing from results")
            index = int(matches[0])
            ax.scatter(
                [pooling[index]], [median[index]],
                s=POINT_SIZE, facecolor=color, edgecolor="white",
                linewidth=1.0, zorder=4,
            )

        # Direct labeling is easier to read than a separate color legend.
        ax.annotate(
            f"$-{target}\\%\\,\\mathrm{{CO}}_2$", xy=(pooling[-1], median[-1]),
            xytext=(11, 0), textcoords="offset points",
            va="center", ha="left", color=color,
            fontsize=11.5, fontweight="bold", clip_on=False,
        )

    ax.set_title(
        "How many research trips can budget pooling preserve?",
        fontsize=17, pad=15,
    )
    ax.set_xlabel("Share of the annual carbon budget pooled", fontsize=12)
    ax.set_ylabel("Refused missions per 100 requested trips", fontsize=12)

    ax.set_xlim(-0.015, 1.12)
    ax.set_ylim(bottom=0)
    ax.set_xticks(np.linspace(0, 1, 11))
    ax.xaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))

    ax.grid(axis="y", color="#D9DEE3", alpha=0.75, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.text(
        0.015, 0.98, "Lower is better",
        transform=ax.transAxes, fontsize=11,
        va="top", ha="left", color="#5E6670",
    )
    ax.text(
        0.5, -0.14,
        f"Median across {rule_count:,} sampled decision rules · "
        "shading: 25th–75th percentiles",
        transform=ax.transAxes, va="top", ha="center",
        fontsize=11, color="#5E6670",
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

    curves, rule_count = load_curves(args.results_dir)
    plot_missions(curves, rule_count, args.output_dir)


if __name__ == "__main__":
    main()
