# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Streamlit controls for carbon-budget simulations."""

from hashlib import sha256
import json
import re

import streamlit as st

from caribou_data.workbooks import export_workbook
from caribou_simulation.explore_budget_allocation import (
    DEFAULT_GRID,
    DEFAULT_LAMBDAS,
    DEFAULT_MAX_BRACKET_PP,
    DEFAULT_REFINE,
    DEFAULT_SEVERITY_THRESHOLD,
)
from caribou_simulation.workflow import simulate_workbook


# ==================================================================================================
# Utility functions
# ==================================================================================================

def number_list(text):
    """Read comma- or whitespace-separated numeric settings."""
    return [float(value) for value in re.split(r"[\s,;]+", text.strip()) if value]


def render_breakdowns(reports):
    """Show the two additive category indicators from simulation reports."""
    rows = {"by_mission_type": [], "by_personnel_category": []}
    for content in reports.values():
        report = json.loads(content)
        for pooling, summary in report["summary_by_lambda"].items():
            for section, categories in summary["breakdowns"].items():
                for category, values in categories.items():
                    rate = values["refused_missions_percent"]
                    paired = values.get("paired_difference_from_lambda_0_percentage_points", {})
                    rows[section].append({
                        "Reduction target (%)": report["target_reduction_percent"],
                        "Pooling fraction": float(pooling),
                        "Category": category,
                        "Requested missions": values["requested_missions"],
                        "Refused missions (%) — median": rate["median"],
                        "p05": rate["p05"], "p95": rate["p95"],
                        "Paired change from no pooling (pp) — median": paired.get("median"),
                    })
    for section, title in [("by_mission_type", "Refused missions by mission purpose"),
                           ("by_personnel_category", "Refused missions by personnel category")]:
        if rows[section]:
            with st.expander(title):
                st.caption("Rates are within each category, using eligible missions. Purpose groups can overlap; missing labels are Not specified. Ranges describe sampled rules, not confidence intervals.")
                st.dataframe(rows[section], use_container_width=True)


