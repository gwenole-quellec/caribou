# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Compare pooling effects on mission refusals by category.

Two rows show mission purposes and personnel categories; four columns show carbon-reduction targets.
Points and bars summarize within-rule changes from no pooling at 20% and 50% pooling: median and
25th–75th percentiles. Negative values mean fewer refusals and more missions preserved. Purpose
groups overlap so their counts are not additive.

Run with:

  python -m caribou_simulation.fig_mission_preservation_breakdown

Optionally with settings:

  python -m caribou_simulation.fig_mission_preservation_breakdown \
      --category-settings settings.json

Example of settings.json:

  {
    "by_mission_type": {
      "hidden": ["Administration de la recherche", "Inconnu"],
      "labels": {
        "Collaboration": "Collaboration",
        "Colloque-Congrès": "Conferences",
        "Enseignement": "Teaching",
        "Séminaire": "Seminars",
        "Visite": "Visits"
      }
    },
    "by_personnel_category": {
      "hidden": [],
      "labels": {}
    }
  }
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from textwrap import fill

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D


# ==================================================================================================
# Configuration
# ==================================================================================================

TARGETS = (5, 10, 15, 20)
POOLING_LEVELS = (0.2, 0.5)
SECTIONS = {
    "by_mission_type": "Mission purpose",
    "by_personnel_category": "Personnel category",
}
COLORS = {0.2: "#2676B8", 0.5: "#DF8836"}
OUTPUT_STEM = Path(__file__).stem
RATE_TOLERANCE = 1e-9


# ==================================================================================================
# Paired category effects
# ==================================================================================================

def paired_effects(report: dict, section: str, pooling: float) -> dict:
    """Compute paired changes: pooled refusals minus baseline refusals."""
    draws = report["draws"]
    if not draws:
        raise ValueError("Category figures require per-rule simulation results.")
    key = format(pooling, ".10g")
    baseline = draws[0]["by_lambda"]["0"]["breakdowns"][section]
    changes = {label: [] for label in baseline}
    for draw in draws:
        reference = draw["by_lambda"]["0"]["breakdowns"][section]
        pooled = draw["by_lambda"][key]["breakdowns"][section]
        if reference.keys() != baseline.keys() or pooled.keys() != baseline.keys():
            raise ValueError("Category labels differ between rules or pooling levels.")
        for label, entry in baseline.items():
            if any(
                values[label]["requested_missions"] != entry["requested_missions"]
                for values in (reference, pooled)
            ):
                raise ValueError("Category counts differ between rules or pooling levels.")
            before = float(reference[label]["refused_missions_percent"])
            after = float(pooled[label]["refused_missions_percent"])
            if not all(
                np.isfinite(value) and -RATE_TOLERANCE <= value <= 100 + RATE_TOLERANCE
                for value in (before, after)
            ):
                raise ValueError(
                    f"Invalid category refusal rate for {label!r} at pooling={pooling:g}: "
                    f"baseline={before!r}, pooled={after!r}. Expected values between 0 and 100."
                )
            # Convex interpolation can exceed a boundary by floating-point roundoff.
            before = float(np.clip(before, 0., 100.))
            after = float(np.clip(after, 0., 100.))
            changes[label].append(after - before)
    return {
        label: {
            "requested_missions": entry["requested_missions"],
            "quartiles": np.percentile(changes[label], [25, 50, 75]),
        }
        for label, entry in baseline.items()
    }


def load_effects(results_dir: Path) -> tuple[dict, int]:
    """Load four targets with no pooling, 20% pooling and 50% pooling."""
    effects = {}
    reference_counts = None
    rule_count = None
    for target in TARGETS:
        path = results_dir / f"budget_allocation_{target}pct.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        if report["schema_version"] != "1.0" or report["target_reduction_percent"] != target:
            raise ValueError(f"Unexpected report schema or target: {path}")
        if not report["draws"]:
            raise ValueError(f"Per-rule results are required: {path}")
        levels = np.asarray(report["pooling_fractions"], dtype=float)
        for level in (0., *POOLING_LEVELS):
            if np.count_nonzero(np.isclose(levels, level)) != 1:
                raise ValueError(f"Missing or duplicated pooling fraction {level:g}: {path}")
        count = len(report["draws"])
        if rule_count is not None and count != rule_count:
            raise ValueError("Targets must contain the same number of sampled rules.")
        rule_count = count
        counts = {
            section: {
                label: entry["requested_missions"]
                for label, entry in report["draws"][0]["by_lambda"]["0"]["breakdowns"][section].items()
            }
            for section in SECTIONS
        }
        if reference_counts is not None and counts != reference_counts:
            raise ValueError("Targets must describe the same mission categories and counts.")
        reference_counts = counts
        effects[target] = {
            section: {pooling: paired_effects(report, section, pooling) for pooling in POOLING_LEVELS}
            for section in SECTIONS
        }
        del report
    return effects, rule_count


# ==================================================================================================
# Figure
# ==================================================================================================

