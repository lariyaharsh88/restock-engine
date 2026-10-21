# Metric definitions

Every number in the case study is one of these, computed by `sim/backtest.py` or `evals/forecast_eval.py`
and written to `evals/results/` and `docs/metrics-log.csv`.

| Metric | Definition | Direction | Notes |
|---|---|---|---|
| Fill rate | units sold / units demanded, over the evaluation window | higher | the simulator knows true demand; a real store only knows it with a stockout flag |
| Stockout SKU-days | share of (SKU, day) pairs that started the day with zero on hand | lower | the pilot north star, because a store can count it |
| Average inventory value | mean over days of Σ on_hand × unit_cost | lower, with fill rate held | cash tied up |
| Inventory turns (annualised) | COGS of units sold / average inventory value × 365 / days | higher | |
| Waste (% of purchases) | value of expired units / value of units purchased | lower | perishables only contribute |
| Lost margin | Σ unmet units × unit margin | lower | what empty shelves cost |
| Realised margin | Σ sold units × unit margin | higher | the number that matters under a cash cap |
| GMROI | realised margin / average inventory value, annualised | higher | margin earned per rupee of stock |
| Orders placed | review points at which at least one line was ordered | context | |
| Order lines | SKU lines ordered | lower, with fill rate held | handling cost; the engine's weak spot in V1 |
| WAPE | Σ abs(forecast − actual) / Σ actual, 7-day horizon, weekly checkpoints after warm-up | lower | computed on uncensored true demand in the simulator |

Benchmark protocol:
- 120 SKUs, 4 suppliers, 365 days, first 90 days warm-up (history only, no measurement).
- Seeds 1-5 for the policy comparison. Demand and lead-time draws are identical across policies for a seed.
- Forecast parameters were tuned on seeds 1-5 and are reported on holdout seeds 6-10.
- Cash-constrained run: weekly cash = 80% × (the engine's unconstrained purchase value / evaluation days) × 7,
  released weekly, same budget for every policy.

What the benchmark cannot show: real owners' acceptance, real export quality, real promo behaviour. Those
come from pilots (PRD §13) and go into the same log with `tag=pilot_<store>`.