def render_simulation(available):
    """Select a workbook, configure a run, show progress and download results."""
    st.subheader("Explore carbon-budget allocation")
    st.caption(
        "Use prepared missions or upload a workbook containing the 'missions' sheet. "
        "Compare individual and shared team budgets at your chosen emission-reduction targets. "
        "Visualization filters do not restrict this input."
    )
    source = st.radio(
        "Simulation input",
        [*available, "Upload a workbook"],
        key="simulation-source",
        horizontal=True,
    )
    raw = None
    if source == "Upload a workbook":
        upload = st.file_uploader(
            "Simulation workbook (carbon_footprint.xlsx)",
            type=["xlsx"],
            key="simulation-upload",
        )
        if upload is not None:
            raw = upload.getvalue()
    else:
        raw = export_workbook(available[source])

    left, middle, right = st.columns(3)
    targets = left.text_input(
        "Reduction targets (%) — space-separated list", value="5 10 15 20", help='Reductions relative to total emissions of eligible missions, after exclusions. Example: 5 10 15 20 tests four targets. Each value must be greater than 0 and less than 100.', key="simulation-targets"
    )
    draws = middle.number_input(
        "Sampled rules", min_value=1, value=10000, step=100, help='Number of hypothetical prioritization rules sampled, not the number of missions. More rules take longer; try 100 for a quick run.', key="simulation-draws"
    )
    seed = right.number_input(
        "Random seed",
        min_value=0,
        max_value=4294967295,
        value=42,
        step=1,
        help='Controls random sampling. Keep the same seed, input and settings to reproduce a run with the same software version.', key="simulation-seed",
    )
    exclusions = st.text_area(
        "Mission types to exclude (optional, one per line)",
        value="",
        help='One complete mission-type label per line, ignoring capitalization and surrounding whitespace. Combined labels remain included unless specified in full.', key="simulation-exclusions",
    )
    st.caption(
        "Leave exclusions empty to include all mission types. Missions without a team are always ignored by the simulator."
    )

    with st.expander("How it works"):
        st.write(
            "The same historical mission requests are replayed under hypothetical prioritization "
            "rules and different levels of team-budget sharing. Reduction targets apply to the "
            "total eligible emissions across study years. Complete missions are accepted or refused; "
            "when needed, two complete-mission allocations are mixed to attain the target in expectation."
        )
        st.write(
            "Ranges show sensitivity to the sampled rules, not confidence intervals or predictions. "
            "Comparisons with no pooling are paired within each rule and do not establish causal effects. "
            "Missions without a team are always excluded."
        )

    with st.expander("Additional simulation settings"):
        st.caption("Scenario settings: pooling and team headcount. Sampling settings: how rules are explored. Calibration settings: technical search controls; keep their defaults unless needed.")
        lambdas = st.text_input(
            "Pooling fractions (0 = individual, 1 = fully pooled)",
            value=" ".join(f"{value:g}" for value in DEFAULT_LAMBDAS),
            help='Space-separated values from 0 to 1. At 0 budgets are individual; at 1 the team budget is fully pooled. Keep the defaults to generate all standard artifacts.', key="simulation-lambdas",
        )
        sampling = st.selectbox(
            "Rule sampling", ["latin", "random"], help='latin spreads samples across the parameter space; random draws independently. These explore hypothetical allocation behavior, not probabilities of real decisions.', key="simulation-sampling"
        )
        headcount = st.selectbox(
            "Team headcount", ["annual-active", "pooled"], help='annual-active counts the team’s distinct eligible travelers separately each year. pooled uses the distinct eligible travelers across all observed years for each team. Neither is a full staff roster.', key="simulation-headcount"
        )
        grid = st.number_input(
            "Calibration grid size",
            min_value=5,
            value=DEFAULT_GRID,
            step=1,
            help='Technical calibration setting: number of initial budget values tested. A larger grid can improve the search but increases calculation time.', key="simulation-grid",
        )
        refine = st.number_input(
            "Calibration refinement steps",
            min_value=0,
            value=DEFAULT_REFINE,
            step=1,
            help='Technical calibration setting: additional budget-search refinement steps. More steps take longer; the default is recommended.', key="simulation-refine",
        )
        severity = st.number_input(
            "Severe restriction threshold",
            min_value=0.01,
            max_value=1.0,
            value=DEFAULT_SEVERITY_THRESHOLD,
            step=0.05,
            help='Fraction of a traveler’s missions refused in a year that counts as severe restriction. 0.5 means at least half. This changes the indicator, not the allocation decisions.', key="simulation-severity",
        )
        bracket = st.number_input(
            "Calibration bracket warning (percentage points)",
            min_value=0.0,
            max_value=100.0,
            value=DEFAULT_MAX_BRACKET_PP,
            help='Diagnostic warning threshold for the reduction gap between the two allocations mixed during calibration. This does not change allocation decisions.', key="simulation-bracket",
        )
        keep_draws = st.checkbox(
            "Include per-rule results in downloads",
            value=True,
            key="simulation-keep-draws",
            help="Keep checked to generate figures and the outcome table in Artifacts. Unchecking reduces download size but those artifacts cannot be generated from the reports.",
        )

    settings = None
    try:
        settings = {
            "targets": number_list(targets),
            "draws": int(draws),
            "seed": int(seed),
            "exclude_mission_types": [
                line.strip() for line in exclusions.splitlines() if line.strip()
            ],
            "lambdas": number_list(lambdas),
            "sampling": sampling,
            "headcount": headcount,
            "grid": int(grid),
            "refine": int(refine),
            "severity_threshold": float(severity),
            "max_bracket_pp": float(bracket),
            "keep_draws": keep_draws,
        }
    except ValueError:
        st.error(
            "Targets and pooling fractions must contain numbers separated by spaces or commas."
        )

    if raw is None:
        st.info(
            "Upload carbon_footprint.xlsx or prepare missions in one of the first two tabs."
        )
        return
    if settings is None:
        return
    # Hash logical data rather than XLSX bytes: generated ZIP timestamps may vary on reruns.
    if source == "Upload a workbook":
        identity = sha256(raw).hexdigest()
    else:
        identity = sha256(
            available[source].to_json(date_format="iso", orient="split").encode()
        ).hexdigest()
    signature = sha256(
        json.dumps([source, identity, settings], sort_keys=True).encode()
    ).hexdigest()
    st.caption(
        "10,000 rules can take time. The first run also compiles the calculation engine. Keep this session open while it runs; use fewer rules for a quick trial."
    )

    if st.button("Run simulations", type="primary", key="simulation-run"):
        st.session_state.pop("simulation-result", None)
        bar = st.progress(0, text="Validating missions and initializing the engine…")
        try:

            def update(completed, total):
                percent = int(95 * completed / total)
                text = (
                    "Initializing the engine (first-run compilation may take time)…"
                    if completed == 0
                    else (
                        "Writing simulation reports…"
                        if completed == total
                        else f"Computing allocations: {completed}/{total} steps ({percent}%)"
                    )
                )
                bar.progress(percent, text=text)

            reports, archive = simulate_workbook(raw, settings, progress=update)
            bar.progress(100, text="Simulation complete — results ready.")
            st.session_state["simulation-result"] = (signature, reports, archive)
        except Exception as exc:
            bar.empty()
            st.error(f"Unable to run simulations: {exc}")

    saved = st.session_state.get("simulation-result")
    if saved is None or saved[0] != signature:
        return
    _, reports, archive = saved
    st.success(f"Simulation complete: {len(reports)} reduction target(s).")
    metadata = json.loads(next(iter(reports.values())))["input"]
    st.info(
        f"{metadata['missions_included']} eligible missions; {metadata['missions_excluded']} excluded."
    )
    st.caption(
        "Medians and ranges describe sensitivity across hypothetical rules, not confidence intervals or predictions."
    )
    render_breakdowns(reports)
    st.download_button(
        "Download all simulation results (.zip)",
        archive,
        file_name="caribou_simulation_results.zip",
        mime="application/zip",
        key="simulation-download-zip",
    )
    for name, content in reports.items():
        st.download_button(
            name,
            content,
            file_name=name,
            mime="application/json",
            key="simulation-report-" + name,
        )
