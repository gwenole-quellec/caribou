# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Generate and preview simulation figures and tables in Streamlit."""

from hashlib import sha256
import json
import streamlit as st

from caribou_simulation.artifacts import ARTIFACTS, generate_artifacts
from caribou_ui.reports import report_summary, uploaded_reports
from caribou_ui.session import replace_document, clear_artifacts


# ==================================================================================================
# Category display settings
# ==================================================================================================

def category_controls(reports):
    """Collect figure-only category visibility and display names."""
    name, content = next(iter(reports.items()))
    report = report_summary(name, content)
    summary = next(iter(report["summary_by_lambda"].values()))["breakdowns"]
    settings = {}
    with st.expander("Mission preservation breakdown settings"):
        st.caption("Hide categories and edit their display names, for example to use English labels. "
                   "These settings only change the figure; missions and simulation results remain "
                   "unchanged.")
        for section, title in [("by_mission_type", "Mission purposes"),
                               ("by_personnel_category", "Personnel categories")]:
            st.markdown(f"**{title}**")
            labels = sorted(summary[section], key=str.casefold)
            hidden = st.multiselect("Categories to hide — " + title.lower(), labels,
                                    key="artifact-hidden-" + section)
            names = {}
            for label in labels:
                if label in hidden:
                    continue
                key = sha256((section + label).encode()).hexdigest()[:16]
                name = st.text_input(label, value=label, key="artifact-label-" + key)
                if name != label:
                    names[label] = name
            settings[section] = {"hidden": hidden, "labels": names}
    return settings


# ==================================================================================================
# Artifact interface
# ==================================================================================================

