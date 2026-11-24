# 🦌 CARIBOU

<p align="center"><img src="caribou.png" alt="CARIBOU logo" width="300"></p>

**One team. Many trips. Shared carbon budgets.**

CARIBOU helps research teams understand their travel emissions and explore how carbon budgets could affect their missions. It turns travel records into complete missions, makes their footprint visible, and compares individual and shared team budgets at different emission-reduction targets.

It runs locally in your browser. Your data and results stay in the current session until you download them.

## What you can do

- **Prepare your travel data:** import an Excel workbook, match your columns, and combine travel segments into complete missions.
- **Estimate emissions:** use existing estimates or calculate them from travel locations and transportation modes, with optional round-trip settings.
- **Explore your footprint:** filter charts by year, team or mission purpose, and generate a dataset summary and emissions histogram.
- **Compare carbon budgets:** choose reduction targets and explore how individual and pooled team budgets affect mission preservation and the distribution of restrictions.
- **Share the results:** preview figures and tables, then download Excel inputs, JSON simulation reports, PNG/PDF figures and Markdown/LaTeX tables.

## Get started

Requires Python 3.10+ and Python virtual-environment support. No API key is needed.

On Linux:

```bash
git clone https://github.com/gwenole-quellec/caribou.git
cd caribou
./start.sh
```

Dependencies are installed automatically on first launch and updated when the requirements files change.

Alternatively, on other operating systems:

```bash
git clone https://github.com/gwenole-quellec/caribou.git
cd caribou
python -m pip install -r requirements-ui.txt
python -m streamlit run caribou.py
```

Open [http://localhost:8501](http://localhost:8501).

**Command-line use only:** install the calculation dependencies with `python -m pip install -r requirements.txt`.

1. **Prepare:** choose **Simple preparation** if emissions are already available, or **Advanced preparation** to estimate them from travel records. Download `carbon_footprint.xlsx`, ready for simulation.
2. **Visualize:** inspect your prepared missions and generate a descriptive table and histogram. Chart filters do not change the simulation input.
3. **Simulate:** use the prepared data or upload a missions workbook. Adjust the targets and sampling settings, then follow the progress bar.
4. **Export:** open **Artifacts** to generate, preview and download the simulation figures and outcome table.

Already have a CARIBOU missions workbook? Go straight to **Simulation**. Already have simulation reports? Upload them in **Artifacts**.

## Designed for research travel

Each mission has a unique ID and each traveler a stable ID. Combining segments sums their emissions, keeps the earliest departure date and joins their purposes. The exported `missions` sheet is ready for simulation.

Mission-type exclusions match complete labels; mixed-purpose missions remain included unless their full label is selected.

Missions without a team remain in the prepared workbook and charts, but are excluded from simulations. Simulated team sizes count eligible travelers, not complete staff rosters.

Emissions use geographic distances and transportation factors adapted from [GES 1point5](https://doi.org/10.1088/2634-4505/ac84a4). Geocoding sends city/country pairs to OpenStreetMap Nominatim; save the cache to reuse coordinates offline. Round trips double emissions; taxi estimates also include an empty vehicle return. Car and taxi estimates are per vehicle.

### Restriction rates by category

Compare refusal rates by mission purpose and personnel category; map your staff-category column to `personnel_category` during preparation. Missions with several purposes contribute to each purpose. In **Artifacts**, **Mission preservation by category** shows the effects of 20% and 50% pooling, with options to hide or rename categories.

## Scenarios, not predictions

CARIBOU compares hypothetical prioritization rules to support discussion, not prescribe policy or predict decisions. Ranges reflect variation across sampled rules, not confidence intervals. Reduction targets are matched in expectation; missions remain indivisible.

The default simulation tests reductions of **5, 10, 15 and 20%**, with **10,000 sampled rules**, **seed 42** and no mission-purpose exclusions. Try fewer rules for a quick run. Keep per-rule results enabled and the default targets and pooling fractions to generate all standard artifacts.

## Local and open source

Download your results before closing or restarting the app: session data and temporary files are not a project backup. Never commit identifying travel records or geocoding caches to a public repository.

Command-line simulations and reporting remain available through `python -m caribou_simulation.<module>` and `python -m caribou_data.describe_missions`; use `--help` for options. Command-line outputs default to `artifacts/`, with simulation JSON reports in `artifacts/results/`.

*CARIBOU: Carbon Allocation for Research trIps: Budget Optimization and Utilization.*

License: [BSD 3-Clause](LICENSE).
