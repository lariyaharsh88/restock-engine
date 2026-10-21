"""Run every policy on the same simulated store(s) and write the numbers the case study quotes.

  python scripts/run_backtest.py                 # seeds 1..5, unconstrained cash
  python scripts/run_backtest.py --budget 0.8    # weekly cash = 80% of what the engine would spend unconstrained
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim.backtest import POLICIES, run_backtest  # noqa: E402
from sim.generator import make_store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = ["fill_rate", "stockout_sku_days_pct", "avg_inventory_value", "inventory_turns_annualised",
        "waste_pct_of_purchases", "lost_margin", "realised_margin", "gmroi", "orders_placed", "order_lines"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--warmup", type=int, default=90)
    ap.add_argument("--budget", type=float, default=None, help="weekly cash as a fraction of the engine's unconstrained spend")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    results = {name: [] for name in POLICIES}
    for seed in a.seeds:
        store = make_store(seed, horizon_days=a.days)
        budget_per_day = None
        if a.budget is not None:
            base = run_backtest(POLICIES["engine"], store=store, seed=seed, days=a.days, warmup=a.warmup)
            budget_per_day = a.budget * base["purchase_value"] / (a.days - a.warmup)
        for name, fn in POLICIES.items():
            r = run_backtest(fn, store=store, seed=seed, days=a.days, warmup=a.warmup, budget_per_day=budget_per_day)
            r["seed"] = seed
            results[name].append(r)
            print(f"seed {seed:2d} {name:9s} fill {r['fill_rate']:.3f}  stockout-days {r['stockout_sku_days_pct']:.3f}  "
                  f"avg inv {r['avg_inventory_value']:>10,.0f}  turns {r['inventory_turns_annualised']:5.1f}  "
                  f"waste {r['waste_pct_of_purchases']:.3f}  lost margin {r['lost_margin']:>9,.0f}")

    summary = {}
    for name, rows in results.items():
        summary[name] = {k: statistics.mean(r[k] for r in rows) for k in KEYS}
        summary[name].update({k + "_sd": (statistics.pstdev(r[k] for r in rows) if len(rows) > 1 else 0.0) for k in KEYS})
    tag = a.tag or (f"budget{a.budget}" if a.budget is not None else "unconstrained")
    out = {"run_at": datetime.now().isoformat(timespec="seconds"), "seeds": a.seeds, "days": a.days, "warmup": a.warmup,
           "budget_fraction": a.budget, "per_seed": results, "mean": summary}
    os.makedirs(os.path.join(ROOT, "evals", "results"), exist_ok=True)
    path = os.path.join(ROOT, "evals", "results", f"backtest_{tag}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)

    print("\nMean over seeds", a.seeds, f"({tag})")
    print(f"{'policy':9s} {'fill':>6s} {'so-days':>8s} {'avg inv':>10s} {'turns':>6s} {'waste':>6s} {'lost margin':>12s} {'GMROI':>6s}")
    for name, s in summary.items():
        print(f"{name:9s} {s['fill_rate']:6.3f} {s['stockout_sku_days_pct']:8.3f} {s['avg_inventory_value']:10,.0f} "
              f"{s['inventory_turns_annualised']:6.1f} {s['waste_pct_of_purchases']:6.3f} {s['lost_margin']:12,.0f} {s['gmroi']:6.2f}")

    log = os.path.join(ROOT, "docs", "metrics-log.csv")
    new = not os.path.exists(log)
    with open(log, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["run_at", "tag", "policy", "seeds"] + KEYS)
        for name, s in summary.items():
            w.writerow([out["run_at"], tag, name, " ".join(map(str, a.seeds))] + [round(s[k], 4) for k in KEYS])
    print(f"\nwrote {os.path.relpath(path, ROOT)} and appended docs/metrics-log.csv")


if __name__ == "__main__":
    main()
