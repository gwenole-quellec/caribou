# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Descriptive views of the validated consolidated mission data."""

from html import escape

import altair as alt
import pandas as pd
import streamlit as st

from caribou_ui.description import render_description


def render(df, context="missions"):
    original = df.copy()
    df = df.copy()
    df["mission_type"] = df["mission_type"].fillna("").replace("", "(Not specified)")
    df["team"] = df["team"].fillna("").replace("", "(No team)")
    st.caption(
        "Explore your prepared missions before simulation. Filters apply to every chart and the "
        "dataset description below. They do not change the missions workbook or the data sent "
        "to Simulation; use the simulation exclusions to change which mission types are included."
    )
    years = st.multiselect(
        "Years",
        sorted(df.year.unique()),
        default=sorted(df.year.unique()),
        key=f"{context}-years",
    )
    teams = st.multiselect(
        "Teams",
        sorted(df.team.unique()),
        default=sorted(df.team.unique()),
        key=f"{context}-teams",
    )
    types = st.multiselect(
        "Mission types",
        sorted(df.mission_type.unique()),
        default=sorted(df.mission_type.unique()),
        key=f"{context}-types",
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
    categories = sorted(df.mission_type.unique())
    palette = [
        "#0072B2", "#E69F00", "#009E73", "#CC3311", "#AA4499",
        "#6F4E37", "#56B4E9", "#8A8F00", "#EE6677", "#555555",
        "#332288", "#44AA99", "#882255", "#999933", "#661100",
        "#6699CC", "#AA4466", "#447744", "#CCAA77", "#7777AA",
    ]
    if len(categories) > len(palette):
        from colorsys import hls_to_rgb
        for index in range(len(palette), len(categories)):
            rgb = hls_to_rgb((index * 0.61803398875) % 1, 0.45, 0.65)
            palette.append("#" + "".join(f"{round(value * 255):02x}" for value in rgb))
    totals = view.groupby(["team", "mission_type"], as_index=False).emissions_kg_co2e.sum()
    chart = alt.Chart(totals).mark_bar().encode(
        x=alt.X("team:N", title="Team", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("emissions_kg_co2e:Q", title="Emissions (kg CO₂e)", stack="zero"),
        color=alt.Color(
            "mission_type:N", title="Mission type",
            scale=alt.Scale(domain=categories, range=palette[:len(categories)]),
            legend=None,
        ),
        tooltip=[alt.Tooltip("team:N", title="Team"),
                 alt.Tooltip("mission_type:N", title="Mission type"),
                 alt.Tooltip("emissions_kg_co2e:Q", title="Emissions (kg CO₂e)", format=",.1f")],
    )
    st.altair_chart(chart, use_container_width=True)
    colors = dict(zip(categories, palette))
    legend_items = "".join(
        '<span role="listitem" style="display:flex;align-items:center;gap:6px;white-space:nowrap;" '
        f'title="{escape(label)}"><span aria-hidden="true" style="display:inline-block;'
        f'width:11px;height:11px;background:{colors[label]};flex-shrink:0;"></span>'
        f'{escape(label)}</span>'
        for label in sorted(view.mission_type.unique())
    )
    st.markdown(
        '<div style="overflow-x:auto;padding:4px 0 10px;">'
        '<div role="list" aria-label="Mission type legend" style="display:grid;'
        'grid-template-rows:repeat(2,auto);grid-auto-flow:column;grid-auto-columns:max-content;'
        'gap:8px 24px;width:max-content;font-size:0.85rem;">'
        + legend_items + '</div></div>',
        unsafe_allow_html=True,
    )
    st.caption("Each color represents one complete mission-type label. "
               "Combined purposes remain a single category; emissions are counted once.")
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

    render_description(original.loc[view.index], context)
