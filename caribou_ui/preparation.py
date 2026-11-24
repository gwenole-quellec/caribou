# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Simple and advanced preparation, shared mapping and workbook export."""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from caribou_data.emissions import FIELDS, MODE_ALIASES, calculate
from caribou_data.workbooks import COLUMNS, OPTIONAL_COLUMNS, prepare, export_workbook
from caribou_ui.session import replace_document


# ==================================================================================================
# Constants
# ==================================================================================================

FIELD_HELP = {
    "personnel_category": "Optional personnel category, such as the source Statut column. "
                          "Used for category-based priorities and refusal-rate diagnostics. "
                          "Leave unmapped if unavailable.",
    "mission_id": "Identifies one complete mission for one traveler. It must be unique across "
                  "people and years. Segments of that mission share this ID.",
    "year": "Departure year. Leave unmapped to derive it from start_date; mapped values must match "
            "the date.",
    "person_id": "Stable traveler identifier across all years. Store IDs as text in Excel to "
                 "preserve leading zeros.",
    "team": "Research team. Blank cells are retained in both preparation modes and excluded only "
            "during simulations. Select the column even if some cells are blank.",
    "mission_type": "Mission purpose. Optional: leave unmapped or keep blank cells. "
                    "Distinct purposes are combined with commas when segments are grouped.",
    "start_date": "Departure date, as an Excel date or text. "
                  "When segments are combined, the earliest date becomes the mission departure date.",
    "emissions_kg_co2e": "Previously estimated emissions for each row. "
                         "Select the tonnes-to-kg option only if the source values are in tonnes CO₂e.",
}


# ==================================================================================================
# Shared preparation controls and validation
# ==================================================================================================

def mission_controls(source, context, calculated_emissions=False):
    """Collect mission settings before importing or calculating emissions."""
    st.caption(
        "Required: mission ID, traveler ID, team column and departure date"
        + ("." if calculated_emissions else ", plus emissions.")
        + " Year can be derived from the date; mission type and personnel category may remain blank. "
        "Use stable traveler IDs and store identifiers as text in Excel to preserve leading zeros."
    )
    mapping = {}
    for field in COLUMNS + OPTIONAL_COLUMNS:
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
            help=FIELD_HELP[field],
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
            "is retained. Traveler, team and year must match. "
            "Distinct nonempty mission types are joined with a comma.  \n"
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


# ==================================================================================================
# Rendering function (Simple preparation)
# ==================================================================================================

def render_simple():
    """Prepare existing emissions and return validated missions, or None.

    Worksheet selection and the preview belong here. Column mapping, mission aggregation, validation
    and workbook export are delegated to render_missions.
    """
    st.subheader("Prepare missions from existing emissions")
    st.caption(
        "Upload an Excel workbook with emissions already calculated. Each row may be a complete "
        "mission or a travel segment to combine. Match your columns below, then download the "
        "validated missions workbook or continue directly to Visualization and Simulation."
    )
    upload = st.file_uploader(
        "Consolidated Excel workbook", type=["xlsx"], key="simple-upload",
        on_change=replace_document, args=("simple-workbook",),
    )
    if upload is None:
        st.info(
            "Upload a workbook with previously estimated emissions. Mission identifiers "
            "must be unique across travelers and years; traveler identifiers must remain stable."
        )
        return None

    # Scope widget state to the uploaded content so a new workbook does not
    # inherit worksheet or mapping choices from a different file.
    raw = upload.getvalue()
    key = "simple-" + sha256(raw).hexdigest()[:16]
    try:
        with pd.ExcelFile(BytesIO(raw), engine="openpyxl") as book:
            sheet = st.selectbox(
                "Source worksheet", book.sheet_names, key=f"sheet-{key}"
            )
            header = st.number_input(
                "Header row", min_value=1, value=1, step=1, key=f"header-{key}-{sheet}"
            )
            # The interface numbers rows from 1; pandas numbers them from 0.
            # Read as objects to avoid forcing mixed source columns to one type.
            source = pd.read_excel(
                book, sheet_name=sheet, header=int(header) - 1, dtype=object
            )
    except Exception as exc:
        st.error(f"Unable to read the workbook: {exc}")
        return None

    # Limit only the preview; preparation receives every source row.
    st.dataframe(source.head(100), use_container_width=True)
    st.caption(
        f"{len(source)} rows; preview limited to the first 100. Empty rows are not automatically removed."
    )
    # Include the worksheet and header in the context to separate mapping state.
    return render_missions(source, f"{key}-{sheet}-{header}")


# ==================================================================================================
# Rendering function (Advanced preparation)
# ==================================================================================================

