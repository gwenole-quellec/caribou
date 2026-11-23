# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Streamlit controls for preparing the workbook."""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from caribou_data.emissions import FIELDS, MODE_ALIASES, calculate
from caribou_ui.preparation import mission_controls, render_missions, render_validated
from caribou_data.workbooks import prepare


# ==================================================================================================
# Rendering function (Simple preparation)
# ==================================================================================================

def render_simple():
    """Prepare existing emissions and return validated missions, or None.

    Worksheet selection and the preview belong here. Column mapping, mission
    aggregation, validation and workbook export are delegated to render_missions.
    """
    st.subheader("Prepare missions from existing emissions")
    st.caption(
        "Upload an Excel workbook with emissions already calculated. Each row may be a complete "
        "mission or a travel segment to combine. Match your columns below, then download the "
        "validated missions workbook or continue directly to Visualization and Simulation."
    )
    upload = st.file_uploader(
        "Consolidated Excel workbook", type=["xlsx"], key="simple-upload"
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
        "Travel workbook (.xlsx)", type=["xlsx"], key="advanced-upload"
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
            "Unchecked: all rows are one-way journeys (default). Checked: all estimates are doubled."
        )
    else:
        st.caption(
            "Accepted values: yes/no, oui/non, true/false or 1/0. Empty or unknown values are reported as errors."
        )
    st.info(
        "A round trip doubles the one-way estimate. Do not enable it if return segments "
        "are already listed separately. Taxi estimates already include an empty vehicle "
        "return; the passenger round-trip setting is applied in addition. "
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
        "Geocoding cache (.json, optional)", type=["json"], key=prefix + "-cache"
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
                        status.info("No OpenStreetMap requests needed (cached locations or offline mode).")
                elif last_stage != stage:
                    status.info("Calculating emissions…" if stage == "emissions" else "Preparing workbook and error report…")
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
            "Some rows could not be calculated. Their emissions are blank, not zero. Review the error report before preparing missions."
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