def category_display(effects: dict, settings: dict) -> dict:
    """Select and rename displayed categories without combining their statistics."""
    unknown = set(settings) - set(SECTIONS)
    if unknown:
        raise ValueError(f"Unknown category sections: {sorted(unknown)}")
    display = {}
    for section in SECTIONS:
        categories = effects[TARGETS[0]][section][POOLING_LEVELS[0]]
        options = settings.get(section, {})
        hidden = set(options.get("hidden", []))
        labels = options.get("labels", {})
        unknown = (hidden | set(labels)) - set(categories)
        if unknown:
            raise ValueError(f"Unknown categories in {section}: {sorted(unknown)}")
        names = {label: labels.get(label, label).strip() for label in categories if label not in hidden}
        if not names or any(not name for name in names.values()):
            raise ValueError(f"Keep at least one category with a nonempty display name in {section}.")
        if len(set(names.values())) != len(names):
            raise ValueError(f"Display names must be distinct within {section}.")
        display[section] = names
    return display


def plot_mission_preservation_breakdown(effects: dict, rule_count: int, output_dir: Path,
                                        settings: dict | None = None) -> None:
    """Save a two-by-four figure with categorical axes and offset interval markers."""
    display = category_display(effects, settings or {})
    style = {
        "font.family": "serif",
        "font.serif": ["Latin Modern Roman", "DejaVu Serif"],
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
    with plt.rc_context(style):
        fig, axes = plt.subplots(2, 4, figsize=(16, 11), sharey="row", layout="constrained")
        fig.get_layout_engine().set(
            rect=(0, 0.10, 1, 0.77), w_pad=0.04, h_pad=0.05, wspace=0.04, hspace=0.08
        )
        fig.suptitle("Who benefits from carbon-budget pooling?", fontsize=26, y=0.995)
        for row, (section, title) in enumerate(SECTIONS.items()):
            categories = sorted(display[section], key=lambda label: display[section][label].casefold())
            bounds = [
                abs(value)
                for target in TARGETS for pooling in POOLING_LEVELS
                for label, entry in effects[target][section][pooling].items() if label in display[section]
                for value in entry["quartiles"]
            ]
            limit = max(1., max(bounds, default=0.) * 1.15)
            positions = np.arange(len(categories))
            for col, target in enumerate(TARGETS):
                ax = axes[row, col]
                ax.axhline(0, color="#777777", linewidth=1, linestyle="--")
                ax.grid(axis="y", color="#E2E5E8", linewidth=0.8)
                ax.set_axisbelow(True)
                for pooling, offset in zip(POOLING_LEVELS, (-0.13, 0.13)):
                    entries = effects[target][section][pooling]
                    quartiles = np.array(
                        [entries[label]["quartiles"] for label in categories]
                    ).reshape(-1, 3)
                    ax.errorbar(
                        positions + offset, quartiles[:, 1],
                        yerr=np.array([quartiles[:, 1] - quartiles[:, 0],
                                       quartiles[:, 2] - quartiles[:, 1]]),
                        fmt="o", color=COLORS[pooling], markersize=6,
                        capsize=4, elinewidth=1.8, zorder=3,
                    )
                labels = [
                    fill(display[section][label], width=17) +
                    f"\n(n={effects[target][section][POOLING_LEVELS[0]][label]['requested_missions']})"
                    for label in categories
                ]
                ax.set_xticks(positions, labels, rotation=55, ha="right", va="top",
                               multialignment="right", rotation_mode="anchor", fontsize=12)
                ax.tick_params(axis="y", labelsize=13)
                ax.set_ylim(-limit, limit)
                ax.set_xlim(-0.6, max(0.6, len(categories) - 0.4))
                ax.spines[["top", "right"]].set_visible(False)
                if row == 0:
                    ax.set_title(f"−{target}% CO$_2$e", fontsize=20, pad=14)
                if col == 0:
                    ax.set_ylabel(f"{title}\nChange in refused missions (pp)", fontsize=15)
        handles = [
            Line2D([], [], marker="o", linestyle="none", color=COLORS[level], label=f"{level:.0%} pooled")
            for level in POOLING_LEVELS
        ]
        fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 0.965), ncol=2,
                   frameon=False, fontsize=16)
        fig.text(0.5, 0.895, "Lower is better — more missions preserved",
                 fontsize=15, color="#555555", ha="center")
        fig.text(
            0.5, 0.02,
            f"Median and 25th–75th percentiles of paired changes across {rule_count:,} sampled rules. "
            "\n"
            "n = requested missions per category; mission-purpose groups overlap. "
            "Ranges are not confidence intervals.",
            fontsize=12, ha="center", va="bottom",
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        for suffix in ("png", "pdf"):
            path = output_dir / f"{OUTPUT_STEM}.{suffix}"
            fig.savefig(path, dpi=300, bbox_inches="tight")
            print(f"Saved {path}")
        plt.close(fig)


# ==================================================================================================
# Command-line interface
# ==================================================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=Path("artifacts/results"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    parser.add_argument(
        "--category-settings", type=Path,
        help="JSON display settings by section: hidden labels and replacement display names"
    )
    args = parser.parse_args()
    effects, count = load_effects(args.results_dir)
    settings = json.loads(args.category_settings.read_text(encoding="utf-8")) \
        if args.category_settings else {}
    plot_mission_preservation_breakdown(effects, count, args.output_dir, settings)


if __name__ == "__main__":
    main()
