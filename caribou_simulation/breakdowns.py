# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — Category groups and descriptive restriction rates."""

import numpy as np
import pandas as pd


# ==================================================================================================
# Constants
# ==================================================================================================

DEFINITIONS = {
    "by_mission_type": "Refused missions / requested missions of each purpose, in percent. "
                       "Comma-separated purposes overlap: a mission counts once in each distinct purpose.",
    "by_personnel_category": "Refused missions / requested missions of each personnel category, in percent. "
                             "This is a mission rate, not a percentage of affected people.",
    "missing_labels": "Blank or unavailable labels are reported as Not specified.",
    "calibration": "Rates use the same whole-mission allocation lottery weights as the existing metrics.",
}


# ==================================================================================================
# Breakdown management
# ==================================================================================================

def build_groups(frame):
    """Build fixed denominators after eligibility filtering and mission sorting."""
    result = {}
    for section, column, multiple in [
        ("by_mission_type", "mission_type", True),
        ("by_personnel_category", "personnel_category", False),
    ]:
        groups, spelling = {}, {}
        values = frame[column].tolist() if column in frame else [""] * len(frame)
        for index, value in enumerate(values):
            text = "" if pd.isna(value) else str(value).strip()
            labels = text.split(",") if multiple else [text]
            labels = [label.strip() for label in labels if label.strip()] or ["Not specified"]
            for key in dict.fromkeys(label.casefold() for label in labels):
                spelling.setdefault(key, next(label for label in labels if label.casefold() == key))
                groups.setdefault(key, []).append(index)
        result[section] = {
            spelling[key]: np.asarray(indices, dtype=int)
            for key, indices in sorted(groups.items())
        }
    return result


def restriction_breakdowns(groups, accepted):
    """Measure refusals within each fixed group without changing decisions."""
    return {
        section: {
            label: {"requested_missions": len(indices),
                    "refused_missions_percent": float(100 * np.mean(~accepted[indices]))}
            for label, indices in categories.items()
        }
        for section, categories in groups.items()
    }


def interpolate_breakdowns(left, right, weight):
    """Interpolate rates, never the category denominators."""
    return {
        section: {
            label: {"requested_missions": entry["requested_missions"],
                    "refused_missions_percent": float(
                        weight * entry["refused_missions_percent"] +
                        (1 - weight) * right[section][label]["refused_missions_percent"]
                    )}
            for label, entry in categories.items()
        }
        for section, categories in left.items()
    }


def summarize_breakdowns(records, key, baseline, describe):
    """Summarize rates and within-rule differences from no pooling."""
    result = {}
    first = records[0]["by_lambda"][key]["breakdowns"]
    for section, categories in first.items():
        result[section] = {}
        for label, entry in categories.items():
            values = [record["by_lambda"][key]["breakdowns"][section][label]["refused_missions_percent"]
                      for record in records]
            summary = {"requested_missions": entry["requested_missions"],
                       "refused_missions_percent": describe(values)}
            if baseline is not None:
                summary["paired_difference_from_lambda_0_percentage_points"] = describe([
                    value - record["by_lambda"][baseline]["breakdowns"][section][label]["refused_missions_percent"]
                    for value, record in zip(values, records)
                ])
            result[section][label] = summary
    return result
