"""Forecast accuracy on simulated stores where true demand is known.

Compares the engine forecast to two naive baselines a spreadsheet would use, on uncensored demand,
over a 7-day horizon, at every weekly checkpoint after warm-up. Metric: WAPE (sum |err| / sum actual).
"""
from __future__ import annotations

import json
import os
import random
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.forecast import forecast_sku  # noqa: E402
from engine.schema import DemandHistory  # noqa: E402
from sim.generator import make_store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(seeds=(1, 2, 3, 4, 5), days=365, warmup=90, horizon=7, params=None):
    from engine.schema import PolicyParams
    params = params or PolicyParams()
    totals = {"engine": [0.0, 0.0], "avg_28d": [0.0, 0.0], "same_week_last": [0.0, 0.0]}
    for seed in seeds:
        store = make_store(seed, horizon_days=days)
        rng = random.Random(seed * 7919 + 1)
        demand = {sku: [store.true_demand(rng, sku, d) for d in range(days)] for sku in store.products}
        # NB: draws are consumed sku-major here vs day-major in the backtest, so this is a fresh sample of the
        # same process, which is fine for a forecast eval.
        for t in range(warmup, days - horizon, 7):
            for sku in store.products:
                dates = [store.start + timedelta(days=i) for i in range(t)]
                h = DemandHistory(sku, dates, demand[sku][:t])
                actual = sum(demand[sku][t:t + horizon])
                f = forecast_sku(h, params)
                preds = {
                    "engine": f.expected(store.start + timedelta(days=t), horizon),
                    "avg_28d": sum(demand[sku][t - 28:t]) / 28 * horizon,
                    "same_week_last": sum(demand[sku][t - 7:t]),
                }
                for k, p in preds.items():
                    totals[k][0] += abs(p - actual)
                    totals[k][1] += actual
    return {k: v[0] / max(v[1], 1) for k, v in totals.items()}


if __name__ == "__main__":
    import argparse
    from engine import forecast as fmod
    from engine.schema import PolicyParams
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[6, 7, 8, 9, 10], help="holdout seeds; 1-5 were used for tuning")
    ap.add_argument("--alpha", type=float, default=None)
    ap.add_argument("--no-dow", action="store_true", help="disable the day-of-week index")
    ap.add_argument("--horizon", type=int, default=7)
    ap.add_argument("--out", default="forecast_eval.json")
    a = ap.parse_args()
    params = PolicyParams()
    if a.alpha is not None:
        params.ewma_alpha = a.alpha
    if a.no_dow:
        fmod.DOW_SHRINK_K = 1e9
    res = run(seeds=tuple(a.seeds), horizon=a.horizon, params=params)
    res["_config"] = {"seeds": a.seeds, "alpha": params.ewma_alpha, "dow": not a.no_dow, "horizon": a.horizon}
    for k, v in res.items():
        if not k.startswith("_"):
            print(f"{k:16s} WAPE {v:.3f}")
    os.makedirs(os.path.join(ROOT, "evals", "results"), exist_ok=True)
    with open(os.path.join(ROOT, "evals", "results", a.out), "w") as f:
        json.dump(res, f, indent=2)
