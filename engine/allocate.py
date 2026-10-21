"""Cross-SKU constraints: a cash budget for this order cycle, and supplier minimum order values.

Budget: greedy by priority = expected lost margin per rupee. Lines that don't fit are cut to the
number of packs that do; lines that can't afford one pack are deferred with the reason recorded.
This is a knapsack heuristic, not optimal, and that is the point: a shop owner can audit it.

Supplier minimum: if the order to a supplier is short of its minimum by <= 30%, top up one pack
at a time starting with the SKU with the fewest days of cover. Otherwise defer the whole supplier
order to the next review (ordering filler to hit a minimum is how dead stock is born).
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from .schema import Cap, PolicyParams, Product, Recommendation, Supplier


def allocate_budget(recs: List[Recommendation], products: Dict[str, Product], budget: Optional[float]) -> List[Recommendation]:
    if budget is None:
        return recs
    remaining = float(budget)
    order = sorted((r for r in recs if r.is_order), key=lambda r: (r.priority, r.abc_class == "A"), reverse=True)
    for r in order:
        pr = products[r.sku]
        if r.line_cost <= remaining:
            remaining -= r.line_cost
            continue
        pack_cost = pr.unit_cost * max(pr.pack_size, 1)
        packs = int(math.floor(remaining / pack_cost)) if pack_cost > 0 else 0
        new_qty = packs * max(pr.pack_size, 1)
        if new_qty > 0:
            r.caps.append(Cap("budget", r.qty, new_qty, f"cash budget: only {new_qty} fit in the remaining budget"))
            r.qty = new_qty
            r.line_cost = new_qty * pr.unit_cost
            remaining -= r.line_cost
        else:
            r.caps.append(Cap("budget", r.qty, 0, "cash budget exhausted; higher-priority SKUs were funded first"))
            r.qty = 0
            r.line_cost = 0.0
            r.status = "deferred"
    return recs


def apply_min_order_value(recs: List[Recommendation], products: Dict[str, Product], suppliers: Dict[str, Supplier],
                          params: Optional[PolicyParams] = None) -> List[Recommendation]:
    p = params or PolicyParams()
    by_sup: Dict[str, List[Recommendation]] = {}
    for r in recs:
        if r.is_order:
            by_sup.setdefault(products[r.sku].supplier_id, []).append(r)
    for sid, lines in by_sup.items():
        sup = suppliers[sid]
        if sup.min_order_value <= 0:
            continue
        total = sum(r.line_cost for r in lines)
        if total >= sup.min_order_value:
            continue
        gap = sup.min_order_value - total
        if gap > p.mov_topup_tolerance * sup.min_order_value:
            for r in lines:
                r.caps.append(Cap("min_order_value", r.qty, 0,
                                  f"{sup.name} minimum is {sup.min_order_value:.0f}; this cycle's need is only {total:.0f}, deferring"))
                r.qty, r.line_cost, r.status = 0, 0.0, "deferred"
            continue
        # top up, fewest days of cover first, one pack per pass
        lines_sorted = sorted(lines, key=lambda r: r.days_of_cover)
        guard = 0
        while total < sup.min_order_value and guard < 1000:
            guard += 1
            for r in lines_sorted:
                pr = products[r.sku]
                add = max(pr.pack_size, 1)
                before = r.qty
                r.qty += add
                r.line_cost = r.qty * pr.unit_cost
                total += add * pr.unit_cost
                existing = next((c for c in r.caps if c.name == "min_order_value"), None)
                if existing:
                    existing.qty_after = r.qty
                else:
                    r.caps.append(Cap("min_order_value", before, r.qty, f"topped up to reach {sup.name} minimum of {sup.min_order_value:.0f}"))
                if total >= sup.min_order_value:
                    break
    return recs
