# Carbon Allocation for Research trIps: Budget Optimization and Utilization

<p align="center"><img src="figures/logo_caribou.png" alt="CARIBOU logo" width="300"></p>

CARIBOU is a Python workflow for exploring how individual and pooled carbon budgets affect research travel. It replays historical mission requests under hypothetical prioritization behaviors and compares mission preservation and the distribution of restrictions at common carbon-reduction targets. The purpose is **sensitivity analysis and decision support**, not to prescribe an optimal policy.

## Requirements and input

Python 3.10+ with:

```bash
python -m pip install numpy pandas scipy numba matplotlib openpyxl
```

The private input workbook, `carbon_analysis.xlsx`, must contain a `missions` sheet with the columns:

```text
mission_id, year, person_id, accounting_team, original_team, start_date, emissions_kg_co2e
```

Missions assigned to the `ADMIN` accounting category are excluded by default. Pooled budgets use `original_team`; team sizes are based on travelers with eligible requests rather than complete personnel rosters. **The input workbook is not included in the public repository.**

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

Source data remain private. The code is released under the repository's BSD 3-Clause license.
