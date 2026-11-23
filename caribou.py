# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Streamlit entry point connecting preparation, exploration and simulation.

Tab modules handle their own controls and calculations. This module passes validated mission tables
between them; simulation and artifact results are managed by those modules in Streamlit's session
state.
"""

import streamlit as st

from caribou_ui.preparation import render_simple, render_advanced
from caribou_ui.visualizations import render
from caribou_ui.simulation import render_simulation
from caribou_ui.artifacts import render_artifacts


# ==================================================================================================
# Configuration
# ==================================================================================================

st.set_page_config(page_title="CARIBOU", page_icon="🦌", layout="wide")
st.title("🦌 CARIBOU")
st.markdown(
    "Explore your team’s travel emissions and compare carbon-budget scenarios.\n\n"
    "**1. Prepare your data** — Choose **Simple preparation** if emissions are already "
    "calculated, or **Advanced preparation** to estimate them from travel locations and "
    "transportation modes. Already have a CARIBOU missions workbook? Go straight to **Simulation**.\n\n"
    "**2. Explore** — Inspect your data, filter the charts and generate a dataset summary in "
    "**Visualization**.\n\n"
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


# ==================================================================================================
# Rendering
# ==================================================================================================

# Streamlit reruns this script on interaction and executes every tab body,
# including hidden tabs. Prepare both sources before rendering downstream tabs.
simple_tab, advanced_tab, viz_tab, simulation_tab, artifacts_tab = st.tabs(
    ["1. Simple preparation", "1. Advanced preparation", "2. Visualization", "3. Simulation",
     "4. Artifacts"]
)

with simple_tab:
    simple_missions = render_simple()

with advanced_tab:
    advanced_missions = render_advanced()

with viz_tab:
    # Share only validated datasets. Keep both preparation modes independent so
    # users can choose a source without replacing the other mode's data.
    available = {}
    if simple_missions is not None:
        available["Simple preparation"] = simple_missions
    if advanced_missions is not None:
        available["Advanced preparation"] = advanced_missions

    if not available:
        st.info(
            "Prepare valid missions in either Simple preparation or Advanced preparation to display "
            "visualizations."
        )
    else:
        mode = st.radio("Data source", list(available), horizontal=True)
        st.caption(f"Showing validated missions from {mode}.")
        # The source context keeps visualization controls separate for each mode.
        render(available[mode], context=mode)

with simulation_tab:
    # Simulations can use either prepared dataset or their own workbook upload.
    render_simulation(available)

with artifacts_tab:
    # Artifacts use completed simulation results from session state or uploaded
    # reports; they do not depend on the visualization's selected source.
    render_artifacts()
