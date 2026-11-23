# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Session-local report storage and lightweight summaries for large result sets."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import ZipFile

import ijson
from ijson.common import ObjectBuilder
import streamlit as st


MAX_SUMMARIES = 8


def result_directory():
    """Keep large reports on disk for the session, outside project folders."""
    if "report-storage" not in st.session_state:
        st.session_state["report-storage"] = TemporaryDirectory(prefix="caribou-session-")
    directory = Path(st.session_state["report-storage"].name) / uuid4().hex
    directory.mkdir()
    return directory


def result_bytes(content):
    """Read disk-backed downloads only when explicitly requested."""
    return content.read_bytes() if isinstance(content, Path) else content


def report_header(raw):
    """Read summaries before the final draws array without materializing rules.

    Figure workers validate complete reports when generation is requested.
    """
    builder = ObjectBuilder()
    with raw.open("rb") if isinstance(raw, Path) else BytesIO(raw) as stream:
        events = ijson.parse(stream, use_float=True)
        for prefix, event, value in events:
            if prefix == "draws":
                header = builder.value
                required = {"input", "target_reduction_percent", "summary_by_lambda",
                            "schema_version"}
                if not isinstance(header, dict) or not required <= header.keys():
                    raise ValueError(
                        "The report must contain its summaries before per-rule results."
                    )
                if event == "null":
                    header["draws"] = False
                elif event == "start_array":
                    _, first_event, _ = next(events)
                    if first_event not in {"start_map", "end_array"}:
                        raise ValueError("Per-rule results must be JSON objects.")
                    header["draws"] = first_event != "end_array"
                else:
                    raise ValueError("Expected a per-rule array or null.")
                return header
            builder.event(event, value)
    raise ValueError("Missing per-rule results field.")


def report_summary(name, raw, parsed=None):
    """Cache only compact summaries; disk-backed reports never become large dicts."""
    cache = st.session_state.setdefault("report-summary-cache", {})
    key = (name, raw)
    if key in cache:
        return cache[key]
    report = report_header(raw) if parsed is None else parsed
    # Session paths are unique and immutable; avoid rereading whole files to hash them.
    identity = str(raw) if isinstance(raw, Path) else sha256(raw).hexdigest()
    summary = {
        "input": report["input"],
        "target_reduction_percent": report["target_reduction_percent"],
        "summary_by_lambda": report["summary_by_lambda"],
        "identity": identity,
    }
    while len(cache) >= MAX_SUMMARIES:
        del cache[next(iter(cache))]
    cache[key] = summary
    return summary


def uploaded_reports(uploads):
    """Extract uploads to session files once, reading only their small headers."""
    identity = tuple(uploads)
    saved = st.session_state.get("uploaded-report-cache")
    if saved is not None and saved[0] == identity:
        return saved[1]
    directory = result_directory()
    reports = {}

    def store(name, stream):
        name = Path(name).name
        if not re.fullmatch(r"budget_allocation_\d+(?:p\d+)?pct\.json", name):
            raise ValueError(f"Unrecognized simulation report filename: {name}")
        if name in reports:
            raise ValueError(f"Duplicate report: {name}")
        path = directory / name
        with path.open("wb") as output:
            shutil.copyfileobj(stream, output, length=1024 * 1024)
        header = report_header(path)
        if header["schema_version"] != "1.0" or not header["draws"]:
            raise ValueError("Artifact generation requires reports with per-rule results.")
        report_summary(name, path, header)
        reports[name] = path

    try:
        for name, raw in uploads:
            if name.lower().endswith(".zip"):
                with ZipFile(BytesIO(raw)) as archive:
                    for entry in archive.infolist():
                        filename = Path(entry.filename).name
                        if not entry.is_dir() and filename.startswith("budget_allocation_") \
                            and filename.endswith(".json"):
                            with archive.open(entry) as stream:
                                store(filename, stream)
            else:
                with BytesIO(raw) as stream:
                    store(name, stream)
        if not reports:
            raise ValueError("No simulation reports were found.")
    except Exception:
        shutil.rmtree(directory)
        raise
    st.session_state["uploaded-report-cache"] = (identity, reports)
    return reports
