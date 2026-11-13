# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 CARIBOU contributors

"""CARIBOU — explore carbon-budget allocation for research travel.

Simulates individual (lambda=0), hybrid (0<lambda<1), and fully pooled team budgets using observed
research-travel missions. For each sampled prioritization rule, pooling fraction, and
carbon-reduction target, the annual reference allowance B0 is calibrated separately.

Five families of hypothetical decision-making behaviors are explored. Random effects are held fixed
across pooling fractions where applicable. These simulations characterize sensitivity to behavioral
assumptions, not probabilities of actual institutional decisions.

Carbon-reduction targets apply to aggregate emissions across study years and are matched in
expectation through a lottery between two feasible allocations of indivisible missions. Calibration
diagnostics are recorded in the JSON outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit
from scipy.stats import qmc


# ==================================================================================================
# Constants and experimental configuration
# ==================================================================================================

VERSION = "1.0.0"
SCHEMA_VERSION = "1.0"

DEFAULT_TARGETS = (5.0, 10.0, 15.0, 20.0)
LAMBDA_GRID_INTERVALS = 10
DEFAULT_LAMBDAS = tuple(
    i / LAMBDA_GRID_INTERVALS for i in range(LAMBDA_GRID_INTERVALS + 1)
)
DEFAULT_SEVERITY_THRESHOLD = 0.5

DEFAULT_DRAWS = 1000
DEFAULT_SEED = 42
DEFAULT_GRID = 24
DEFAULT_REFINE = 10
DEFAULT_MAX_BRACKET_PP = 2.0
LATIN_HYPERCUBE_DIMENSIONS = 8
PROGRESS_BAR_WIDTH = 30

CALIBRATION_GEOMETRIC_RANGE_RATIO = 20_000.0
CALIBRATION_MIN_BUDGET_KG_CO2E = 1e-5
CALIBRATION_BUDGET_DECIMALS = 9
CALIBRATION_UPPER_MARGIN = 1.01
CALIBRATION_UPPER_OFFSET_KG_CO2E = 1.0
NUMERICAL_TOLERANCE = 1e-9

FAMILY_SEQUENTIAL = 0
FAMILY_COST = 1
FAMILY_DISTRIBUTIVE = 2
FAMILY_LONGITUDINAL = 3
FAMILY_RANDOM = 4

FAMILIES = (
    "sequential",
    "cost",
    "distributive",
    "longitudinal",
    "random",
)

METRICS = (
    "refused_missions_percent",
    "affected_traveler_years_percent",
    "severely_affected_traveler_years_percent",
    "repeatedly_affected_travelers_percent",
)

REQUIRED_COLUMNS = (
    "mission_id",
    "year",
    "person_id",
    "team",
    "mission_type",
    "start_date",
    "emissions_kg_co2e",
)

# Sequential governance
SEQUENTIAL_RESERVE_FRACTION_RANGE = (0.0, 0.75)
SEQUENTIAL_RELEASE_POWER_RANGE = (0.5, 2.5)

# Carbon-cost governance
COST_COST_WEIGHT_RANGE = (-2.0, 2.0)
COST_NOISE_WEIGHT_RANGE = (0.02, 1.22)

# Distributive governance
DISTRIBUTIVE_COST_WEIGHT_RANGE = (-1.0, 1.0)
DISTRIBUTIVE_FAIRNESS_WEIGHT_RANGE = (0.2, 3.0)
DISTRIBUTIVE_NOISE_WEIGHT_RANGE = (0.05, 1.05)
DISTRIBUTIVE_CAP_MULTIPLE_RANGE = (1.0, 4.0)
DISTRIBUTIVE_NO_CAP_PROBABILITY = 0.35

# Longitudinal governance
LONGITUDINAL_COST_WEIGHT_RANGE = (-1.0, 1.0)
LONGITUDINAL_HISTORY_WEIGHT_RANGE = (0.0, 2.0)
LONGITUDINAL_PERSON_WEIGHT_RANGE = (0.0, 1.5)
LONGITUDINAL_NOISE_WEIGHT_RANGE = (0.1, 1.1)
LONGITUDINAL_CAP_MULTIPLE_RANGE = (1.0, 4.0)
LONGITUDINAL_NO_CAP_PROBABILITY = 0.5

# Random governance
RANDOM_PERSON_WEIGHT_RANGE = (0.0, 1.5)
RANDOM_NOISE_WEIGHT_RANGE = (0.1, 1.1)


# ==================================================================================================
# Data structures
# ==================================================================================================

@dataclass(frozen=True)
class Rule:
    """Hypothetical prioritization rule, not a fitted behavior model."""

    family: str
    cost_weight: float = 0.0
    fairness_weight: float = 0.0
    history_weight: float = 0.0
    person_weight: float = 0.0
    noise_weight: float = 0.0
    reserve_fraction: float = 0.0
    release_power: float = 1.0
    cap_multiple: float | None = None


@dataclass
class Missions:
    """Indexed records; person-level identifiers are not exported."""

    year: np.ndarray
    person: np.ndarray
    team: np.ndarray
    cost: np.ndarray
    cost_z: np.ndarray
    date_fraction: np.ndarray
    person_year: np.ndarray
    people: int
    person_years: int
    years: list[int]
    individual_groups: dict[tuple[int, int], np.ndarray]
    team_groups: dict[tuple[int, int], tuple[np.ndarray, int]]
    total: float
    metadata: dict
    year_offsets: np.ndarray | None = None
    team_headcounts: np.ndarray | None = None


# ==================================================================================================
# Input data
# ==================================================================================================

def load_missions(
    path: Path,
    exclude_mission_types: list[str],
    headcount: str,
) -> Missions:
    """Read complete missions and construct annual individual/team allocation groups.

    Rows with an empty team (including missing or whitespace-only values) are
    always ignored. Mission types specified by the user are also excluded,
    case-insensitively. Filtering precedes all validation and budget calculations.
    Team headcounts use eligible travelers, not the full staff roster.
    """
    df = pd.read_excel(path, sheet_name="missions")

    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing missions columns: {sorted(missing)}")

    original_count = len(df)
    team_names = df["team"].astype("string").fillna("").str.strip()
    missing_team_mask = team_names.eq("")

    excluded_types = {value.strip().casefold() for value in exclude_mission_types}
    excluded_types.discard("")
    types = df["mission_type"].astype("string").fillna("").str.strip().str.casefold()
    # Count each excluded mission once: missing team takes precedence.
    excluded_type_mask = (~missing_team_mask) & types.isin(excluded_types)
    eligible_mask = ~(missing_team_mask | excluded_type_mask)

    df = df.loc[eligible_mask].copy()
    df["team"] = team_names.loc[eligible_mask]

    if df.empty:
        raise ValueError("No eligible missions after filtering empty teams and mission types")
    if df[list(REQUIRED_COLUMNS)].isna().any().any():
        raise ValueError("Missing mandatory mission fields among eligible missions")
    if df.mission_id.duplicated().any():
        raise ValueError("Duplicated mission_id among eligible missions")

    df["start_date"] = pd.to_datetime(df.start_date, errors="raise")
    df["year"] = pd.to_numeric(df.year, errors="raise").astype(int)
    df["emissions_kg_co2e"] = pd.to_numeric(
        df.emissions_kg_co2e, errors="raise"
    )

    if (df.start_date.dt.year != df.year).any():
        raise ValueError("year must match start_date year")
    if not np.isfinite(df.emissions_kg_co2e).all() or (
        df.emissions_kg_co2e < 0
    ).any():
        raise ValueError("Emissions must be finite and nonnegative")

    df = df.sort_values(["year", "start_date", "mission_id"]).reset_index(drop=True)
    if df.emissions_kg_co2e.sum() <= 0:
        raise ValueError("No positive-emission eligible missions")

    person, _ = pd.factorize(df.person_id.astype(str), sort=True)
    team, _ = pd.factorize(df.team.astype(str), sort=True)
    year = df.year.to_numpy(dtype=int)
    cost = df.emissions_kg_co2e.to_numpy(dtype=float)

    cost_z = np.log1p(cost)
    cost_z = (cost_z - cost_z.mean()) / max(cost_z.std(), NUMERICAL_TOLERANCE)

    day = df.start_date.dt.dayofyear.to_numpy(dtype=float)
    days_per_year = np.where(df.start_date.dt.is_leap_year, 366.0, 365.0)
    date_fraction = (day - 1) / days_per_year

    pairs = sorted(set(zip(person, year)))
    pair_indices = {pair: i for i, pair in enumerate(pairs)}
    person_year = np.array(
        [pair_indices[pair] for pair in zip(person, year)], dtype=int
    )

    individual_groups = {}
    team_groups = {}
    years = sorted(set(map(int, year)))

    for current_year in years:
        for p in set(person[year == current_year]):
            individual_groups[current_year, int(p)] = np.flatnonzero(
                (year == current_year) & (person == p)
            )

        for t in set(team[year == current_year]):
            indices = np.flatnonzero((year == current_year) & (team == t))
            if headcount == "annual-active":
                count = len(set(person[indices]))
            else:
                count = len(set(person[team == t]))
            team_groups[current_year, int(t)] = (indices, count)

    metadata = {
        "missions_original": original_count,
        "missions_excluded": int((~eligible_mask).sum()),
        "missions_excluded_no_team": int(missing_team_mask.sum()),
        "missions_excluded_mission_type": int(excluded_type_mask.sum()),
        "missions_included": len(df),
        "travelers": len(set(person)),
        "active_traveler_years": len(pairs),
        "years": years,
        "baseline_kg_co2e": float(cost.sum()),
        "headcount": headcount,
        "excluded_mission_types": sorted(excluded_types),
        "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }

    return Missions(
        year=year,
        person=person,
        team=team,
        cost=cost,
        cost_z=cost_z,
        date_fraction=date_fraction,
        person_year=person_year,
        people=len(set(person)),
        person_years=len(pairs),
        years=years,
        individual_groups=individual_groups,
        team_groups=team_groups,
        total=float(cost.sum()),
        metadata=metadata,
    )

# ==================================================================================================
# Sampling decision rules
# ==================================================================================================

def scale_parameter(value: float, bounds: tuple[float, float]) -> float:
    """Map a unit-cube design coordinate to a named parameter interval."""
    minimum, maximum = bounds
    return float(minimum + (maximum - minimum) * value)


def sample_rules(
    n: int,
    rng: np.random.Generator,
    sampling: str,
) -> list[Rule]:
    """Sample balanced rule families, with optional Latin-hypercube designs."""
    if n < 1:
        raise ValueError("draws must be positive")

    families = list(FAMILIES) * (n // len(FAMILIES))
    families += list(FAMILIES[: n % len(FAMILIES)])
    rng.shuffle(families)

    designs = {}
    for family in FAMILIES:
        count = families.count(family)
        if count == 0:
            continue
        if sampling == "latin":
            design = qmc.LatinHypercube(d=LATIN_HYPERCUBE_DIMENSIONS, seed=int(rng.integers(2**32)))
            designs[family] = design.random(count)
        else:
            designs[family] = rng.random((count, LATIN_HYPERCUBE_DIMENSIONS))

    next_row = dict.fromkeys(FAMILIES, 0)
    rules = []

    for family in families:
        values = designs[family][next_row[family]]
        next_row[family] += 1

        if family == "sequential":
            rule = Rule(
                family=family,
                reserve_fraction=scale_parameter(
                    values[0], SEQUENTIAL_RESERVE_FRACTION_RANGE
                ),
                release_power=scale_parameter(
                    values[1], SEQUENTIAL_RELEASE_POWER_RANGE
                ),
            )

        elif family == "cost":
            rule = Rule(
                family=family,
                cost_weight=scale_parameter(values[0], COST_COST_WEIGHT_RANGE),
                noise_weight=scale_parameter(values[1], COST_NOISE_WEIGHT_RANGE),
            )

        elif family == "distributive":
            rule = Rule(
                family=family,
                cost_weight=scale_parameter(
                    values[0], DISTRIBUTIVE_COST_WEIGHT_RANGE
                ),
                fairness_weight=scale_parameter(
                    values[1], DISTRIBUTIVE_FAIRNESS_WEIGHT_RANGE
                ),
                noise_weight=scale_parameter(
                    values[2], DISTRIBUTIVE_NOISE_WEIGHT_RANGE
                ),
                cap_multiple=(
                    None if values[3] < DISTRIBUTIVE_NO_CAP_PROBABILITY
                    else scale_parameter(values[4], DISTRIBUTIVE_CAP_MULTIPLE_RANGE)
                ),
            )

        elif family == "longitudinal":
            rule = Rule(
                family=family,
                cost_weight=scale_parameter(
                    values[0], LONGITUDINAL_COST_WEIGHT_RANGE
                ),
                history_weight=scale_parameter(
                    values[1], LONGITUDINAL_HISTORY_WEIGHT_RANGE
                ),
                person_weight=scale_parameter(
                    values[2], LONGITUDINAL_PERSON_WEIGHT_RANGE
                ),
                noise_weight=scale_parameter(
                    values[3], LONGITUDINAL_NOISE_WEIGHT_RANGE
                ),
                cap_multiple=(
                    None if values[4] < LONGITUDINAL_NO_CAP_PROBABILITY
                    else scale_parameter(values[5], LONGITUDINAL_CAP_MULTIPLE_RANGE)
                ),
            )

        elif family == "random":
            rule = Rule(
                family=family,
                person_weight=scale_parameter(
                    values[0], RANDOM_PERSON_WEIGHT_RANGE
                ),
                noise_weight=scale_parameter(
                    values[1], RANDOM_NOISE_WEIGHT_RANGE
                ),
            )

        else:
            raise ValueError(f"Unknown rule family: {family}")

        rules.append(rule)

    return rules


# ==================================================================================================
# Fast numerical selection core (optional Numba acceleration)
# ==================================================================================================

@njit(cache=True)
def _selection_core(
    person, team, cost, cost_z, date_fraction,
    year_offsets, team_headcounts, person_effect, mission_noise,
    pooling, b0, family, cost_weight, fairness_weight,
    history_weight, person_weight, noise_weight,
    reserve_fraction, release_power, cap_multiple,
):
    """Numerical counterpart of ``simulate`` for repeated budget evaluations.

    Requests are considered chronologically for sequential governance and within each team in
    priority order otherwise. Dynamic fairness and compensation are evaluated at their respective
    decision times.
    """
    n = len(cost)
    n_people = len(person_effect)
    n_teams = team_headcounts.shape[1]
    accepted = np.zeros(n, dtype=np.bool_)

    previous_requests = np.zeros(n_people)
    previous_refusals = np.zeros(n_people)
    processed = np.zeros(n, dtype=np.bool_)

    scale = (
        abs(cost_weight) + abs(person_weight) + abs(noise_weight)
        + abs(history_weight) + abs(fairness_weight)
    )
    if scale == 0:
        scale = 1.0

    for y in range(len(year_offsets) - 1):
        start = year_offsets[y]
        stop = year_offsets[y + 1]
        individual_spent = np.zeros(n_people)
        total_spent = np.zeros(n_people)
        requested = np.zeros(n_people)
        refused = np.zeros(n_people)
        team_spent = np.zeros(n_teams)
        team_budgets = pooling * team_headcounts[y] * b0
        personal_budget = (1 - pooling) * b0

        history = np.zeros(n_people)
        for p in range(n_people):
            if previous_requests[p] > 0:
                history[p] = previous_refusals[p] / previous_requests[p]

        # Team-by-team planning; chronology instead uses the entire year's
        # date-sorted sequence, including any traveler switching teams.
        group_count = 1 if family == FAMILY_SEQUENTIAL else n_teams

        for group in range(group_count):
            while True:
                best_index = -1
                best_score = -np.inf

                for idx in range(start, stop):
                    if processed[idx]:
                        continue
                    if family != FAMILY_SEQUENTIAL and team[idx] != group:
                        continue

                    p = person[idx]
                    if family == FAMILY_SEQUENTIAL:
                        best_index = idx
                        break

                    score = (
                        cost_weight * cost_z[idx]
                        + person_weight * person_effect[p]
                        + noise_weight * mission_noise[idx]
                    ) / scale

                    if pooling > 0 and family == FAMILY_LONGITUDINAL:
                        score += history_weight * history[p] / scale
                    if pooling > 0 and family == FAMILY_DISTRIBUTIVE:
                        score -= fairness_weight * total_spent[p] / max(b0, NUMERICAL_TOLERANCE) / scale

                    # Stable ties are resolved by the original date-sorted order.
                    if score > best_score:
                        best_score = score
                        best_index = idx

                if best_index == -1:
                    break

                idx = best_index
                processed[idx] = True
                p = person[idx]
                t = team[idx]
                c = cost[idx]
                requested[p] += 1

                released = 1.0
                if family == FAMILY_SEQUENTIAL:
                    released = (
                        1 - reserve_fraction
                        + reserve_fraction * date_fraction[idx] ** release_power
                    )

                available_personal = max(0.0, personal_budget * released - individual_spent[p])
                available_pooled = max(0.0, team_budgets[t] * released - team_spent[t])

                personal_cap = np.inf
                if pooling > 0 and cap_multiple > 0:
                    personal_cap = cap_multiple * b0

                affordable = c <= available_personal + available_pooled + NUMERICAL_TOLERANCE
                below_cap = total_spent[p] + c <= personal_cap + NUMERICAL_TOLERANCE

                if affordable and below_cap:
                    personal_charge = min(c, available_personal)
                    accepted[idx] = True
                    individual_spent[p] += personal_charge
                    team_spent[t] += c - personal_charge
                    total_spent[p] += c
                else:
                    refused[p] += 1

        previous_requests += requested
        previous_refusals += refused

    return accepted


def _prepare_fast_inputs(data: Missions) -> None:
    """Cache year offsets and team sizes, which do not depend on B0/lambda."""
    if data.year_offsets is not None:
        return

    offsets = [0]
    for year in data.years:
        offsets.append(offsets[-1] + int(np.sum(data.year == year)))

    counts = np.zeros((len(data.years), int(data.team.max()) + 1))
    year_index = {year: i for i, year in enumerate(data.years)}
    for (year, team), (_, count) in data.team_groups.items():
        counts[year_index[year], team] = count

    data.year_offsets = np.asarray(offsets, dtype=np.int64)
    data.team_headcounts = counts


# ==================================================================================================
# Allocation and mission selection
# ==================================================================================================

def simulate(
    data: Missions,
    pooling: float,
    rule: Rule,
    b0: float,
    person_effect: np.ndarray,
    mission_noise: np.ndarray,
) -> np.ndarray:
    """Accept whole missions with individual-first, team-second financing.

    Every traveler starts each year with (1-pooling)*B0. Each team receives pooling*headcount*B0.
    A mission is accepted only when its *entire* carbon cost can be covered by the available
    personal and team balances together.

    Sequential rules process requests by departure date; other rules know all requests of the year
    (retrospective planning). With pooled resources, distributive rules update traveler priority
    after each acceptance.
    """
    if not 0 <= pooling <= 1 or b0 < 0:
        raise ValueError("pooling must be in [0, 1] and B0 must be nonnegative")

    _prepare_fast_inputs(data)
    return _selection_core(
        data.person, data.team, data.cost, data.cost_z,
        data.date_fraction, data.year_offsets, data.team_headcounts,
        person_effect, mission_noise, pooling, b0,
        FAMILIES.index(rule.family), rule.cost_weight,
        rule.fairness_weight, rule.history_weight,
        rule.person_weight, rule.noise_weight,
        rule.reserve_fraction, rule.release_power,
        rule.cap_multiple if rule.cap_multiple is not None else -1.0,
    )


# ==================================================================================================
# Restriction outcomes
# ==================================================================================================

def restriction_metrics(
    data: Missions,
    accepted: np.ndarray,
    severity_threshold: float = DEFAULT_SEVERITY_THRESHOLD,
) -> dict[str, float | None]:
    """Compute four restriction metrics with explicit fixed denominators."""
    if not 0 < severity_threshold <= 1:
        raise ValueError("severity_threshold must be in (0, 1]")

    requested = np.bincount(data.person_year, minlength=data.person_years)
    refused = np.bincount(
        data.person_year,
        weights=(~accepted).astype(float),
        minlength=data.person_years,
    )

    affected = refused > 0
    severe = refused / requested >= severity_threshold

    person_by_year = np.zeros(data.person_years, dtype=int)
    person_by_year[data.person_year] = data.person

    active_years = np.bincount(person_by_year, minlength=data.people)
    affected_years = np.bincount(
        person_by_year,
        weights=affected.astype(float),
        minlength=data.people,
    )

    recurrently_eligible = active_years >= 2
    repeated = (
        float(100 * np.mean(affected_years[recurrently_eligible] >= 2))
        if recurrently_eligible.any() else None
    )

    return {
        "refused_missions_percent": float(100 * np.mean(~accepted)),
        "affected_traveler_years_percent": float(100 * np.mean(affected)),
        "severely_affected_traveler_years_percent": float(100 * np.mean(severe)),
        "repeatedly_affected_travelers_percent": repeated,
    }


# ==================================================================================================
# Budget calibration
# ==================================================================================================

def upper_budget(data: Missions, pooling: float, rule: Rule) -> float:
    """Conservative B0 ensuring all missions can eventually be financed.

    Either the personal component or the team pool is individually sufficient at this upper bound;
    the tighter of those two sufficient bounds is used. Sequential reserve rules need an additional
    release-fraction allowance.
    """
    maximum_person = max(
        float(data.cost[indices].sum())
        for indices in data.individual_groups.values()
    )
    maximum_team_per_person = max(
        float(data.cost[indices].sum()) / count
        for indices, count in data.team_groups.values()
    )

    personal_bound = (
        maximum_person / (1 - pooling) if pooling < 1 else math.inf
    )
    pooled_bound = (
        maximum_team_per_person / pooling if pooling > 0 else math.inf
    )
    bound = min(personal_bound, pooled_bound)

    if pooling > 0 and rule.cap_multiple is not None:
        bound = max(bound, maximum_person / rule.cap_multiple)

    if rule.family == "sequential":
        bound /= 1 - rule.reserve_fraction

    return float(bound * CALIBRATION_UPPER_MARGIN + CALIBRATION_UPPER_OFFSET_KG_CO2E)


def calibrate(
    data: Missions,
    pooling: float,
    rule: Rule,
    person_effect: np.ndarray,
    mission_noise: np.ndarray,
    targets: tuple[float, ...],
    grid: int,
    refine: int,
    severity_threshold: float,
) -> dict[float, dict]:
    """Calibrate a shared annual B0 for all years, separately per target.

    A reduction target between achievable whole-mission allocations is met exactly *in expectation*
    by randomizing between those two allocations. Retain the closest deterministic solution and
    bracket-width diagnostics. The carbon response need not be monotone in B0.
    """
    top = upper_budget(data, pooling, rule)
    cache: dict[float, tuple[float, dict]] = {}

    def observe(budget: float) -> None:
        budget = round(max(0.0, float(budget)), CALIBRATION_BUDGET_DECIMALS)
        if budget in cache:
            return

        accepted = simulate(
            data, pooling, rule, budget, person_effect, mission_noise
        )
        reduction = 100 * (1 - data.cost[accepted].sum() / data.total)
        cache[budget] = (
            float(reduction),
            restriction_metrics(data, accepted, severity_threshold),
        )

    # Linear and geometric grids emphasize different budget scales.
    initial_budgets = np.unique(
        np.r_[
            np.linspace(0, top, grid),
            np.geomspace(
                max(
                    top / CALIBRATION_GEOMETRIC_RANGE_RATIO,
                    CALIBRATION_MIN_BUDGET_KG_CO2E,
                ),
                top,
                grid,
            ),
        ]
    )
    for budget in initial_budgets:
        observe(float(budget))

    observe(0.0)
    observe(top)

    def bracket(target: float) -> tuple[float, float]:
        """Find nearby sampled B0 values whose reductions span the target."""
        evaluations = sorted(cache.items())
        candidates = []

        for (b1, (r1, _)), (b2, (r2, _)) in zip(
            evaluations, evaluations[1:]
        ):
            if min(r1, r2) <= target <= max(r1, r2):
                candidates.append((abs(r1 - r2), b2 - b1, b1, b2))

        if not candidates:
            raise RuntimeError(
                "Target not bracketed; verify the upper-budget bound"
            )
        _, _, lower, upper = min(candidates)
        return lower, upper

    for target in targets:
        for _ in range(refine):
            lower, upper = bracket(target)
            midpoint = round(
                (lower + upper) / 2, CALIBRATION_BUDGET_DECIMALS
            )
            if midpoint in cache or midpoint in (lower, upper):
                break
            observe(midpoint)

    results = {}
    for target in targets:
        b1, b2 = bracket(target)
        r1, m1 = cache[b1]
        r2, m2 = cache[b2]

        if r1 > r2:
            b1, b2 = b2, b1
            r1, r2 = r2, r1
            m1, m2 = m2, m1

        width = r2 - r1
        weight = float(np.clip(
            (r2 - target) / width if width > NUMERICAL_TOLERANCE else 1.0,
            0.0, 1.0,
        ))

        expected_metrics = {
            name: (
                None if m1[name] is None or m2[name] is None
                else float(weight * m1[name] + (1 - weight) * m2[name])
            )
            for name in METRICS
        }

        closest_lower = abs(r1 - target) <= abs(r2 - target)
        closest_reduction = r1 if closest_lower else r2
        closest_budget = b1 if closest_lower else b2
        closest_metrics = m1 if closest_lower else m2
        expected_reduction = weight * r1 + (1 - weight) * r2

        results[float(target)] = {
            "b0_kg_co2e": float(weight * b1 + (1 - weight) * b2),
            "achieved_reduction_percent": float(expected_reduction),
            "target_gap_percentage_points": float(expected_reduction - target),
            "metrics": expected_metrics,
            "interpolation": {
                "method": "lottery_between_two_whole_mission_allocations",
                "lower_reduction_percent": r1,
                "upper_reduction_percent": r2,
                "lower_budget_kg_co2e": b1,
                "upper_budget_kg_co2e": b2,
                "probability_lower_reduction": weight,
                "bracket_width_percentage_points": float(width),
                "deterministic_closest_reduction_percent": float(closest_reduction),
                "deterministic_closest_budget_kg_co2e": float(closest_budget),
                "deterministic_closest_abs_gap_percentage_points": float(
                    abs(closest_reduction - target)
                ),
                "deterministic_closest_metrics": closest_metrics,
            },
        }

    return results


# ==================================================================================================
# Reports and diagnostics
# ==================================================================================================

def describe(values: list[float | None]) -> dict:
    """Describe variability across hypothetical rules, not a confidence band."""
    valid = np.asarray([x for x in values if x is not None], dtype=float)
    if len(valid) == 0:
        return {"n": 0, "median": None, "p05": None, "p95": None}
    return {
        "n": len(valid),
        "median": float(np.median(valid)),
        "p05": float(np.percentile(valid, 5)),
        "p95": float(np.percentile(valid, 95)),
    }


def lambda_key(pooling: float) -> str:
    """Stable, human-readable JSON key for a pooling fraction."""
    return format(pooling, ".10g")


def create_report(
    target: float,
    records: list[dict],
    data: Missions,
    args: argparse.Namespace,
) -> dict:
    """Combine all pooling levels in one JSON for a carbon target."""
    by_lambda = {}
    zero = lambda_key(0.0)
    has_zero = zero in {lambda_key(x) for x in args.lambdas}

    for pooling in args.lambdas:
        key = lambda_key(pooling)
        evaluations = [record["by_lambda"][key] for record in records]
        widths = [
            e["interpolation"]["bracket_width_percentage_points"]
            for e in evaluations
        ]

        entry = {
            "budget_b0_kg_co2e": describe(
                [e["b0_kg_co2e"] for e in evaluations]
            ),
            "metrics": {
                name: describe([e["metrics"][name] for e in evaluations])
                for name in METRICS
            },
            "calibration": {
                "bracket_width_percentage_points": describe(widths),
                "fraction_wider_than_warning": float(
                    np.mean(np.asarray(widths) > args.max_bracket_pp)
                ),
                "closest_deterministic_absolute_gap_percentage_points": describe(
                    [
                        e["interpolation"][
                            "deterministic_closest_abs_gap_percentage_points"
                        ]
                        for e in evaluations
                    ]
                ),
            },
        }

        if has_zero:
            entry["paired_difference_from_lambda_0"] = {
                name: describe([
                    record["by_lambda"][key]["metrics"][name]
                    - record["by_lambda"][zero]["metrics"][name]
                    for record in records
                    if record["by_lambda"][key]["metrics"][name] is not None
                    and record["by_lambda"][zero]["metrics"][name] is not None
                ])
                for name in METRICS
            }

        by_lambda[key] = entry

    return {
        "schema_version": SCHEMA_VERSION,
        "software_version": VERSION,
        "target_reduction_percent": target,
        "pooling_fractions": list(args.lambdas),
        "input": data.metadata,
        "experiment": {
            "draws": args.draws,
            "seed": args.seed,
            "sampling": args.sampling,
            "families": list(FAMILIES),
            "calibration_method": "whole_mission_allocation_lottery",
            "b0_constant_over_observed_years": True,
            "b0_calibrated_separately_per_rule_pooling_target": True,
            "individual_first_team_second_financing": True,
            "grid": args.grid,
            "refine": args.refine,
            "severity_threshold": args.severity_threshold,
            "max_bracket_width_warning_pp": args.max_bracket_pp,
            "interpretation": "sensitivity_to_hypothetical_governance_rules",
        },
        "metric_definitions": {
            "refused_missions_percent": "Refused / all eligible missions",
            "affected_traveler_years_percent": (
                "Traveler-years with >=1 refusal / active traveler-years"
            ),
            "severely_affected_traveler_years_percent": (
                f"Traveler-years with refused/requested >= {args.severity_threshold:g} "
                "/ active traveler-years"
            ),
            "repeatedly_affected_travelers_percent": (
                "Travelers refused in >=2 years / travelers active in >=2 years"
            ),
        },
        "summary_by_lambda": by_lambda,
        "draws": records if args.keep_draws else None,
    }


def print_progress(
    completed: int,
    total: int,
    width: int = PROGRESS_BAR_WIDTH,
) -> None:
    """Update a dependency-free progress bar counting 1, 2, ..., total."""
    filled = round(width * completed / total)
    bar = "#" * filled + "-" * (width - filled)
    print(f"\r[{bar}] {completed}/{total}", end="\n" if completed == total else "", flush=True)


# ==================================================================================================
# Experiment execution
# ==================================================================================================

def run(args: argparse.Namespace) -> list[Path]:
    """Run paired pooling-level experiments and write one JSON per target."""
    if args.draws < 1 or args.grid < 5 or args.refine < 0:
        raise ValueError("draws>=1, grid>=5, refine>=0 required")
    if not 0 < args.severity_threshold <= 1:
        raise ValueError("severity threshold must be in (0, 1]")
    if not 0 <= args.max_bracket_pp <= 100:
        raise ValueError("max bracket width must be between 0 and 100 pp")
    if not args.targets or not all(0 < x < 100 for x in args.targets):
        raise ValueError("carbon targets must lie strictly between 0 and 100")
    if not args.lambdas or not all(0 <= x <= 1 for x in args.lambdas):
        raise ValueError("pooling fractions must lie in [0, 1]")
    if len(set(args.lambdas)) != len(args.lambdas):
        raise ValueError("pooling fractions must be unique")
    if len(set(args.targets)) != len(args.targets):
        raise ValueError("carbon targets must be unique")

    data = load_missions(args.input, args.exclude_mission_types, args.headcount)
    rng = np.random.default_rng(args.seed)
    rules = sample_rules(args.draws, rng, args.sampling)

    records = {
        target: [
            {"draw": i, "rule": asdict(rule), "by_lambda": {}}
            for i, rule in enumerate(rules)
        ]
        for target in args.targets
    }

    total_operations = len(rules) * len(args.lambdas)
    progress_steps = len(args.targets) * len(args.lambdas)
    last_step = 0

    print(
        f"{data.metadata['missions_included']} missions; "
        f"{data.people} travelers; "
        f"{data.total / 1000:.1f} t CO2e"
    )
    print(
        f"{len(args.targets)} targets x {len(args.lambdas)} pooling fractions "
        f"= {progress_steps} configurations, {args.draws} rules each"
    )
    print_progress(0, progress_steps)

    # Each rule uses the SAME random effects at ALL pooling levels. Calibration
    # shares initial budget evaluations across all requested carbon targets.
    completed_operations = 0

    for i, rule in enumerate(rules):
        effects = rng.standard_normal(data.people)
        noise = rng.standard_normal(len(data.cost))

        for pooling in args.lambdas:
            calibrated = calibrate(
                data=data,
                pooling=pooling,
                rule=rule,
                person_effect=effects,
                mission_noise=noise,
                targets=args.targets,
                grid=args.grid,
                refine=args.refine,
                severity_threshold=args.severity_threshold,
            )
            key = lambda_key(pooling)

            for target in args.targets:
                records[target][i]["by_lambda"][key] = calibrated[target]

            completed_operations += 1
            # The bar tracks total rule-pooling work in 44 equal fractions;
            # the four targets share the same calibration budget search.
            new_step = completed_operations * progress_steps // total_operations
            if new_step > last_step:
                for step in range(last_step + 1, new_step + 1):
                    print_progress(step, progress_steps)
                last_step = new_step

    args.output_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    for target in args.targets:
        target_label = format(target, "g").replace(".", "p")
        path = args.output_dir / f"budget_allocation_{target_label}pct.json"
        report = create_report(target, records[target], data, args)
        path.write_text(
            json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
        )
        paths.append(path)
        print(f"Wrote {path}")

    return paths


# ==================================================================================================
# Command-line interface
# ==================================================================================================

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input", type=Path, required=True,
        help="Input workbook (e.g. carbon_analysis.xlsx), sheet 'missions'",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument(
        "--exclude-mission-types", nargs="+", default=[], metavar="TYPE",
        help="Mission types to exclude (case-insensitive); missions without a team are always excluded",
    )
    parser.add_argument(
        "--targets", type=float, nargs="+", default=list(DEFAULT_TARGETS)
    )
    parser.add_argument(
        "--lambdas", type=float, nargs="+", default=list(DEFAULT_LAMBDAS),
        help="Fraction of the team's nominal budget that is pooled",
    )
    parser.add_argument("--draws", type=int, default=DEFAULT_DRAWS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--sampling", choices=("latin", "random"), default="latin"
    )
    parser.add_argument(
        "--headcount", choices=("annual-active", "pooled"),
        default="annual-active",
    )
    parser.add_argument("--grid", type=int, default=DEFAULT_GRID)
    parser.add_argument("--refine", type=int, default=DEFAULT_REFINE)
    parser.add_argument(
        "--max-bracket-pp", type=float, default=DEFAULT_MAX_BRACKET_PP
    )
    parser.add_argument(
        "--severity-threshold", type=float,
        default=DEFAULT_SEVERITY_THRESHOLD,
    )
    parser.add_argument(
        "--no-draws", action="store_false", dest="keep_draws",
        help="Keep only aggregate reports (omit per-rule results)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    run(parse_args(argv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
