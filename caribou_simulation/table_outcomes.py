# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Summarize travel restrictions in a publication table.

Reports four restriction indicators for expected carbon-reduction targets of 5%, 10%, 15%, and 20%,
at a selected pooling fraction.

Each cell contains the median outcome and, in parentheses, the median paired change relative to no
pooling (lambda=0). Paired differences are computed within each sampled rule before taking medians
and are expressed in percentage points.

Results characterize sensitivity to hypothetical prioritization behaviors, not probabilities of
real-world decisions.

Inputs:  artifacts/results/budget_allocation_{5,10,15,20}pct.json
Outputs: artifacts/table_outcomes.tex, artifacts/table_outcomes.md

Usage:
    python -m caribou_simulation.table_outcomes --results-dir artifacts/results --lambda 0.5
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from caribou_version import SIMULATION_SCHEMA_VERSION


# ==================================================================================================
# Configuration
# ==================================================================================================

TARGETS = (5, 10, 15, 20)
OUTPUT_STEM = Path(__file__).stem

# Keep column order aligned with the four outcomes defined in the manuscript.
METRICS = (
    ("refused_missions_percent", "Refused missions", "O_{\\mathrm{miss}}"),
    ("affected_traveler_years_percent", "Affected traveler-years", "O_{\\mathrm{aff}}"),
    ("severely_affected_traveler_years_percent", "Severely affected traveler-years",
     "O_{\\mathrm{sev}}"),
    ("repeatedly_affected_travelers_percent", "Repeatedly affected travelers", "O_{\\mathrm{rep}}"),
)


# ==================================================================================================
# Utility function
# ==================================================================================================

def pooling_key(value: float) -> str:
    """Return the string key used for pooling fractions in CARIBOU reports."""
    return format(float(value), ".10g")


# ==================================================================================================
# Load and summarize simulation data
# ==================================================================================================

def load_report(results_dir: Path, target: int, pooling: float) -> dict:
    path = results_dir / f"budget_allocation_{target}pct.json"
    if not path.is_file():
        raise FileNotFoundError(f"Missing CARIBOU results: {path}")

    with path.open(encoding="utf-8") as stream:
        report = json.load(stream)

    if report.get("schema_version") != SIMULATION_SCHEMA_VERSION:
        raise ValueError(f"Unsupported CARIBOU schema in {path}")
    if not report.get("draws"):
        raise ValueError(f"No per-rule records in {path}; rerun without --no-draws")
    if not np.isclose(float(report.get("target_reduction_percent", -1)), target):
        raise ValueError(f"Reduction target does not match filename: {path}")

    levels = np.asarray(report.get("pooling_fractions", []), dtype=float)
    if levels.ndim != 1 or not np.all(np.isfinite(levels)):
        raise ValueError(f"Invalid pooling fractions in {path}")
    for level in (0.0, pooling):
        if np.count_nonzero(np.isclose(levels, level, atol=1e-10, rtol=0)) != 1:
            raise ValueError(
                f"Expected exactly one pooling fraction lambda={level:g} in {path}"
            )
    return report


