# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Invalidate document-derived state when an upload is replaced or removed."""

import streamlit as st

from caribou_ui.reports import clear_uploaded_reports, discard_report_files


def clear_artifacts():
    """Drop generated previews and downloads, leaving the input selection alone."""
    st.session_state.pop("artifact-result", None)
    st.session_state.pop("artifact-result-source", None)


def clear_simulation():
    """Drop completed reports and dependent artifacts, including session files."""
    saved = st.session_state.pop("simulation-result", None)
    st.session_state.pop("simulation-result-source", None)
    if saved is not None:
        discard_report_files(saved[1], saved[2])
    if st.session_state.get("artifact-result-source") == "Last completed simulation":
        clear_artifacts()


def replace_document(kind):
    """Uploader callback: invalidate old data before even reading the replacement."""
    if kind in {"simple-workbook", "advanced-workbook", "advanced-cache"}:
        mode = "Simple preparation" if kind == "simple-workbook" else "Advanced preparation"
        prefix = "simple-" if kind == "simple-workbook" else "advanced-"
        if kind != "advanced-cache":
            # Keep the newly uploaded file; discard old file-dependent mapping controls.
            for key in list(st.session_state):
                if key != prefix + "upload" and key.startswith((prefix, "sheet-" + prefix, "header-" + prefix)):
                    del st.session_state[key]
        if mode == "Advanced preparation":
            st.session_state.pop("advanced-emission-result", None)
        for key in list(st.session_state):
            if key.startswith(mode + "-"):
                del st.session_state[key]
        if st.session_state.get("simulation-result-source") == mode:
            clear_simulation()
    elif kind == "simulation-workbook":
        clear_simulation()
        st.session_state.pop("simulation-exclusions", None)
        # This uploader is inside a fragment: refresh dependent tabs once, too.
        st.session_state["document-refresh-pending"] = True
    elif kind in {"artifact-reports", "artifact-format"}:
        clear_artifacts()
        clear_uploaded_reports()
        if kind == "artifact-format":
            st.session_state.pop("artifact-upload", None)
            st.session_state.pop("artifact-json-upload", None)
        for key in list(st.session_state):
            if key.startswith(("artifact-label-", "artifact-hidden-")):
                del st.session_state[key]
    else:
        raise ValueError(f"Unknown document kind: {kind}")