@st.fragment
def render_artifacts():
    """Use the last completed simulation or uploaded reports to build artifacts."""
    st.subheader("Generate figures and tables")
    st.caption(
        "Choose the last completed simulation or upload its result ZIP/JSON files. Generate "
        "figures and an outcome table, preview them here, then download individual files or one ZIP."
    )
    with st.expander("How it works"):
        st.write(
            "Figures are available as PNG for quick use and PDF for publication; the outcome "
            "table is available as Markdown and LaTeX. Table pooling must be one of the simulated "
            "fractions, and comparisons require the no-pooling baseline (0)."
        )
        st.write(
            "Last completed simulation refers to a saved result snapshot, even if you have since "
            "edited Simulation settings without rerunning. Results describe hypothetical scenarios, "
            "not predictions. Download files to retain them beyond this session."
        )
    saved = st.session_state.get("simulation-result")
    options = (["Last completed simulation"] if saved else []) + [
        "Upload simulation results"
    ]
    source = st.radio(
        "Artifact source", options, horizontal=True, key="artifact-source"
    )
    reports = saved[1] if saved and source == "Last completed simulation" else None
    if source == "Upload simulation results":
        upload_format = st.radio(
            "Report format", ["Result ZIP", "JSON reports"], horizontal=True,
            key="artifact-upload-format", on_change=replace_document, args=("artifact-format",),
        )
        if upload_format == "Result ZIP":
            upload = st.file_uploader(
                "Simulation result ZIP", type=["zip"], key="artifact-upload",
                on_change=replace_document, args=("artifact-reports",),
            )
            uploads = [upload] if upload is not None else []
        else:
            uploads = st.file_uploader(
                "JSON reports from one simulation run", type=["json"], accept_multiple_files=True,
                key="artifact-json-upload", on_change=replace_document, args=("artifact-reports",),
            )
            st.caption("Select one run's JSON files together. Clear the selection before loading another run.")
        if uploads:
            try:
                reports = uploaded_reports(
                    [(upload.name, upload.getvalue()) for upload in uploads]
                )
            except Exception as exc:
                st.error(f"Unable to read simulation results: {exc}")
                return
    st.caption(
        "Artifact templates use targets 5, 10, 15 and 20%. Governance and traveler restrictions "
        "need pooling fractions 0, 0.2, 0.5 and 1; the category breakdown needs 0, 0.2 and 0.5. "
        "Keep per-rule results enabled when simulating."
    )
    selected = st.multiselect(
        "Artifacts to generate",
        list(ARTIFACTS),
        default=list(ARTIFACTS),
        key="artifact-selection",
    )
    with st.expander("Outcome table settings"):
        pooling = st.number_input(
            "Table pooling fraction",
            min_value=0.0,
            max_value=1.0,
            value=0.5,
            step=0.1,
            key="artifact-pooling",
            help="Select a pooling fraction present in your simulation reports. "
                 "The table reports paired changes relative to no pooling (0).",
        )
        decimals = st.number_input(
            "Decimal places",
            min_value=0,
            max_value=4,
            value=1,
            step=1,
            key="artifact-decimals",
            help="Display precision only; this does not rerun or change the simulation.",
        )
    if not reports:
        st.info(
            "Run a simulation first, or upload the downloaded result ZIP or JSON reports."
        )
        return
    try:
        targets = [
            report_summary(name, content)["target_reduction_percent"]
            for name, content in reports.items()
        ]
        st.caption(
            "Available reduction targets: "
            + ", ".join(f"{target:g}%" for target in sorted(targets))
        )
    except Exception as exc:
        st.error(f"Invalid reports: {exc}")
        return
    category_settings = {}
    if "Mission preservation by category" in selected:
        try:
            category_settings = category_controls(reports)
        except Exception as exc:
            st.error(f"Unable to read category settings: {exc}")
            return
    digest = sha256()
    for name, content in sorted(reports.items()):
        digest.update(name.encode())
        digest.update(report_summary(name, content)["identity"].encode())
    digest.update(json.dumps([selected, pooling, decimals, category_settings]).encode())
    signature = digest.hexdigest()
    if st.button(
        "Generate artifacts",
        type="primary",
        disabled=not selected,
        key="artifact-generate",
    ):
        clear_artifacts()
        bar = st.progress(0, text="Preparing artifact generation…")
        try:

            def update(done, total):
                bar.progress(
                    int(100 * done / total),
                    text=f"Generating artifacts: {done}/{total}",
                )

            files, errors, archive = generate_artifacts(
                reports, selected, pooling, int(decimals), progress=update,
                category_settings=category_settings
            )
            st.session_state["artifact-result"] = (signature, files, errors, archive)
            st.session_state["artifact-result-source"] = source
        except Exception as exc:
            bar.empty()
            st.error(f"Unable to generate artifacts: {exc}")
    result = st.session_state.get("artifact-result")
    if result is None or result[0] != signature:
        return
    _, files, errors, archive = result
    for label, message in errors.items():
        st.warning(
            f"{label} could not be generated. "
            "Check that all required targets and pooling fractions are available."
        )
        with st.expander(label + " — details"):
            st.code(message, language="text")
    if not files:
        return
    st.success("Artifacts are ready.")
    st.download_button(
        "Download all artifacts (.zip)",
        lambda: archive,
        on_click="ignore",
        file_name="caribou_artifacts.zip",
        mime="application/zip",
        key="artifact-download-all",
    )
    for label in selected:
        stem = ARTIFACTS[label]
        matching = {
            name: content
            for name, content in files.items()
            if name.startswith(stem + ".")
        }
        if not matching:
            continue
        st.subheader(label)
        if stem + ".png" in matching:
            st.image(matching[stem + ".png"])
        if stem + ".md" in matching:
            st.markdown(matching[stem + ".md"].decode("utf-8"), unsafe_allow_html=False)
        for name, content in matching.items():
            mime = (
                "image/png"
                if name.endswith(".png")
                else (
                    "application/pdf"
                    if name.endswith(".pdf")
                    else "text/markdown" if name.endswith(".md") else "text/plain"
                )
            )
            st.download_button(
                "Download " + name,
                lambda content=content: content,
                on_click="ignore",
                file_name=name,
                mime=mime,
                key="artifact-download-" + name,
            )
