# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

An **isotope generator calculator** — a Flask web app (and companion Jupyter notebook) that simulates the parent→daughter activity of radioisotope generators over time, with fixed-interval milking. Despite the repo name, it has nothing to do with expression parsers.

## Environment

Always activate the virtual environment first:
```bash
source .venv/bin/activate
```

Install / update dependencies:
```bash
pip install -r requirements.txt          # dev (includes jupyterlab, matplotlib, etc.)
pip install -r requirements-prod.txt     # prod (flask, gunicorn, radioactivedecay, numpy)
pip freeze > requirements.txt            # after adding a new package
```

## Running the app

```bash
# Dev server (port 5000)
python run.py
FLASK_DEBUG=true python run.py           # with auto-reload

# Production (used by Railway / Procfile)
gunicorn --bind 0.0.0.0:$PORT run:app

# JupyterLab (run from project root so paths resolve)
jupyter lab
```

## Database

`instance/generator.db` is a pre-seeded SQLite file committed to the repo. It is **read-only at runtime**. To rebuild it from scratch (requires `radioactivedecay`):
```bash
python scripts/seed_db.py
```

The seed script pulls nuclide data from the ICRP-107 dataset via the `radioactivedecay` library. `HALF_LIFE_CORRECTIONS` in that script overrides known-bad ICRP-107 values (e.g. Ac-225 is corrected to 9.919 d).

Schema:
- `isotopes(symbol, name, half_life_s, atomic_number, mass_number)` — stable nuclides have `half_life_s = 1e30`
- `decay_modes(parent_symbol, daughter_symbol, branching_ratio, mode)`
- `generator_presets(display_name, parent_symbol, intermediate_symbols JSON, daughter_symbol, sort_order)`

## Architecture

### Layer model

```
Frontend (JS + Plotly)
    ↓ POST /api/calculate
app/routes/api.py          ← unit conversion, DB lookups, input validation
    ↓ SI-unit calls
app/physics.py             ← pure math, no Flask, importable from notebook too
    ↑
instance/generator.db      ← half-lives and branching ratios
```

### `app/physics.py` — the physics core

All inputs/outputs are in SI units (seconds, atom counts). Two solvers:

- **`simulate_generator`** — analytic Bateman equation for a 2-member chain (parent→daughter). Handles the λ₁ ≈ λ₂ degenerate case via L'Hôpital. Fastest path.
- **`simulate_chain`** — matrix-exponential solver (`scipy.linalg.expm`) for N-member linear chains. Handles any chain length without special cases.

Both walk fixed milking intervals: the last species is reset to zero at each milking; all others carry over. Corresponding `infer_duration` / `infer_duration_chain` walk cycles until yield falls below a threshold atom count.

`activity_from_atoms(N, λ)` → `λ * N / 1e6` (MBq).

### `app/routes/api.py` — the API layer

Single endpoint `POST /api/calculate`. Responsibilities:
- Parse and validate user inputs (symbols, MBq, hours)
- Look up half-lives from the DB; compute λ = ln2 / t½
- Convert initial activity (MBq) → atom count: N₀ = A·10⁶ / λ
- Dispatch to the 2-member or N-member solver depending on whether intermediates are present
- Convert results back to hours and MBq for the response

Generator yield % is **not** handled by the backend — the frontend divides `min_yield_MBq` by `genYield` before sending, and multiplies yields back when rendering the table.

### Frontend (`static/js/app.js`)

Vanilla JS, no framework. Key behaviours:
- Time units auto-scale based on the isotope half-life: picks the unit where the half-life falls in [1, 100) (seconds → centuries). Parent half-life drives the x-axis / duration input; daughter half-life drives the milking interval input.
- Daughter activity curve inserts explicit drops to zero at each milking time (for the visual sawtooth shape).
- Two tabs: **Decay Chart** (Plotly line chart) and **Milking Events** (cumulative bar chart + table).

### `generator_notebook.ipynb`

Mirrors the web app exactly. Imports from `app.physics` directly (run from project root). Uses matplotlib for plots, pandas for the milking events table. Same auto time-unit logic as the JS.
