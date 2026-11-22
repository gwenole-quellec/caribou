# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Main application."""

from hashlib import sha256
from io import BytesIO

import pandas as pd
import streamlit as st

from caribou_ui.advanced import render_advanced
from caribou_ui.preparation import render_missions
from caribou_ui.visualizations import render
from caribou_ui.simulation import render_simulation
from caribou_ui.artifacts import render_artifacts


st.set_page_config(page_title="CARIBOU", page_icon="🦌", layout="wide")
st.title("🦌 CARIBOU")
st.markdown(
    "Explore your team’s travel emissions and compare carbon-budget scenarios.\n\n"
    "**1. Prepare your data** — Choose **Simple preparation** if emissions are already "
    "calculated, or **Advanced preparation** to estimate them from travel locations and "
    "transportation modes. Already have a CARIBOU missions workbook? Go straight to **Simulation**.\n\n"
    "**2. Explore** — Inspect your data, filter the charts and generate a dataset summary in **Visualization**.\n\n"
    "**3. Simulate** — Set reduction targets and compare individual versus shared team budgets, "
    "using prepared data or an uploaded missions workbook.\n\n"
    "**4. Export** — Generate, preview and download figures and the summary table in **Artifacts**."
)
with st.expander("Keeping your results"):
    st.write(
        "Prepared data and results are held temporarily in this session. Download the files "
        "you want to keep before closing or restarting the app. Nothing is automatically saved "
        "to your project folders. You can upload a saved missions workbook or simulation reports "
        "later to continue."
    )


def render_simple():
    """Import, map, validate and export previously estimated emissions."""
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
            source = pd.read_excel(
                book, sheet_name=sheet, header=int(header) - 1, dtype=object
            )
    except Exception as exc:
        st.error(f"Unable to read the workbook: {exc}")
        return None

    st.dataframe(source.head(100), use_container_width=True)
    st.caption(
        f"{len(source)} rows; preview limited to the first 100. Empty rows are not automatically removed."
    )
    return render_missions(source, f"{key}-{sheet}-{header}")


simple_tab, advanced_tab, viz_tab, simulation_tab, artifacts_tab = st.tabs(
    ["1. Simple preparation", "1. Advanced preparation", "2. Visualization", "3. Simulation", "4. Artifacts"]
)

with simple_tab:
    simple_missions = render_simple()

with advanced_tab:
    advanced_missions = render_advanced()

with viz_tab:
    available = {}
    if simple_missions is not None:
        available["Simple preparation"] = simple_missions
    if advanced_missions is not None:
        available["Advanced preparation"] = advanced_missions

    if not available:
        st.info(
            "Prepare valid missions in either Simple preparation or Advanced preparation to display visualizations."
        )
    else:
        mode = st.radio("Data source", list(available), horizontal=True)
        st.caption(f"Showing validated missions from {mode}.")
        render(available[mode], context=mode)



with simulation_tab:
    render_simulation(available)


with artifacts_tab:
    render_artifacts()
