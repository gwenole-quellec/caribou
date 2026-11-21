# Carbon Allocation for Research trIps: Budget Optimization and Utilization

<p align="center"><img src="figures/logo_caribou.png" alt="CARIBOU logo" width="300"></p>

CARIBOU is a Python workflow for exploring how individual and pooled carbon budgets affect research travel. It replays historical mission requests under hypothetical prioritization behaviors and compares mission preservation and the distribution of restrictions at common carbon-reduction targets. The purpose is **sensitivity analysis and decision support**, not to prescribe an optimal policy.

## Installation

Requires Python 3.10+. From the repository root:

```bash
pip install -r requirements-ui.txt
streamlit run caribou_app.py
```

For command-line use only, install `requirements.txt` instead.

## Prepare the data

The simulator expects an Excel worksheet named `missions`, with **one row per complete mission** and these columns:

| Column | Expected value |
|---|---|
| `mission_id` | Unique mission identifier across all travelers and years. |
| `year` | Departure year, matching `start_date`. |
| `person_id` | Traveler identifier, stable across years. |
| `team` | Research team; rows without a team are ignored. |
| `mission_type` | Mission purpose, e.g., `research` or `teaching`. |
| `start_date` | Departure date, as an Excel date or parseable text. |
| `emissions_kg_co2e` | Total emissions of all mission segments, in kg CO₂e; finite and nonnegative. |

### Simple mode: emissions already available

In the Streamlit app, upload the consolidated `.xlsx`, select its worksheet and map the columns. If `year` is unmapped, it is derived from `start_date`. Select the source emissions unit and the interpretation of ambiguous text dates.

If several rows represent segments of the same mission, enable **Group segments by mission_id**: emissions are summed and the earliest date is retained; traveler, team, mission type and year must match. Otherwise, mission IDs must be unique. Rows without a team are ignored, with a warning.

Resolve validation errors, then download `caribou_missions.xlsx` and use it as the simulation input. The **Visualizations** tab explores the prepared data. This mode does not estimate emissions.

### Full mode: estimate emissions from travel segments

If emissions are unavailable, first run `carbon_footprint.py` on a workbook containing origin/destination cities and countries and transport modes. It estimates segment emissions from geographic distances and transport-specific factors adapted from GES 1point5 ([Mariette et al., 2022](https://doi.org/10.1088/2634-4505/ac84a4)). **This step will also be integrated into the UI; it currently runs from the command line.**

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

Adapt column names and mode labels to your workbook. The first worksheet is used unless `--sheet` is specified. Outputs are:

- `travels_carbon.xlsx`: source data plus a `carbon footprint` column in kg CO₂e.
- `travels_carbon_errors.csv`: unresolved locations, missing data and unknown modes.
- `travels_geocode_cache.json`: cached coordinates.

Each row represents **one one-way segment**. Include return segments or adjust emissions before aggregation; round-trip and passenger-count columns are not interpreted. Taxi estimates already include an empty-return factor of two, separate from any passenger return journey.

Review the error report and resolve missing estimates, then import the enriched workbook into the app, map `carbon footprint` to `emissions_kg_co2e`, and follow simple mode above. Retain the mission identifiers and metadata required for mapping.

Uncached locations require internet access to OpenStreetMap Nominatim. Keep the geocoding cache and factor settings for reproducibility; `--cache PATH` selects a cache and `--offline` uses cached locations only.

**The study workbook is not included in the public repository** because it contains confidential institutional travel records.

## Run the workflow

From the repository root:

```bash
# Dataset summary and mission-emissions histogram
python describe_missions.py \
    --input carbon_footprint.xlsx \
    --exclude-mission-types research_administration

# Full simulation: 10,000 sampled rules, four carbon-reduction targets
python explore_budget_allocation.py \
    --input carbon_footprint.xlsx \
    --exclude-mission-types research_administration \
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

These example commands exclude `research_administration` missions to reproduce the corresponding research-travel analysis. To include **all mission types**, omit `--exclude-mission-types` from both commands (missions without a team are still ignored).

For a shorter technical test, reduce `--draws` (e.g., `--draws 100`) and use a separate `--output-dir`. Run `python <script>.py --help` for additional options.

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

The dataset table summarizes eligible missions, distinct travelers, teams, and emissions by year and overall; its histogram shows emissions per eligible mission. The outcomes table reports all four restriction indicators at the selected pooling fraction, with median **within-rule paired changes** relative to no pooling. Its default is `--lambda 0.5`.

## Simulation settings and interpretation

- **Pooling:** `λ = 0, 0.1, …, 1`, from individual to fully pooled team budgets.
- **Targets:** 5%, 10%, 15%, and 20% reductions relative to emissions from all eligible requests.
- **Prioritization:** five equally sampled hypothetical families (`cost`, `distributive`, `longitudinal`, `random`, `sequential`); the example workflow uses 10,000 rules with seed 42.
- **Calibration:** targets are attained *in expectation* when necessary by mixing two complete, indivisible-mission allocations.
- **Reporting:** medians and ranges describe sensitivity across sampled rules, **not** confidence intervals or probabilities of real-world behavior. Differences relative to `λ = 0` are paired within each sampled rule; they are not isolated causal effects of pooling.

## License

The code is released under the repository's BSD 3-Clause license.
