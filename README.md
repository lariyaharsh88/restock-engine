# ReStock (working name)

What should a small retailer order today, how much, from whom, and why? Four CSV exports go in, an order
list comes out, and every line carries a paragraph a shop owner can check with a calculator.

Pure rules, no API keys, no integrations, no database. The decision logic is a library of pure functions
with unit tests; a built-in simulator backtests it against the two spreadsheet policies the segment actually
uses, and those numbers are the case study.

```
engine/     forecast (censoring-aware, DOW, intermittent, cold start), order-up-to policy, caps,
            cash-budget allocation, supplier minimums, explanation. Standard library only.
sim/        synthetic store generator + day-by-day backtest with FEFO, expiry, lead-time noise
evals/      forecast accuracy eval, smoothing sweep, results JSON
scripts/    run_backtest.py (the benchmark), make_sample_data.py (the demo store)
web/        FastAPI + Jinja: Today, Order list (with cash box), SKU page, Backtest, Upload, JSON
tests/      19 hand-checkable tests; every worked example in docs/LOGIC.md is here with the same numbers
docs/       PRD.md, LOGIC.md, CASE_STUDY.md, STARTUP.md, METRICS.md, metrics-log.csv
data/sample four CSVs exported from the simulator so the app runs with no setup (flagged in the UI)
```

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q tests
.venv/bin/uvicorn web.app:app --reload --port 8020
```

Reproduce the numbers in the case study:

```bash
.venv/bin/python scripts/run_backtest.py                 # 3 policies × 5 seeds, unconstrained cash
.venv/bin/python scripts/run_backtest.py --budget 0.8    # weekly cash capped at 80% of engine spend
.venv/bin/python evals/forecast_eval.py                  # 7-day WAPE on holdout seeds 6-10
./evals/sweep_alpha.sh                                   # how the smoothing constant was chosen (seeds 1-5)
```

## Headline (simulated 120-SKU store, 5 seeds, 365 days)

| | Gut feel | Min–max spreadsheet | ReStock |
|---|---|---|---|
| Fill rate | 90.7% | 98.1% | **98.1%** |
| Average inventory | ₹19.3 L | ₹39.9 L | **₹13.6 L** |
| Perishable waste (% of purchases) | 24.2% | 44.7% | **0.4%** |
| Gross margin with cash capped at 80% | ₹76.5 L | ₹77.3 L | **₹94.6 L** |

These are simulator results and the case study says exactly what they do and do not prove. The pilot that
would replace them with customer numbers is specified in `docs/PRD.md` §13.

## Bring your own store

Upload `products.csv`, `suppliers.csv`, `sales.csv`, `stock.csv` on the Your data page. Column contract in
`docs/LOGIC.md` §1 and in `data/sample/`. The optional `stockout` column in sales is the one that matters:
an empty shelf is not zero demand.

## Scope choices

- No machine-learned forecasting until a store has years of clean data; the segment has weeks of noisy counts.
- Assisted ordering only. Auto-order needs pilot trust first.
- Greedy budget allocation on purpose: auditable beats optimal here.
- Everything the UI shows is a field on the JSON at `/api/orders`.