def render_advanced():
    """Render an independent advanced workflow with session-local results."""
    st.subheader("Estimate emissions from travel segments")
    st.caption(
        "Upload travel records to estimate emissions from departure and arrival locations and "
        "transportation modes. Each row should describe one travel segment; use the round-trip "
        "settings if it also includes the return journey."
    )
    st.caption(
        "Match your columns below. CARIBOU calculates emissions, combines segments into complete "
        "missions when selected, and prepares your data for visualization and simulation."
    )
    with st.expander("How it works"):
        st.write(
            "Distances between cities are adjusted by transportation mode and multiplied by "
            "emission factors adapted from GES 1point5. These are estimates, not measured emissions. "
            "A round trip doubles the one-way estimate; do not enable it when return segments "
            "are already separate rows. Taxi estimates also include an empty vehicle return. "
            "Car and taxi emissions are per vehicle, without automatic sharing between passengers."
        )
        st.write(
            "Both preparation modes retain missions without a team in the workbook and charts; "
            "simulations exclude them. Online "
            "geocoding sends city/country pairs to OpenStreetMap Nominatim. Download the cache "
            "to reuse coordinates or work offline."
        )
    upload = st.file_uploader(
        "Travel workbook (.xlsx)", type=["xlsx"], key="advanced-upload",
        on_change=replace_document, args=("advanced-workbook",),
    )
    if upload is None:
        st.info(
            "Upload travel records to calculate emissions and export complete missions for simulations."
        )
        return

    raw = upload.getvalue()
    prefix = "advanced-" + sha256(raw).hexdigest()[:16]
    try:
        with pd.ExcelFile(BytesIO(raw), engine="openpyxl") as book:
            sheet = st.selectbox(
                "Travel worksheet", book.sheet_names, key=prefix + "-sheet"
            )
            header = st.number_input(
                "Travel header row",
                min_value=1,
                value=1,
                step=1,
                key=prefix + "-header",
            )
            source = pd.read_excel(
                book, sheet_name=sheet, header=int(header) - 1, dtype=object
            )
    except Exception as exc:
        st.error(f"Unable to read the travel workbook: {exc}")
        return

    prefix += f"-{sheet}-{header}"
    st.dataframe(source.head(100), use_container_width=True)
    st.caption(f"{len(source)} rows; preview limited to the first 100.")
    st.markdown("**Mission information**")
    mission_mapping, aggregate, _, dayfirst = mission_controls(
        source, prefix + "-missions", calculated_emissions=True
    )
    st.caption(
        "Mission emissions will be calculated in kg CO₂e from the travel fields below."
    )
    st.markdown("**Travel information**")
    mapping = {}
    for field in FIELDS:
        options = [None, *source.columns]
        mapping[field] = st.selectbox(
            (
                "Transportation mode"
                if field == "mode"
                else field.replace("_", " ").capitalize()
            ),
            options,
            index=0,
            format_func=lambda value: (
                "— Select a column —" if value is None else str(value)
            ),
            key=f"{prefix}-{field}",
        )

    st.markdown("**Return journeys**")
    round_trip_column = st.selectbox(
        "Round-trip yes/no column (optional)",
        [None, *source.columns],
        format_func=lambda value: (
            "No column: use the setting below" if value is None else str(value)
        ),
        key=prefix + "-round-trip-column",
    )
    always_round_trip = False
    if round_trip_column is None:
        always_round_trip = st.checkbox(
            "All journeys are round trips", value=False, key=prefix + "-round-trip"
        )
        st.caption(
            "Unchecked: all rows are one-way journeys (default). "
            "Checked: all estimates are doubled."
        )
    else:
        st.caption(
            "Accepted values: yes/no, oui/non, true/false or 1/0. "
            "Empty or unknown values are reported as errors."
        )
    st.info(
        "A round trip doubles the one-way estimate. Do not enable it if return segments are already "
        "listed separately. Taxi estimates already include an empty vehicle return; "
        "the passenger round-trip setting is applied in addition. "
        "Car and taxi estimates are per vehicle; passenger counts are not interpreted."
    )

    aliases = {}
    with st.expander("Transport mode labels", expanded=True):
        st.caption("One label per line. Multi-word labels stay on a single line.")
        for mode, defaults in MODE_ALIASES.items():
            text = st.text_area(
                mode.capitalize(),
                value="\n".join(defaults),
                key=f"{prefix}-aliases-{mode}",
            )
            aliases[mode] = [
                value.strip() for value in text.splitlines() if value.strip()
            ]

    cache_upload = st.file_uploader(
        "Geocoding cache (.json, optional)", type=["json"], key=prefix + "-cache",
        on_change=replace_document, args=("advanced-cache",),
    )
    cache_bytes = cache_upload.getvalue() if cache_upload else None
    offline = st.checkbox(
        "Offline: use cached coordinates only", key=prefix + "-offline"
    )
    st.caption(
        "Online calculation sends city/country pairs to OpenStreetMap Nominatim. "
        "Uncached locations are requested sequentially, at least 1.1 seconds apart. "
        "Keep the downloaded cache to reuse coordinates in later runs."
    )
    user_agent = st.text_input(
        "Geocoding User-Agent",
        value="CARIBOU-carbon-footprint-ui/1.0 (academic research)",
        help="Use an identifiable application name and contact email for production use.",
        key=prefix + "-user-agent",
    )
    signature = sha256(
        raw
        + json.dumps(
            [
                sheet,
                header,
                mapping,
                mission_mapping,
                aggregate,
                dayfirst,
                aliases,
                round_trip_column,
                always_round_trip,
                offline,
                user_agent,
            ],
            sort_keys=True,
            default=str,
        ).encode()
        + (cache_bytes or b"")
    ).hexdigest()

    if st.button("Calculate emissions", type="primary", key=prefix + "-calculate"):
        st.session_state.pop("advanced-emission-result", None)
        bar = st.progress(0, text="Preparing OpenStreetMap requests…")
        status = st.empty()
        status.info("Validating mission information…")
        try:
            # Validate metadata before any network request. Emissions are checked
            # after calculation; placeholders only enable metadata validation here.
            _, metadata_errors = prepare(
                source.assign(**{"carbon footprint": 1.0}),
                mission_mapping,
                aggregate=aggregate,
                dayfirst=dayfirst,
                keep_empty_teams=True,
            )
            if metadata_errors:
                raise ValueError(" ".join(metadata_errors))
            if not offline and not user_agent.strip():
                raise ValueError(
                    "Provide a geocoding User-Agent for online calculation."
                )
            last_stage = None

            def update(stage, completed, total):
                nonlocal last_stage
                if stage == "geocoding":
                    if total:
                        bar.progress(
                            int(100 * completed / total),
                            text=f"OpenStreetMap requests: {completed}/{total}",
                        )
                        status.info("Resolving uncached locations…")
                    else:
                        bar.empty()
                        status.info(
                            "No OpenStreetMap requests needed (cached locations or offline mode)."
                        )
                elif last_stage != stage:
                    status.info("Calculating emissions..." if stage == "emissions"
                                else "Preparing workbook and error report…")
                last_stage = stage

            with st.spinner("Estimating emissions and resolving uncached locations…"):
                result = calculate(
                    raw,
                    sheet,
                    mapping,
                    aliases,
                    header=int(header),
                    round_trip_column=round_trip_column,
                    always_round_trip=always_round_trip,
                    cache_bytes=cache_bytes,
                    offline=offline,
                    user_agent=user_agent.strip(),
                    progress=update,
                )
            st.session_state["advanced-emission-result"] = (signature, result)
            status.success("Calculation complete — review the results below.")
        except Exception as exc:
            bar.empty()
            status.empty()
            st.error(f"Unable to calculate emissions: {exc}")

    saved = st.session_state.get("advanced-emission-result")
    if saved is None or saved[0] != signature:
        return
    result = saved[1]
    st.success(
        f"Emissions calculated for {result.calculated} of {result.rows} travel rows."
    )
    if result.issues:
        st.warning(
            "Some rows could not be calculated. Their emissions are blank, not zero. "
            "Review the error report before preparing missions."
        )
        st.dataframe(pd.DataFrame(result.issues), use_container_width=True)
    stem = Path(upload.name).stem
    st.download_button(
        "Download error report",
        result.errors,
        file_name=stem + "_carbon_errors.csv",
        mime="text/csv",
        key=prefix + "-download-errors",
    )
    st.download_button(
        "Download geocoding cache",
        result.cache,
        file_name=stem + "_geocode_cache.json",
        mime="application/json",
        key=prefix + "-download-cache",
    )
    if result.issues:
        st.info(
            "Resolve calculation errors to enable the missions export and Visualization."
        )
        return None

    enriched = pd.read_excel(
        BytesIO(result.workbook), sheet_name=sheet, header=int(header) - 1, dtype=object
    )
    missions, errors = prepare(
        enriched, mission_mapping, aggregate=aggregate, dayfirst=dayfirst, keep_empty_teams=True
    )
    return render_validated(missions, errors, prefix + "-result")
