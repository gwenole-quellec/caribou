# CARIBOU

**Carbon Allocation for Research trIps: Budget Optimization and Utilization**

<p align="center"><img src="figures/logo_caribou.png" alt="CARIBOU logo" width="300"></p>

CARIBOU explores how to allocate an annual carbon budget for research travel. Using historical mission requests, it compares **individual budgets, partially pooled budgets, and fully pooled team budgets** under a range of hypothetical governance rules and carbon-reduction targets.

The aim is **decision support through sensitivity analysis**, not the identification of a universally optimal policy. The simulations investigate how many missions are refused and how restrictions are distributed among travelers when the expected carbon reduction is held constant.

## 1. Files and dependencies

The core workflow consists of one simulation script and four independent visualization scripts:

| File | Purpose | Outputs |
| --- | --- | --- |
| `explore_budget_allocation.py` | Sample governance rules, calibrate carbon budgets, and evaluate allocations | `results/budget_allocation_5pct.json`, `_10pct.json`, `_15pct.json`, `_20pct.json` |
| `fig_missions.py` | How many research trips can budget pooling preserve? | `figures/fig_missions.png`, `.pdf` |
| `fig_restrictions.py` | Who bears the travel restrictions? | `figures/fig_restrictions.png`, `.pdf` |
| `fig_governance.py` | Does governance make pooling fairer? | `figures/fig_governance.png`, `.pdf` |
| `fig_tradeoff.py` | How much pooling is worth it? | `figures/fig_tradeoff.png`, `.pdf` |

Figure files always use **the same stem as their Python script**. No figure numbering is embedded in filenames. The four visualization scripts generate only PNG and PDF files; they do not create Markdown tables.

**Requirements:** Python 3.10+ and the following packages:

```bash
python -m pip install numpy pandas scipy numba matplotlib openpyxl
```

Numba accelerates the mission-selection calculations. `openpyxl` is used by pandas to read the Excel workbook.

## 2. Reproduce the simulations

The input workbook must have a sheet named `missions`, with at least these columns:

```text
mission_id, year, person_id, accounting_team, original_team,
start_date, emissions_kg_co2e
```

The `--exclude ADMIN` option excludes missions classified under the `ADMIN` accounting team **before** calculating budgets and the emissions baseline. The team used for pooled allocation is `original_team`. Team headcounts are estimated from travelers observed in the data, not full staffing rosters.

### Full exploration (10,000 rules)

```bash
python explore_budget_allocation.py \
    --input carbon_analysis.xlsx \
    --exclude ADMIN \
    --targets 5 10 15 20 \
    --draws 10000 \
    --seed 42 \
    --output-dir results
```

By default, CARIBOU evaluates **11 pooling fractions**, from `0` to `1` in increments of `0.1`. This gives **4 reduction targets × 11 pooling fractions = 44 target–pooling configurations for every sampled rule**, or 440,000 rule–target–pooling results at 10,000 sampled rules. Budget calibration calculations are shared across reduction targets where possible.

The five governance families are sampled in balanced numbers (2,000 rules per family when `--draws 10000`), with Latin-hypercube sampling of their parameters. All pooling fractions are evaluated using the same sampled rule and underlying random mission/traveler effects. The progress display reports completion over the 44 target–pooling configurations.

### Short validation run

```bash
python explore_budget_allocation.py \
    --input carbon_analysis.xlsx \
    --draws 100 \
    --seed 42 \
    --output-dir results
```

For a faster *technical smoke test*, calibration resolution can be reduced:

```bash
python explore_budget_allocation.py \
    --input carbon_analysis.xlsx \
    --draws 10 \
    --grid 12 \
    --refine 4 \
    --output-dir smoke
```

The reduced calibration grid is intended only to check that the workflow runs, not to produce publication results.

Other useful options are `--sampling {latin,random}`, `--headcount {annual-active,pooled}`, `--lambdas`, `--severity-threshold`, `--grid`, `--refine`, and `--max-bracket-pp`. See:

```bash
python explore_budget_allocation.py --help
```

**Keep the default per-rule records**: the figure scripts require `draws` in each JSON report. Do **not** use `--no-draws` when generating results for the four figures.

## 3. Generate the four figures

After the four JSON reports have been produced:

```bash
python fig_missions.py     --results-dir results
python fig_restrictions.py --results-dir results
python fig_governance.py   --results-dir results
python fig_tradeoff.py     --results-dir results
```

The output directory defaults to `figures/` and can be changed consistently for any script:

```bash
python fig_missions.py --results-dir results --output-dir figures
```

Expected structure:

```text
CARIBOU/
├── explore_budget_allocation.py
├── fig_missions.py
├── fig_restrictions.py
├── fig_governance.py
├── fig_tradeoff.py
├── carbon_analysis.xlsx           # Local input; not for public distribution
├── results/
│   ├── budget_allocation_5pct.json
│   ├── budget_allocation_10pct.json
│   ├── budget_allocation_15pct.json
│   └── budget_allocation_20pct.json
└── figures/
    ├── fig_missions.png
    ├── fig_missions.pdf
    ├── fig_restrictions.png
    ├── fig_restrictions.pdf
    ├── fig_governance.png
    ├── fig_governance.pdf
    ├── fig_tradeoff.png
    └── fig_tradeoff.pdf
```

Each plot detects the number of sampled rules automatically. The figure scripts require all four reduction targets (5%, 10%, 15%, 20%) and the pooling fractions they display; `fig_tradeoff.py` also requires `λ = 0` as its comparison baseline. The default 11-point pooling grid satisfies these requirements.

### What each figure shows

**`fig_missions.py` — How many research trips can budget pooling preserve?**  One chart combines the four carbon-reduction targets. The vertical axis shows **refused missions per 100 requested missions**. Curves are medians across rules; translucent bands show the **25th–75th percentiles**. Vertical guides mark pooling fractions **0%, 20%, 50%, and 100%**, with markers at 20% and 50%. Lower is better.

**`fig_restrictions.py` — Who bears the travel restrictions?**  A **4 × 4 grid of pictogram villages** compares four carbon targets (rows) with **0%, 20%, 50%, and 100% pooling** (columns). Each village depicts 100 *active traveler-year equivalents* categorized as: no refused missions (gray); some refused missions, but less than half of requests lost (yellow); and **at least half of requested missions refused** (red). Exact percentages are printed below each village. Faces are rounded illustrations, **not 100 distinct observed people**. The displayed moderate share is the median affected share **minus** the median severe share; this is not necessarily the median moderate share across rules.

**`fig_governance.py` — Does governance make pooling fairer?**  Four panels compare the **absolute median percentage of severely affected traveler-years** within five governance families. Each row has points for **20%, 50%, and 100% pooling**. Points are slightly offset vertically **for readability only**: the y-axis is categorical, and **only horizontal position encodes the restriction rate**. Left is better. The friendly family labels are simplified descriptions of the sampled rule families, not fixed real-world operating policies.

**`fig_tradeoff.py` — How much pooling is worth it?**  A single graph shows all four carbon targets in the plane of **additional missions preserved** (horizontal) versus **additional severely affected traveler-years** (vertical), each measured **relative to `λ = 0` within the same sampled rule**. More rightward and less upward is preferable. Colored paths join **coordinate-wise medians of paired differences**, with symbols marking 20%, 50%, and 100% pooling. A point on the path **need not correspond to any single realizable allocation**; the joining segments are visual aids, not interpolated policies.

The same four target colors are used throughout: blue (5%), teal (10%), orange (15%), and red (20%). Percentages on different axes may have **different denominators**: requested missions versus active traveler-years.

## 4. Allocation model

For annual nominal budget `B0`, traveler `i`, team `e`, year `t`, and pooled fraction `λ`, the initial accounts are:

$$
I_{it} = (1-\lambda) B_0,
\qquad
R_{et} = \lambda\, n_{et} B_0.
$$

Here `n[e,t]` is an estimated team headcount based on eligible observed travelers (default `--headcount annual-active`). A mission is **indivisible**: it is either accepted in full or refused. The personal account pays first, and the team reserve pays any shortfall permitted by the governance rule.

- **`λ = 0`**: strictly individual budgets.
- **`0 < λ < 1`**: hybrid individual and team budgets.
- **`λ = 1`**: fully pooled team budgets.

There is **one continuous allocation model** across the full pooling range.

Five sampled governance families determine the order in which missions are considered:

