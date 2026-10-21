"""One call that turns inputs into recommendations. Used by the web app, the simulator and scripts."""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from .allocate import allocate_budget, apply_min_order_value
from .explain import explain
from .forecast import forecast_sku
from .policy import classify_abc, recommend
from .schema import DemandHistory, Forecast, PolicyParams, Product, Recommendation, StockState, Supplier


def plan_orders(products: Dict[str, Product], suppliers: Dict[str, Supplier], stock: Dict[str, StockState],
                history: Dict[str, DemandHistory], today: date, budget: Optional[float] = None,
                params: Optional[PolicyParams] = None) -> List[Recommendation]:
    p = params or PolicyParams()
    # category averages as cold-start fallbacks
    first_pass: Dict[str, Forecast] = {s: forecast_sku(h, p) for s, h in history.items()}
    cat_avg: Dict[str, List[float]] = {}
    for s, f in first_pass.items():
        if f.method != "cold_start" and s in products:
            cat_avg.setdefault(products[s].category, []).append(f.daily_mean)
    forecasts: Dict[str, Forecast] = {}
    for sku, pr in products.items():
        h = history.get(sku) or DemandHistory(sku, [], [], [])
        fb = cat_avg.get(pr.category)
        forecasts[sku] = forecast_sku(h, p, fallback_daily_mean=(sum(fb) / len(fb)) if fb else None)
    abc = classify_abc(products.values(), forecasts, p)
    recs: List[Recommendation] = []
    for sku, pr in products.items():
        st = stock.get(sku) or StockState(sku, 0, 0)
        recs.append(recommend(pr, suppliers[pr.supplier_id], st, forecasts[sku], today, abc.get(sku, "C"), p))
    apply_min_order_value(recs, products, suppliers, p)
    allocate_budget(recs, products, budget)
    for r in recs:
        r.explanation = explain(r, products[r.sku], suppliers[products[r.sku].supplier_id])
    recs.sort(key=lambda r: (r.status != "order", -r.priority, r.sku))
    return recs
