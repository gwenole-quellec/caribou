# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Shared mission mapping, validation and export for both preparation modes."""

import streamlit as st
from caribou_data.workbooks import COLUMNS, prepare, export_workbook


def mission_controls(source, context, calculated_emissions=False):
    """Collect mission settings before importing or calculating emissions."""
    mapping = {}
    for field in COLUMNS:
        if calculated_emissions and field == "emissions_kg_co2e":
            mapping[field] = "carbon footprint"
            continue
        options = [None, *source.columns]
        mapping[field] = st.selectbox(
            field,
            options,
            index=0,
            format_func=lambda v: "— Select a column —" if v is None else str(v),
            key=f"{context}-{field}",
        )
    st.caption(
        "If year is not mapped, it is taken from start_date. "
        "An unmapped or missing mission_type is kept blank."
    )
    aggregate = st.checkbox(
        "Combine travel segments into complete missions",
        value=calculated_emissions,
        key=f"aggregate-{context}",
    )
    st.caption(
        (
            "Check this if several rows describe segments of the same mission and share "
            "the same mission_id. Emissions are summed and the earliest departure date "
            "is retained. Traveler, team and year must match. Distinct nonempty mission types are joined with a comma."
            "  \n"
            "Leave unchecked if each row already represents a complete mission. Duplicate "
            "mission IDs will then block export."
        )
    )
    tonnes = False
    if not calculated_emissions:
        tonnes = st.checkbox(
            "Convert source emissions from tonnes to kg CO₂e", key=f"tonnes-{context}"
        )
        st.caption(
            (
                "Leave unchecked if emissions are already in kg CO₂e. Check only if the "
                "source values are in tonnes: each value will be multiplied by 1,000."
            )
        )
    dayfirst = st.checkbox(
        "Read ambiguous text dates as day/month/year",
        value=True,
        key=f"dates-{context}",
    )
    st.caption(
        (
            "For text dates such as 02/04/2022: checked means 2 April; unchecked means "
            "4 February."
            "  \n"
            "This setting does not affect native Excel dates. Their display, such as "
            "2022-04-02 00:00:00, does not require changing this option."
        )
    )
    return mapping, aggregate, tonnes, dayfirst


def render_missions(source, context):
    """Collect settings and return validated missions for the simple workflow."""
    mapping, aggregate, tonnes, dayfirst = mission_controls(source, context)
    missions, errors = prepare(
        source, mapping, aggregate, tonnes, dayfirst, keep_empty_teams=True
    )
    return render_validated(missions, errors, context)


def render_validated(missions, errors, context):
    """Display validation and export the same complete missions used in charts."""
    kept_rows = missions.attrs.get("kept_no_team_rows", 0)
    if kept_rows:
        st.info(
            f"{kept_rows} source row(s) without a team were retained. Team cells stay "
            "blank in the export and these missions are included in Visualization. "
            "The simulator will still ignore missions without a team."
        )
    ignored_rows = missions.attrs.get("ignored_no_team_rows", 0)

    if ignored_rows:
        st.warning(
            f"{ignored_rows} source row(s) without a team were ignored, "
            "as in the CARIBOU simulator. They are excluded from validation, "
            "export and visualizations."
        )

    if errors:
        for error in errors:
            st.error(error)
        st.info(("Correct the source data or mapping to enable export."))
    else:
        st.success(
            f"{len(missions)} missions validated — compatible with the CARIBOU simulator."
        )
        st.dataframe(missions, use_container_width=True)
        st.download_button(
            "Download missions workbook",
            export_workbook(missions),
            file_name="carbon_footprint.xlsx",
            key=f"{context}-download-missions",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    return None if errors else missions