| Family in JSON | Decision-oriented label | Mechanism explored |
| --- | --- | --- |
| `sequential` | First come, first served | Chronological processing with progressive budget release; mission start date proxies request order |
| `cost` | Lowest-carbon trips first | Carbon-cost priority score with a sampled coefficient and random noise; the coefficient can also favor high-cost trips |
| `distributive` | Shared fairly | Dynamic consideration of prior within-year individual spending, optionally with caps |
| `longitudinal` | Compensate past restrictions | Priority influenced by refusals in preceding years and optionally spending caps |
| `random` | Random allocation | Randomized mission/traveler priority, potentially including person-specific effects |

Parameter ranges and sampling distributions are documented as named constants near the top of `explore_budget_allocation.py`. The five families are **equally represented by design**; their simulated frequencies do not estimate real-life governance frequencies. Comparing families is descriptive, not an isolated causal test of any individual fairness mechanism.

## 5. Calibration and outcome metrics

`B0` is **constant across the observed years**, but calibrated **separately for each decision rule, pooling fraction, and carbon-reduction target**. Whole-mission allocations make the carbon reduction discrete; the simulator therefore reaches the prescribed target **in expectation**, using a lottery between two feasible complete allocations. It does not divide missions into fractions or guarantee that a particular realized allocation exactly achieves the target.

The four exported outcome metrics, expressed as percentages, are:

| JSON metric | Definition |
| --- | --- |
| `refused_missions_percent` | Refused eligible missions / all eligible requested missions |
| `affected_traveler_years_percent` | Active traveler-years with ≥ 1 refusal / all active traveler-years |
| `severely_affected_traveler_years_percent` | Active traveler-years losing ≥ 50% of requested missions / all active traveler-years (default threshold) |
| `repeatedly_affected_travelers_percent` | Travelers refused in ≥ 2 years / travelers with eligible requests in ≥ 2 years |

Each `budget_allocation_*pct.json` report (schema `1.0`) contains `input` metadata, `experiment` parameters, `pooling_fractions`, `metric_definitions`, `summary_by_lambda`, and `draws`. The per-rule `draws` records contain `rule` and `by_lambda` results. Lambda keys are strings: `"0"`, `"0.1"`, ..., `"1"`.

Inspect the exported calibration diagnostics before interpreting results, particularly:

- `interpolation.bracket_width_percentage_points`;
- `interpolation.deterministic_closest_abs_gap_percentage_points`;
- the proportion of calibrations with brackets exceeding `--max-bracket-pp` in `summary_by_lambda`.

Large brackets mean that the two deterministic allocations used in the calibration lottery are relatively far apart in achieved emissions reduction.

## 6. Interpretation and limitations

1. **Sensitivity, not probability:** medians and percentile bands summarize the deliberately sampled governance rules. They are not confidence intervals or forecasts of how laboratory members will behave.
2. **Fixed historical requests:** the model does not estimate how researchers might substitute trips, switch to remote participation, adapt destinations, or change future travel demand under a real carbon policy.
3. **Trip count is not scientific value:** preserving more missions does not necessarily preserve more valuable missions. Mission importance is not measured.
4. **Headcount approximation:** individual/team budgets use observed travelers rather than complete staff rosters, and the comparison is sensitive to this definition.
5. **Governance assumptions:** sequential processing uses mission dates as a proxy for request dates; other families may rank an entire year's requests with retrospective knowledge. Family parameter ranges differ.
6. **Expected outcomes:** results can reflect mixtures of two indivisible allocation scenarios; plot coordinates and calibrated budget values should not be mistaken for guaranteed annual allocations.
7. **Discreteness:** severe-restriction indicators are thresholded and depend on the finite number of observed traveler-years. Step-like curves, particularly under mild reduction targets, should not be smoothed into apparent precision.

The input workbook can contain pseudonymized person-level information. Keep raw inputs and unreviewed output files out of public repositories. The exported JSON reports omit original person identifiers but may still warrant review before sharing.

---

**Reproducibility:** For comparable experiments, document the input workbook/version (or its exported SHA-256), the random seed, the number of sampled rules, and any departures from the default calibration and pooling grids. The four final figures are regenerated from the simulation JSON without rerunning the allocation model.
