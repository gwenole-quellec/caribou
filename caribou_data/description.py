# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Generate dataset-description artifacts for a selected mission view."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from caribou_data.workbooks import export_workbook


# ==================================================================================================
# Constants
# ==================================================================================================

WORKER = """
import sys
from pathlib import Path
import pandas as pd
from caribou_data.describe_missions import (
    calculate_summary, markdown_table, latex_table, plot_histogram,
)
source, destination, bins = sys.argv[1:]
frame = pd.read_excel(source, sheet_name="missions", dtype={"person_id": str, "team": str})
output = Path(destination)
rows, traveler_years = calculate_summary(frame)
exclusions = {"total": 0, "no_team": 0, "mission_type": 0}
(output / "table_dataset.md").write_text(markdown_table(rows, traveler_years, exclusions), encoding="utf-8")
(output / "table_dataset.tex").write_text(latex_table(rows, traveler_years, exclusions), encoding="utf-8")
plot_histogram(frame.emissions_kg_co2e.to_numpy(dtype=float), output, int(bins))
"""


# ==================================================================================================
# Dataset description generation
# ==================================================================================================

def describe_view(frame, bins=30):
    """Describe the selected rows."""
    if frame.empty or bins < 1:
        raise ValueError("A nonempty dataset and positive bin count are required.")
    with TemporaryDirectory(prefix="caribou-description-") as temporary:
        directory = Path(temporary)
        source = directory / "missions.xlsx"
        source.write_bytes(export_workbook(frame))
        environment = dict(os.environ)
        root = Path(__file__).resolve().parents[1]
        environment["PYTHONPATH"] = (
            str(root) + os.pathsep + environment.get("PYTHONPATH", "")
        )
        environment["MPLBACKEND"] = "Agg"
        environment["MPLCONFIGDIR"] = str(directory / "matplotlib")
        result = subprocess.run(
            [sys.executable, "-c", WORKER, str(source), str(directory), str(bins)],
            env=environment,
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode:
            raise ValueError((result.stderr or result.stdout)[-2000:])
        return {
            path.name: path.read_bytes()
            for path in directory.iterdir()
            if path.name.startswith(("table_dataset.", "fig_emissions_histogram."))
        }
