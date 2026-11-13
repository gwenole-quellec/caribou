# Carbon Allocation for Research trIps: Budget Optimization and Utilization

<p align="center"><img src="figures/logo_caribou.png" alt="CARIBOU logo" width="300"></p>

CARIBOU is a Python workflow for exploring how individual and pooled carbon budgets affect research travel. It replays historical mission requests under hypothetical prioritization behaviors and compares mission preservation and the distribution of restrictions at common carbon-reduction targets. The purpose is **sensitivity analysis and decision support**, not to prescribe an optimal policy.

## Requirements

Python 3.10+ with:

```bash
python -m pip install numpy pandas scipy numba matplotlib openpyxl
```

## Input workbook

The input workbook, e.g., `carbon_analysis.xlsx`, must contain a worksheet named `missions`, with **one row per complete research mission**. Each mission must have a unique identifier and may comprise multiple travel segments and transportation modes. Its carbon footprint must represent the total estimated emissions of all segments.

The following columns are required:

| Column | Description |
|---|---|
| `mission_id` | Unique identifier for each mission, across all years and travelers. |
| `year` | Calendar year of the mission (e.g., `2025`). Used to define annual carbon budgets. |
| `person_id` | Stable identifier for the traveler. The same individual must retain the same identifier across years to enable longitudinal analyses. |
| `accounting_team` | Administrative or accounting category assigned to the mission. Used to exclude specific categories (e.g., `ADMIN`) through the `--exclude` option. |
| `original_team` | Research team to which the traveler belongs. Used to define the groups within which carbon allowances are pooled. |
| `start_date` | Mission departure date, stored as an Excel date or a parseable date value. Used to order missions in chronological allocation scenarios. |
| `emissions_kg_co2e` | Total estimated greenhouse gas emissions of the complete mission, expressed in kg CO₂e. Must be a non-negative numerical value. |

Multiple missions by the same traveler are represented by separate rows, sharing the same `person_id` but having distinct `mission_id` values. All travel segments belonging to a mission must be aggregated beforehand, and emissions must already be calculated, e.g., using the `carbon_footprint.py` script described below; The simulation does not perform geocoding or estimate transport emissions.

Missions assigned to the `ADMIN` accounting category are excluded by default in the example commands above. Pooled budgets use `original_team`; team sizes are based on travelers with eligible requests rather than complete personnel rosters.

**The input workbook is not included in the public repository** because it contains confidential institutional travel records.

## Run the workflow

From the repository root:

```bash
# Dataset summary and mission-emissions histogram
python describe_missions.py --input carbon_analysis.xlsx --exclude ADMIN

# Full simulation: 10,000 sampled rules, four carbon-reduction targets
python explore_budget_allocation.py \
    --input carbon_analysis.xlsx --exclude ADMIN \
    --targets 5 10 15 20 --draws 10000 --seed 42 \
    --output-dir results

# Results figures
python fig_missions.py     --results-dir results
python fig_restrictions.py --results-dir results
python fig_governance.py   --results-dir results
python fig_tradeoff.py     --results-dir results

# Four-outcome summary table at 50% pooling
python table_outcomes.py --results-dir results --lambda 0.5
```

For a shorter technical test, reduce `--draws` (e.g., `--draws 100`) and use a separate `--output-dir`. Run `python <script>.py --help` for additional options. **Do not use `--no-draws`** when producing the JSON files for figures and outcome tables: they require per-rule records.

## Generated outputs

| Script | Output |
| --- | --- |
| `describe_missions.py` | `tables/table_dataset.{tex,md}`; `figures/fig_emissions_histogram.{pdf,png}` |
| `explore_budget_allocation.py` | `results/budget_allocation_{5,10,15,20}pct.json` |
| `fig_missions.py` | `figures/fig_missions.{pdf,png}` |
| `fig_restrictions.py` | `figures/fig_restrictions.{pdf,png}` |
| `fig_governance.py` | `figures/fig_governance.{pdf,png}` |
| `fig_tradeoff.py` | `figures/fig_tradeoff.{pdf,png}` |
| `table_outcomes.py` | `tables/table_outcomes.{tex,md}` |

The dataset table summarizes missions, distinct travelers, teams, and emissions by year and overall; its histogram shows emissions per mission. The outcomes table reports all four restriction indicators at the selected pooling fraction, with median **within-rule paired changes** relative to no pooling. Its default is `--lambda 0.5`.

The `.tex` tables are ready for `\input{tables/table_dataset.tex}` and `\input{tables/table_outcomes.tex}`; the manuscript must load `booktabs`. PDF figures can be included with `\includegraphics`.

## Simulation settings and interpretation

- **Pooling:** `λ = 0, 0.1, …, 1`, from individual to fully pooled team budgets.
- **Targets:** 5%, 10%, 15%, and 20% reductions relative to emissions from all eligible requests.
- **Prioritization:** five equally sampled hypothetical families (`cost`, `distributive`, `longitudinal`, `random`, `sequential`); default 10,000 rules, seed 42.
- **Calibration:** targets are attained *in expectation* when necessary by mixing two complete, indivisible-mission allocations.
- **Reporting:** medians and ranges describe sensitivity across sampled rules, **not** confidence intervals or probabilities of real-world behavior. Differences relative to `λ = 0` are paired within each sampled rule; they are not isolated causal effects of pooling.

## Estimate travel emissions from Excel

The standalone `carbon_footprint.py` script estimates CO₂e emissions for individual travel segments using geographic distances and transport-specific emission factors adapted from GES 1point5 (Mariette et al., 2022; https://doi.org/10.1088/2634-4505/ac84a4).

```bash
python carbon_footprint.py travels.xlsx \
    --origin-city-column "Ville départ" \
    --origin-country-column "Pays départ" \
    --destination-city-column "Ville arrivée" \
    --destination-country-column "Pays arrivée" \
    --mode-column "Mode" \
    --plane-values avion plane flight \
    --train-values train rail \
    --car-values voiture car \
    --taxi-values taxi \
    --bus-values bus autocar "Autocar intercité" coach
```

The first worksheet is used by default; `--sheet` selects another worksheet. Column names and transport-mode labels are configurable.

The script generates:

- `travels_carbon.xlsx`: original workbook with an additional `carbon footprint` column (kg CO₂e).
- `travels_carbon_errors.csv`: unresolved locations, missing data, and unrecognized transport modes.
- `travels_geocode_cache.json`: cached geographic coordinates for subsequent runs.

Each row is processed independently, and emissions are estimated for a single one-way travel segment between the specified locations. The script does not interpret additional columns indicating round trips, passenger counts, or other travel arrangements. Users must apply any necessary adjustments (e.g., doubling emissions for a round trip) before aggregating emissions into complete missions for the `carbon_analysis.xlsx` input workbook. Note, however, that taxi emissions systematically include a factor of two to account for an assumed empty return journey.

Geocoding uses OpenStreetMap's Nominatim service and requires an internet connection for uncached locations. Use `--offline` to rely exclusively on cached coordinates.


Source data remain private. The code is released under the repository's BSD 3-Clause license.