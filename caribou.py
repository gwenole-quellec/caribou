# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Data preparation application."""

from hashlib import sha256
from io import BytesIO

import pandas as pd
import streamlit as st

from caribou_ui.advanced import render_advanced
from caribou_ui.preparation import render_missions
from caribou_ui.visualizations import render


st.set_page_config(page_title="CARIBOU", page_icon="🦌", layout="wide")
st.title("🦌 CARIBOU")
st.caption("Prepare missions and explore their carbon footprint")


def render_simple():
    """Import, map, validate and export previously estimated emissions."""
    st.subheader("Prepare missions from existing emissions")
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


simple_tab, advanced_tab, viz_tab = st.tabs(
    ["Simple preparation", "Advanced preparation", "Visualization"]
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

