# CARIBOU

<p align="center"><img src="logo_caribou.png" alt="CARIBOU logo" width="300"></p>

**Explore carbon budgets for research travel.**

CARIBOU turns travel records into a carbon footprint you can explore, then compares how individual and shared team budgets would affect those missions. Prepare your data in a browser, inspect the charts, and test different carbon-reduction targets.

*Carbon Allocation for Research trIps: Budget Optimization and Utilization*

## Get started

Requires Python 3.10+. From the repository root:

```bash
pip install -r requirements-ui.txt
streamlit run caribou.py
```

## From Excel to insights

Choose the preparation mode that fits your data:

| Tab | Start with | What happens |
|---|---|---|
| **Simple preparation** | Travel records with emissions already calculated | Map your columns, validate and export. |
| **Advanced preparation** | Travel records with cities, countries and transportation modes | Map your columns; CARIBOU estimates emissions and prepares complete missions. |
| **Visualization** | The result of either mode | Explore emissions over time, by team and mission type, and across missions. |

Both preparation modes export **`carbon_footprint.xlsx`**, ready for simulation. No download and reimport is needed to view the charts.

If your workbook has several segments per mission, combine them using their shared mission ID. CARIBOU adds their emissions and keeps the earliest departure date. This option is enabled by default in advanced mode.

In advanced mode, choose a round-trip column or apply one setting to all rows. **One-way is the default**; round trips double the estimate. Leave this off when return segments are already separate rows. Taxi estimates additionally include an assumed empty vehicle return.

Advanced mode supports plane, train, car, taxi and intercity coach travel, with editable French and English labels. Estimates use distance-based factors adapted from [GES 1point5](https://doi.org/10.1088/2634-4505/ac84a4). Online geocoding sends city/country pairs to OpenStreetMap Nominatim; save the downloadable cache to reuse coordinates or work offline. Car and taxi estimates are per vehicle, without automatic passenger sharing.

## What your data needs

The app maps your column names to this simulation format: a worksheet named **`missions`**, with one row per complete mission.

| Column | Content |
|---|---|
| `mission_id` | Unique mission ID across travelers and years. |
| `year` | Departure year; the app can derive it from the date. |
| `person_id` | Traveler ID, stable across years. |
| `team` | Research team. |
| `mission_type` | Purpose; may be blank. Multiple purposes are joined with commas. |
| `start_date` | Departure date. |
| `emissions_kg_co2e` | Total mission emissions in kg CO₂e, finite and nonnegative. |

Store IDs as text in Excel to preserve leading zeros. When combining segments, traveler, team and year must match. Advanced mode also needs origin/destination cities and countries, plus a transportation mode; emissions are calculated for you.

Simple preparation keeps missions without a team in the export and charts. Advanced preparation and simulations ignore them. Team sizes in simulations count eligible travelers, not complete personnel rosters.

The confidential study workbook is not distributed with the code.

## Run simulations

Data preparation and charts run in the browser; simulations currently run from the command line. For command-line use only, install `requirements.txt`.

```bash
# Summarize the dataset
python -m caribou_data.describe_missions --input carbon_footprint.xlsx

# Compare carbon budgets at four reduction targets
python -m caribou_simulation.explore_budget_allocation \
    --input carbon_footprint.xlsx \
    --targets 5 10 15 20 --draws 10000 --seed 42

# Generate figures and a summary table
python -m caribou_simulation.fig_missions
python -m caribou_simulation.fig_restrictions
python -m caribou_simulation.fig_governance
python -m caribou_simulation.fig_tradeoff
python -m caribou_simulation.table_outcomes --lambda 0.5
```

Figures and tables go to **`artifacts/`**; simulation reports go to **`artifacts/results/`**. Output paths are configurable. For a quick trial, use `--draws 100`.

To exclude a purpose, add `--exclude-mission-types research_administration` to both the dataset summary and simulation commands. A match on any comma-separated purpose excludes the whole mission. Use `--help` with any command for more options.

## Read the results

CARIBOU explores **sensitivity to hypothetical allocation rules**, rather than prescribing a policy. Pooling ranges from individual budgets (`λ = 0`) to fully shared team budgets (`λ = 1`), across five prioritization families: cost, distributive, longitudinal, random and sequential.

Reduction targets are matched in expectation, mixing complete-mission allocations when needed. Reported medians and ranges describe variation across sampled rules, not confidence intervals. Comparisons with no pooling are paired within each rule; they do not establish causal effects.

## Project layout

- `caribou.py` — Streamlit entry point.
- `caribou_data/` — data preparation, emissions and dataset description.
- `caribou_ui/` — forms and visualizations.
- `caribou_simulation/` — simulations and results reporting.
- `artifacts/` — generated outputs.

The emissions engine is an importable module, `caribou_data.carbon_footprint`, without a CLI.

## License

[BSD 3-Clause](LICENSE).
