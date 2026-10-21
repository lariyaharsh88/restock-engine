"""Turn a Recommendation into the sentence a shop owner reads. Every number in it is in the object."""
from __future__ import annotations

from .schema import Product, Recommendation, Supplier


def explain(r: Recommendation, product: Product, supplier: Supplier) -> str:
    f = r.forecast
    daily = f.daily_mean if f else 0.0
    parts = [
        f"Sells ~{daily:.1f}/day ({f.method.replace('_', ' ') if f else 'n/a'}, {f.n_days_used if f else 0} days of data).",
        f"Must cover {r.protection_days} days ({supplier.lead_time_days} lead + {supplier.review_period_days} until next order) "
        f"= {r.expected_demand:.0f} expected + {r.safety_stock:.0f} safety for a {r.service_level:.0%} service level (class {r.abc_class}).",
        f"Target {r.order_up_to:.0f}; holding {r.inventory_position} (on hand + on order).",
    ]
    if r.status == "ok":
        parts.append(f"Enough for now: {r.days_of_cover:.0f} days of cover, {r.stockout_risk:.0%} risk before next delivery.")
    elif r.status == "deferred":
        why = r.caps[-1].reason if r.caps else "deferred"
        parts.append(f"Deferred: {why}.")
    else:
        parts.append(f"Order {r.qty}" + (f" ({r.qty // product.pack_size} packs of {product.pack_size})" if product.pack_size > 1 else "") + ".")
        for c in r.caps:
            parts.append(f"{c.qty_before} -> {c.qty_after}: {c.reason}.")
        parts.append(f"Without it: {r.stockout_risk:.0%} stockout risk, ~{r.expected_shortfall_units:.0f} units lost, "
                     f"Rs {r.expected_lost_margin:.0f} margin at stake.")
    return " ".join(parts)
