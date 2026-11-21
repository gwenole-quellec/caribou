# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Descriptive views of the validated consolidated mission data."""

import pandas as pd
import streamlit as st


def render(df):
    st.caption(
        "Consolidated data after mapping and optional segment grouping, before simulation."
    )
    years = st.multiselect(
        "Years", sorted(df.year.unique()), default=sorted(df.year.unique())
    )
    teams = st.multiselect(
        "Teams", sorted(df.team.unique()), default=sorted(df.team.unique())
    )
    types = st.multiselect(
        "Mission types",
        sorted(df.mission_type.unique()),
        default=sorted(df.mission_type.unique()),
    )
    view = df[
        df.year.isin(years) & df.team.isin(teams) & df.mission_type.isin(types)
    ].copy()
    if view.empty:
        st.info("No missions match these filters.")
        return
    a, b, c = st.columns(3)
    a.metric("Missions", len(view))
    b.metric("Travelers", view.person_id.nunique())
    c.metric("Emissions (t CO₂e)", f"{view.emissions_kg_co2e.sum()/1000:,.2f}")
    st.subheader("Annual emissions (kg CO₂e)")
    st.line_chart(view.groupby("year").emissions_kg_co2e.sum())
    st.subheader("Monthly emissions (kg CO₂e)")
    st.line_chart(view.set_index("start_date").emissions_kg_co2e.resample("MS").sum())
    st.subheader("Emissions by team and mission type (kg CO₂e)")
    st.bar_chart(
        view.pivot_table(
            index="team",
            columns="mission_type",
            values="emissions_kg_co2e",
            aggfunc="sum",
            fill_value=0,
        )
    )
    st.subheader("Distribution of emissions per mission")
    bins = pd.cut(view.emissions_kg_co2e, bins=20)
    counts = bins.value_counts(sort=False)
    counts.index = counts.index.astype(str)
    st.bar_chart(counts.rename("Number of missions"))
    st.subheader("Cumulative emissions, from highest- to lowest-emitting missions")
    ordered = view.emissions_kg_co2e.sort_values(ascending=False).reset_index(drop=True)
    curve = pd.DataFrame(
        {
            "Cumulative missions (%)": [0.0]
            + [100 * (i + 1) / len(ordered) for i in range(len(ordered))],
            "Cumulative emissions (%)": [0.0]
            + (100 * ordered.cumsum() / ordered.sum()).tolist(),
        }
    )
    st.line_chart(curve, x="Cumulative missions (%)", y="Cumulative emissions (%)")
