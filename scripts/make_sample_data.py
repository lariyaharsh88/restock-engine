"""Export a realistic sample dataset (the four CSVs) from the simulator so the app runs with no setup.

Replays 120 days under the engine so stock levels and open orders look like a real shop, then dumps
the visible state. Everything here is synthetic and flagged as such in the UI.
"""
from __future__ import annotations

import csv
import os
import random
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.schema import DemandHistory, StockState  # noqa: E402
from sim import backtest as B  # noqa: E402
from sim.generator import make_store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "sample")


def main(seed: int = 7, days: int = 120) -> None:
    store = make_store(seed, horizon_days=days + 60)
    rng = random.Random(seed * 7919 + 1)
    lt_rng = random.Random(seed * 104729 + 2)
    state = B.SimState()
    for sku, pr in store.products.items():
        q = int(round(store.truth[sku].base_mean * 10))
        exp = store.start + timedelta(days=pr.shelf_life_days) if pr.shelf_life_days else None
        state.lots[sku] = [B._Lot(q, exp)]
        state.hist_dates[sku], state.hist_qty[sku], state.hist_so[sku] = [], [], []
    sup_of = {s: store.suppliers[p.supplier_id] for s, p in store.products.items()}
    policy = B.POLICIES["engine"]
    for day in range(days):
        today = store.start + timedelta(days=day)
        arrived = [p for p in state.pipeline if p[0] <= day]
        state.pipeline = [p for p in state.pipeline if p[0] > day]
        for _, s, q in arrived:
            pr = store.products[s]
            state.lots[s].append(B._Lot(q, today + timedelta(days=pr.shelf_life_days) if pr.shelf_life_days else None))
        for s, pr in store.products.items():
            d = store.true_demand(rng, s, day)
            oh = B._on_hand(state, s)
            rem = d
            for lot in sorted(state.lots[s], key=lambda l: (l.expires_on is None, l.expires_on or today)):
                t = min(lot.qty, rem)
                lot.qty -= t
                rem -= t
                if rem == 0:
                    break
            state.hist_dates[s].append(today)
            state.hist_qty[s].append(d - rem)
            state.hist_so[s].append(oh == 0 or rem > 0)
            for lot in state.lots[s]:
                if lot.expires_on is not None and lot.expires_on <= today:
                    lot.qty = 0
            state.lots[s] = [l for l in state.lots[s] if l.qty > 0]
        if day == days - 1:
            break  # dump state before today's ordering so the app has something to recommend
        review = [s for s in store.products if day % sup_of[s].review_period_days == 0]
        vis = B.Visible(today, store.products, store.suppliers,
                        {s: StockState(s, B._on_hand(state, s), B._on_order(state, s)) for s in store.products},
                        {s: DemandHistory(s, state.hist_dates[s], state.hist_qty[s], state.hist_so[s]) for s in store.products},
                        review, None)
        for s, q in policy(vis).items():
            if q > 0 and s in review:
                su = sup_of[s]
                lt = max(1, int(round(lt_rng.gauss(su.lead_time_days, su.lead_time_sd_days))))
                state.pipeline.append((day + lt, s, q))

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "products.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sku", "name", "category", "unit_cost", "sell_price", "supplier_id", "pack_size", "shelf_life_days"])
        for p in store.products.values():
            w.writerow([p.sku, p.name, p.category, p.unit_cost, p.sell_price, p.supplier_id, p.pack_size, p.shelf_life_days or ""])
    with open(os.path.join(OUT, "suppliers.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["supplier_id", "name", "lead_time_days", "lead_time_sd_days", "review_period_days", "min_order_value"])
        for s in store.suppliers.values():
            w.writerow([s.supplier_id, s.name, s.lead_time_days, s.lead_time_sd_days, s.review_period_days, s.min_order_value])
    with open(os.path.join(OUT, "sales.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "sku", "qty_sold", "stockout"])
        for s in store.products:
            for d, q, so in zip(state.hist_dates[s], state.hist_qty[s], state.hist_so[s]):
                w.writerow([d.isoformat(), s, q, 1 if so else 0])
    with open(os.path.join(OUT, "stock.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sku", "on_hand", "on_order"])
        for s in store.products:
            w.writerow([s, B._on_hand(state, s), B._on_order(state, s)])
    print(f"wrote 4 CSVs to {os.path.relpath(OUT, ROOT)}: {len(store.products)} SKUs, {days} days, as of {today.isoformat()}")


if __name__ == "__main__":
    main()