def metric_value(draw: dict, level: float, metric: str, target: int) -> float:
    """Read the expected result for one rule, raising on absent/undefined Y4."""
    try:
        value = draw["by_lambda"][pooling_key(level)]["metrics"][metric]
    except KeyError as exc:
        raise ValueError(
            f"Missing {metric} at lambda={level:g}, target={target}% "
            f"(draw {draw.get('draw', '?')})"
        ) from exc
    if value is None:
        raise ValueError(
            f"Undefined {metric} at target={target}%: "
            "check that the input includes travelers active in at least two years"
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {metric}: {value!r}") from exc
    if not np.isfinite(number) or not (0 <= number <= 100):
        raise ValueError(f"Restriction percentage outside [0, 100]: {number}")
    return number


def summarize_report(report: dict, target: int, pooling: float) -> list[tuple[float, float]]:
    """Return (median at lambda, median within-rule difference) for Y1--Y4."""
    selected = [[] for _ in METRICS]
    paired = [[] for _ in METRICS]

    for draw in report["draws"]:
        for index, (key, _, _) in enumerate(METRICS):
            baseline = metric_value(draw, 0.0, key, target)
            current = metric_value(draw, pooling, key, target)
            selected[index].append(current)
            paired[index].append(current - baseline)

    return [
        (float(np.median(values)), float(np.median(changes)))
        for values, changes in zip(selected, paired)
    ]


def analyze(results_dir: Path, pooling: float) -> tuple[dict, int, float]:
    """Read all targets one at a time and verify comparability."""
    summary = {}
    counts = set()
    thresholds = set()

    for target in TARGETS:
        report = load_report(results_dir, target, pooling)
        summary[target] = summarize_report(report, target, pooling)
        counts.add(len(report["draws"]))
        thresholds.add(float(report["experiment"]["severity_threshold"]))
        del report  # do not retain full reports in memory

    if len(counts) != 1:
        raise ValueError("Reports contain different numbers of sampled rules")
    if len(thresholds) != 1:
        raise ValueError("Reports use inconsistent severe-restriction thresholds")
    return summary, counts.pop(), thresholds.pop()


# ==================================================================================================
# Table
# ==================================================================================================

def cell(median: float, delta: float, decimals: int) -> str:
    """Example: 12.4 (+2.1), or 12.4 (-2.1)."""
    return f"{median:.{decimals}f} ({delta:+.{decimals}f})"


def markdown_table(
    summary: dict, pooling: float, n_rules: int, threshold: float, decimals: int
) -> str:
    headers = [f"{name} (${symbol}$)" for _, name, symbol in METRICS]
    lines = [
        f"# CARIBOU restriction outcomes at {100 * pooling:g}% pooling",
        "",
        f"Median percentages across {n_rules:,} sampled prioritization rules. Each cell shows "
        "the median outcome at the selected pooling fraction followed by the median **within-rule "
        "paired difference** relative to no pooling (lambda = 0), in percentage points. "
        "Positive differences indicate more restrictions.",
        "",
        f"Severe means refusing at least {100 * threshold:g}% of an active traveler-year's "
        "requested missions; repeated means refusals in at least two distinct years among "
        "travelers active in at least two years.",
        "",
        "| Expected reduction target | " + " | ".join(headers) + " |",
        "| :--- | " + " | ".join(":---:" for _ in METRICS) + " |",
    ]
    for target in TARGETS:
        values = " | ".join(cell(a, b, decimals) for a, b in summary[target])
        lines.append(f"| {target}% | {values} |")
    lines.extend([
        "",
        "The sampled hypothetical rules support sensitivity analysis, not probabilistic inference "
        "about actual institutional behavior. The median of paired differences need not equal "
        "the difference of medians.",
        "",
    ])
    return "\n".join(lines)


def latex_table(
    summary: dict, pooling: float, n_rules: int, threshold: float, decimals: int
) -> str:
    pooling_pct = f"{100 * pooling:g}\\%"
    threshold_pct = f"{100 * threshold:g}\\%"
    headers = (
        r"\shortstack{Refused\\missions\\($O_{\mathrm{miss}}$)}",
        r"\shortstack{Affected\\traveler-years\\($O_{\mathrm{aff}}$)}",
        r"\shortstack{Severely affected\\traveler-years\\($O_{\mathrm{sev}}$)}",
        r"\shortstack{Repeatedly affected\\travelers\\($O_{\mathrm{rep}}$)}",
    )
    # Entries for all Y's represent restriction rates: positive delta = worse.
    caption = (
        rf"\textbf{{Travel restrictions at {pooling_pct} carbon-budget pooling.}} "
        rf"Each entry gives the median expected restriction percentage across "
        rf"{n_rules:,} sampled prioritization rules, followed in parentheses "
        rf"by the median within-rule paired difference (percentage points) "
        rf"relative to no pooling ($\lambda=0$). "
        rf"Positive differences indicate more restrictions. "
        rf"Severe restrictions correspond to losing at least {threshold_pct} "
        rf"of requested missions in an active traveler-year; repeated restrictions "
        rf"refer to refusals in at least two years among travelers active in "
        rf"at least two study years. Medians summarize hypothetical rules, "
        rf"not a probability model of actual prioritization behavior."
    )
    lines = [
        "% Auto-generated by table_outcomes.py; do not edit the numeric values by hand.",
        "% Requires \\usepackage{booktabs} in the manuscript preamble.",
        r"\begin{table}[t]",
        r"\centering",
        rf"\caption{{{caption}}}",
        r"\label{tab:restriction-outcomes}",
        r"\small",
        r"\setlength{\tabcolsep}{4pt}",
        r"\begin{tabular}{@{}lcccc@{}}",
        r"\toprule",
        r"\shortstack{Expected carbon\\reduction target} & "
        + " & ".join(headers) + r" \\",
        r"\midrule",
    ]
    for target in TARGETS:
        values = " & ".join(cell(a, b, decimals) for a, b in summary[target])
        lines.append(rf"{target}\% & {values} \\")
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
        "",
    ])
    return "\n".join(lines)


# ==================================================================================================
# Command-line interface
# ==================================================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--results-dir", type=Path, default=Path("artifacts/results"),
        help="Directory containing CARIBOU budget_allocation_*pct.json files",
    )
    parser.add_argument(
        "--lambda", dest="pooling", type=float, default=0.5,
        help="Pooling fraction to compare against lambda=0",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts"),
        help="Directory in which to save LaTeX and Markdown tables",
    )
    parser.add_argument(
        "--decimals", type=int, default=1,
        help="Number of decimal places in table entries",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not np.isfinite(args.pooling) or not 0 <= args.pooling <= 1:
        raise SystemExit("--lambda must be a number between 0 and 1")
    if not 0 <= args.decimals <= 4:
        raise SystemExit("--decimals must be between 0 and 4")

    try:
        summary, n_rules, threshold = analyze(args.results_dir, args.pooling)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        raise SystemExit(f"Error: {exc}") from exc
    args.output_dir.mkdir(parents=True, exist_ok=True)

    tex = args.output_dir / f"{OUTPUT_STEM}.tex"
    md = args.output_dir / f"{OUTPUT_STEM}.md"
    tex.write_text(
        latex_table(summary, args.pooling, n_rules, threshold, args.decimals),
        encoding="utf-8",
    )
    md.write_text(
        markdown_table(summary, args.pooling, n_rules, threshold, args.decimals),
        encoding="utf-8",
    )
    print(f"Analyzed {n_rules:,} rules, lambda={args.pooling:g}, "
          f"targets={list(TARGETS)}%; severe threshold={threshold:g}")
    print(f"Wrote {tex}")
    print(f"Wrote {md}")


if __name__ == "__main__":
    main()
