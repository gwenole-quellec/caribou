# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Run workbook simulations in isolation and return downloadable results."""

from io import BytesIO
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from caribou_simulation.explore_budget_allocation import parse_args, run


def simulate_workbook(workbook, settings, progress=None):
    """Return JSON reports and a ZIP; temporary input/output files are removed.

    Settings override the engine defaults. Progress is a (completed, total)
    callback; its last update marks computation, before reports are serialized.
    """
    with TemporaryDirectory(prefix="caribou-simulation-") as temporary:
        directory = Path(temporary)
        source = directory / "carbon_footprint.xlsx"
        source.write_bytes(workbook)
        args = parse_args(["--input", str(source)])
        allowed = set(vars(args)) - {"input", "output_dir"}
        if set(settings) - allowed:
            raise ValueError("Unknown simulation settings.")
        for key, value in settings.items():
            setattr(args, key, value)
        args.output_dir = directory / "results"
        paths = run(args, progress=progress)
        reports = {path.name: path.read_bytes() for path in paths}
        manifest = {
            "input_sha256": sha256(workbook).hexdigest(),
            "parameters": {
                key: value
                for key, value in vars(args).items()
                if key not in {"input", "output_dir"}
            },
        }
        archive = BytesIO()
        with ZipFile(archive, "w", ZIP_DEFLATED) as output:
            for name, data in reports.items():
                output.writestr(name, data)
            output.writestr("parameters.json", json.dumps(manifest, indent=2))
        return reports, archive.getvalue()
