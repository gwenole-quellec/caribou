# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Data preparation application."""

from hashlib import sha256
from io import BytesIO
import pandas as pd
import streamlit as st
from caribou_ui.workbooks import COLUMNS, suggest_mapping, prepare, export_workbook
from caribou_ui.visualizations import render


st.set_page_config(page_title="CARIBOU", page_icon="🦌", layout="wide")
st.title("🦌 CARIBOU")
st.caption("Prepare missions and explore their carbon footprint")
st.sidebar.info(
    (
        "Data is processed in memory in this instance. No geocoding or "
        "automatic emissions estimation is performed. Use previously "
        "estimated emissions for all segments."
    )
)
upload = st.sidebar.file_uploader("Consolidated Excel workbook", type=["xlsx"])
if upload is None:
    st.info(
        (
            "Upload a consolidated workbook to begin. Mission identifiers must "
            "be unique across travelers and years; traveler identifiers must "
            "remain stable."
        )
    )
    st.stop()
raw = upload.getvalue()
key = sha256(raw).hexdigest()[:16]
try:
    book = pd.ExcelFile(BytesIO(raw), engine="openpyxl")
    sheet = st.sidebar.selectbox(
        "Source worksheet", book.sheet_names, key=f"sheet-{key}"
    )
    header = st.sidebar.number_input(
        "Header row", min_value=1, value=1, step=1, key=f"header-{key}-{sheet}"
    )
    source = pd.read_excel(book, sheet_name=sheet, header=int(header) - 1, dtype=object)
    book.close()
except Exception as exc:
    st.error(f"Unable to read the workbook : {exc}")
    st.stop()
context = f"{key}-{sheet}-{header}"
import_tab, export_tab, viz_tab = st.tabs(
    ["Import and mapping", "Validation and export", "Visualizations"]
)
with import_tab:
    st.dataframe(source.head(100), use_container_width=True)
    st.caption(
        f"{len(source)} rows; preview limited to the first 100. Empty rows are not automatically removed."
    )
    guesses = suggest_mapping(source.columns)
    mapping = {}
    for field in COLUMNS:
        options = [None, *source.columns]
        mapping[field] = st.selectbox(
            field,
            options,
            index=options.index(guesses[field]),
            format_func=lambda v: "— Select a column —" if v is None else str(v),
            key=f"{context}-{field}",
        )
    st.caption(
        (
            "If year is not mapped, it is taken from start_date."
        )
    )
    aggregate = st.checkbox("Combine travel segments into complete missions", key=f"aggregate-{context}")
    st.caption(
        (
            "Check this if several rows describe segments of the same mission and share "
            "the same mission_id. Emissions are summed and the earliest departure date "
            "is retained. Traveler, team, mission type and year must match across segments."
            "  \n"
            "Leave unchecked if each row already represents a complete mission. Duplicate "
            "mission IDs will then block export."
        )
    )
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
        "Read ambiguous text dates as day/month/year", value=True, key=f"dates-{context}"
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
missions, errors = prepare(source, mapping, aggregate, tonnes, dayfirst)
with export_tab:
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
        st.info(
            (
                "Correct the source data or mapping to enable export."
            )
        )
    else:
        st.success(
            f"{len(missions)} missions validated — compatible with the CARIBOU simulator."
        )
        st.dataframe(missions, use_container_width=True)
        st.download_button(
            "Download missions workbook",
            export_workbook(missions),
            file_name="caribou_missions.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
with viz_tab:
    if errors:
        st.info("Validate the data to display visualizations.")
    else:
        render(missions)
